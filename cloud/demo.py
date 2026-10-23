"""Empresa de demostración con 4 sedes y 30 días de datos inventados, para enseñar el panel.

    python -m cloud.demo                 → crea la empresa "Demo" (usuario demo@traffiqui.com / demo1234)
    python -m cloud.demo --simular       → además, envía estados en vivo cada 3 s a http://localhost:9000
                                           como si las 4 tiendas estuvieran abiertas (Ctrl+C para parar)
    python -m cloud.demo --licencia TQ1… → licencia para la empresa "Demo" (sin ella, solo 1 sede envía en vivo)

Los datos son simulados: curva de horas de una tienda de barrio con ruido, un plano con pasillos y cajas,
recorridos y mapa de calor. Van en una empresa propia ("Demo"), nunca se mezclan con una real.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import math
import random
import sys
import time
import urllib.request
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
from sqlalchemy import insert, select, update

from app.config import DATA_DIR
from cloud.db import make_engine, organizations, sites, users
from cloud.ingest import ingest
from cloud.security import hash_password, new_site_key, sha256

SITES = [("Sede Chacao", 1.0), ("Sede Altamira", 0.75), ("Sede Las Mercedes", 0.55), ("Sede El Hatillo", 0.35)]
TZ = "America/Caracas"
KEYS_FILE = DATA_DIR / "demo-claves.json"
W, D, CELL = 16.0, 10.0, 0.25
AREAS = [("Bebidas", "pasillo", 2.0), ("Limpieza", "pasillo", 5.0), ("Snacks", "pasillo", 8.0), ("Farmacia", "pasillo", 11.0)]
CAJAS = [("Caja 1", 13.6, 3.0), ("Caja 2", 13.6, 6.0)]


def floorplan() -> dict:
    rid = lambda: uuid.uuid4().hex[:8]  # noqa: E731
    els = [{"id": rid(), "type": "wall", "points": [[0, 0], [W, 0], [W, D], [9, D]], "thickness": 0.15},
           {"id": rid(), "type": "wall", "points": [[6, D], [0, D], [0, 0]], "thickness": 0.15},
           {"id": rid(), "type": "door", "points": [[6, D], [9, D]], "label": "Entrada", "role": "both"}]
    for i, (_, _, x) in enumerate(AREAS):
        els.append({"id": rid(), "type": "gondola", "x": x + 1.5, "y": 4.0, "w": 0.8, "d": 5.0, "rot": 0})
    for name, kind, x in AREAS:
        els.append({"id": rid(), "type": "area", "name": name, "kind": kind,
                    "points": [[x - 0.6, 1.5], [x + 1.0, 1.5], [x + 1.0, 6.5], [x - 0.6, 6.5]]})
    for name, x, y in CAJAS:
        els.append({"id": rid(), "type": "checkout", "x": x + 1.2, "y": y, "w": 1.2, "d": 0.7, "rot": 0})
        els.append({"id": rid(), "type": "area", "name": name, "kind": "caja",
                    "points": [[x - 0.6, y - 0.8], [x + 0.5, y - 0.8], [x + 0.5, y + 0.8], [x - 0.6, y + 0.8]]})
    return {"name": "Demo", "width": W, "depth": D, "grid": 0.5, "elements": els}


def _hour_weight(h: int, weekend: bool) -> float:
    if not 8 <= h <= 20:
        return 0.0
    w = math.exp(-((h - 11.5) / 2.2) ** 2) + 0.8 * math.exp(-((h - 17.5) / 1.8) ** 2)
    return w * (1.3 if weekend else 1.0)


def _pack(grid: np.ndarray) -> str:
    buf = io.BytesIO()
    np.savez_compressed(buf, grid=grid.astype(np.float32))
    return base64.b64encode(buf.getvalue()).decode()


def _site_rows(scale: float, days: int, rnd: random.Random, now: float) -> dict:
    zone = ZoneInfo(TZ)
    today = datetime.fromtimestamp(now, zone).replace(hour=0, minute=0, second=0, microsecond=0)
    tracks, doors, occ, visits, trans, heat = [], [], [], [], [], []
    rows_n, cols_n = int(D / CELL), int(W / CELL)
    gid = 0
    for d in range(days - 1, -1, -1):
        day = today - timedelta(days=d)
        weekend = day.weekday() >= 5
        day_heat = np.zeros((rows_n, cols_n), np.float32)
        for h in range(24):
            if not _hour_weight(h, weekend):
                continue
            n = rnd.gauss(28 * scale * _hour_weight(h, weekend), 2)
            for _ in range(max(0, round(n))):
                first = (day + timedelta(hours=h, seconds=rnd.uniform(0, 3600))).timestamp()
                dur = max(20.0, rnd.lognormvariate(5.2, 0.6))
                if first + dur > now:
                    continue
                gid += 1
                buyer = rnd.random() < 0.42
                route = rnd.sample([a[0] for a in AREAS], k=rnd.randint(1, 3))
                caja = rnd.choice(CAJAS)[0] if buyer else None
                if caja:
                    route.append(caja)
                t = first + 5
                for i, name in enumerate(route):
                    stay = rnd.uniform(4, 40) if name.startswith("Caja") is False else rnd.uniform(25, 120)
                    visits.append({"id": len(visits) + 1, "session_id": 1, "global_id": gid, "area_id": name,
                                   "area_name": name, "enter_ts": t, "exit_ts": t + stay, "duration": stay})
                    if i:
                        trans.append({"id": len(trans) + 1, "session_id": 1, "global_id": gid, "from_id": route[i - 1],
                                      "from_name": route[i - 1], "to_id": name, "to_name": name, "ts": t})
                    x = next((a[2] for a in AREAS if a[0] == name), None)
                    cx = (x + 0.2) if x is not None else 13.5
                    for _ in range(int(stay // 3)):
                        r_, c_ = int(rnd.uniform(2, 6.5) / CELL), int(rnd.gauss(cx, 0.4) / CELL)
                        if 0 <= r_ < rows_n and 0 <= c_ < cols_n:
                            day_heat[r_, c_] += 1
                    t += stay
                tracks.append({"id": gid, "session_id": 1, "global_id": gid, "first_seen": first, "last_seen": first + dur,
                               "duration": dur, "is_buyer": int(buyer), "checkout_seconds": rnd.uniform(25, 120) if buyer else 0,
                               "checkout_area": caja, "checkout_area_id": caja, "is_staff": 0, "changed_at": first + dur})
                doors.append({"id": len(doors) + 1, "session_id": 1, "global_id": gid, "door_id": "d1",
                              "door_name": "Entrada", "direction": "in", "ts": first})
            ts = (day + timedelta(hours=h, minutes=30)).timestamp()
            if ts < now:
                peak = max(0, round(n * 0.35 + rnd.uniform(0, 2)))
                occ.append({"id": len(occ) + 1, "session_id": 1, "ts": ts, "people": peak,
                            "people_max": peak + 1, "people_avg": peak * 0.8})
        if day_heat.sum() > 0:
            heat.append({"id": len(heat) + 1, "session_id": 1, "ts_start": day.timestamp(),
                         "ts_end": min(now, (day + timedelta(hours=21)).timestamp()), "rows": rows_n, "cols": cols_n,
                         "cell_m": CELL, "grid": _pack(day_heat)})
    return {"global_tracks": tracks, "store_door_events": doors, "occupancy_samples": occ, "area_visits": visits,
            "area_transitions": trans, "plan_heatmap_snapshots": heat}


def create(engine) -> None:
    rnd = random.Random(7)
    now = time.time()
    keys = {}
    with engine.begin() as conn:
        if conn.execute(select(organizations.c.id).where(organizations.c.name == "Demo")).first():
            print("La empresa Demo ya existe.")
            return
        oid = conn.execute(insert(organizations).values(name="Demo", timezone=TZ)).inserted_primary_key[0]
        plan = json.dumps(floorplan())
        for name, scale in SITES:
            key = new_site_key()
            sid = conn.execute(insert(sites).values(org_id=oid, name=name, status="active", activated_at=now,
                                                    key_hash=sha256(key), key_hint=key[-4:], floorplan_json=plan)
                               ).inserted_primary_key[0]
            keys[str(sid)] = {"name": name, "key": key, "scale": scale}
            rows = _site_rows(scale, 30, rnd, now)
            db_uid = str(uuid.uuid4())
            for i in range(0, max(len(r) for r in rows.values()), 4000):
                ingest(conn, sid, {"db_uid": db_uid, "tables": {t: r[i:i + 4000] for t, r in rows.items()}})
            last = now - 3 * 3600 if name == "Sede El Hatillo" else now   # una sede sin conexión, para verlo
            conn.execute(update(sites).where(sites.c.id == sid).values(last_sync_at=last))
        conn.execute(insert(sites).values(org_id=oid, name="Sede Los Palos Grandes", status="pending"))
        conn.execute(insert(users).values(email="demo@traffiqui.com", name="Gerencia Demo", role="hq", org_id=oid,
                                          password_hash=hash_password("demo1234")))
    KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)
    KEYS_FILE.write_text(json.dumps(keys, indent=2), encoding="utf-8")
    print("Empresa Demo creada. Entra con demo@traffiqui.com / demo1234")


def simulate(url: str = "http://localhost:9000", skip=("Sede El Hatillo",)) -> None:
    """Envía estados en vivo inventados para las sedes de la demo (la de `skip` queda sin conexión)."""
    keys = json.loads(KEYS_FILE.read_text(encoding="utf-8"))
    rnd = random.Random()
    walkers = {sid: [] for sid in keys}
    seen = {sid: 0 for sid in keys}
    print("Simulando tiendas en vivo (Ctrl+C para parar)…")
    while True:
        for sid, k in keys.items():
            if k["name"] in skip:
                continue
            ws = walkers[sid]
            target = max(1, round(10 * k["scale"] * (0.6 + 0.4 * math.sin(time.time() / 90))))
            while len(ws) < target:
                seen[sid] += 1
                ws.append({"gid": seen[sid], "x": 7.5, "y": 9.5, "tx": rnd.uniform(1, 14), "ty": rnd.uniform(1.5, 7)})
            if len(ws) > target:
                ws.pop(0)
            for p in ws:
                p["x"] += (p["tx"] - p["x"]) * 0.3 + rnd.uniform(-0.2, 0.2)
                p["y"] += (p["ty"] - p["y"]) * 0.3 + rnd.uniform(-0.2, 0.2)
                if abs(p["tx"] - p["x"]) < 0.3 and rnd.random() < 0.3:
                    p["tx"], p["ty"] = rnd.uniform(1, 14), rnd.uniform(1.5, 7)
            inside = lambda x0, x1, y0, y1: sum(1 for p in ws if x0 <= p["x"] <= x1 and y0 <= p["y"] <= y1)  # noqa: E731
            areas = [{"id": n, "name": n, "kind": kd, "inside": inside(x - 0.6, x + 1.0, 1.5, 6.5)} for n, kd, x in AREAS]
            areas += [{"id": n, "name": n, "kind": "caja", "inside": inside(x - 0.6, x + 0.5, y - 0.8, y + 0.8)} for n, x, y in CAJAS]
            alerts = []
            if k["name"] == "Sede Chacao":
                alerts.append({"kind": "camara", "ref": "cam2", "title": "Cámara «Pasillo 2»: se movió",
                               "message": "La imagen ya no coincide con su posición.", "since": time.time() - 600})
            body = {"db_uid": "demo-" + sid.zfill(8), "ts": time.time(), "people_now": len(ws),
                    "unique_today": 150 + seen[sid], "checkout_today": 60 + seen[sid] // 3, "entries": 150 + seen[sid],
                    "exits": 140 + seen[sid], "peak": 14, "peak_at": time.time() - 7200, "dwell": {"avg": 212},
                    "staff_now": 2, "areas": areas,
                    "people": [{"gid": p["gid"], "x": round(p["x"], 2), "y": round(p["y"], 2),
                                "color": f"hsl({(p['gid'] * 137) % 360} 75% 50%)", "staff": False, "buyer": False} for p in ws],
                    "cameras": [{"id": "cam1", "name": "Entrada", "enabled": True, "connected": True, "fps": 9.6,
                                 "health": {"state": "ok", "message": "Funcionando", "since": 0}},
                                {"id": "cam2", "name": "Pasillo 2", "enabled": True, "connected": True, "fps": 9.1,
                                 "health": {"state": "movida" if k["name"] == "Sede Chacao" else "ok", "message": "", "since": 0}}],
                    "alerts": alerts}
            req = urllib.request.Request(f"{url}/api/agent/live", data=json.dumps(body).encode(), method="POST",
                                         headers={"Content-Type": "application/json", "Authorization": f"Bearer {k['key']}"})
            try:
                urllib.request.urlopen(req, timeout=5).read()
            except OSError as e:
                print(f"{k['name']}: {e}")
        time.sleep(3)


def main() -> int:
    ap = argparse.ArgumentParser(prog="python -m cloud.demo")
    ap.add_argument("--simular", action="store_true", help="enviar estados en vivo a la sede principal local")
    ap.add_argument("--url", default="http://localhost:9000")
    ap.add_argument("--licencia", help='código de licencia emitido para la empresa "Demo"')
    a = ap.parse_args()
    engine = make_engine()
    create(engine)
    if a.licencia:
        with engine.begin() as conn:
            conn.execute(update(organizations).where(organizations.c.name == "Demo").values(license_code=a.licencia.strip()))
    if a.simular:
        try:
            simulate(a.url)
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
