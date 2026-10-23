"""Empresa de demostración con 4 sedes y 30 días de datos inventados, para mostrar el panel.

    python -m cloud.demo            → usuario demo@traffiqui.com / demo1234

Los datos son simulados (curva de horas típica de una tienda de barrio con ruido); nunca se
mezclan con una empresa real porque se crean en una empresa propia llamada "Demo".
"""
from __future__ import annotations

import math
import random
import sys
import time
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import insert, select, update

from cloud.db import make_engine, organizations, sites, users
from cloud.ingest import ingest
from cloud.security import hash_password

SITES = [("Sede Chacao", 1.0), ("Sede Altamira", 0.75), ("Sede Las Mercedes", 0.55), ("Sede El Hatillo", 0.35)]
TZ = "America/Caracas"


def _hour_weight(h: int, weekend: bool) -> float:
    if not 8 <= h <= 20:
        return 0.0
    w = math.exp(-((h - 11.5) / 2.2) ** 2) + 0.8 * math.exp(-((h - 17.5) / 1.8) ** 2)
    return w * (1.3 if weekend else 1.0)


def _site_rows(scale: float, days: int, rnd: random.Random, now: float) -> dict:
    zone = ZoneInfo(TZ)
    today = datetime.fromtimestamp(now, zone).replace(hour=0, minute=0, second=0, microsecond=0)
    tracks, doors, occ = [], [], []
    gid = 0
    for d in range(days - 1, -1, -1):
        day = today - timedelta(days=d)
        weekend = day.weekday() >= 5
        for h in range(24):
            if not _hour_weight(h, weekend):
                continue  # tienda cerrada
            n = rnd.gauss(28 * scale * _hour_weight(h, weekend), 2)
            for _ in range(max(0, round(n))):
                first = (day + timedelta(hours=h, seconds=rnd.uniform(0, 3600))).timestamp()
                dur = max(20.0, rnd.lognormvariate(5.2, 0.6))
                if first + dur > now:
                    continue
                gid += 1
                buyer = rnd.random() < 0.42
                tracks.append({"id": gid, "session_id": 1, "global_id": gid, "first_seen": first,
                               "last_seen": first + dur, "duration": dur, "is_buyer": int(buyer),
                               "checkout_seconds": rnd.uniform(25, 120) if buyer else 0, "is_staff": 0})
                doors.append({"id": len(doors) + 1, "session_id": 1, "global_id": gid, "door_id": "d1",
                              "door_name": "Entrada", "direction": "in", "ts": first})
            ts = (day + timedelta(hours=h, minutes=30)).timestamp()
            if ts < now:
                peak = max(0, round(n * 0.35 + rnd.uniform(0, 2)))
                occ.append({"id": len(occ) + 1, "session_id": 1, "ts": ts, "people": peak,
                            "people_max": peak + 1, "people_avg": peak * 0.8})
    return {"global_tracks": tracks, "store_door_events": doors, "occupancy_samples": occ}


def main() -> int:
    engine = make_engine()
    rnd = random.Random(7)
    now = time.time()
    with engine.begin() as conn:
        if conn.execute(select(organizations.c.id).where(organizations.c.name == "Demo")).first():
            print("La empresa Demo ya existe.")
            return 0
        oid = conn.execute(insert(organizations).values(name="Demo", timezone=TZ)).inserted_primary_key[0]
        for name, scale in SITES:
            sid = conn.execute(insert(sites).values(org_id=oid, name=name, status="active", activated_at=now)
                               ).inserted_primary_key[0]
            rows = _site_rows(scale, 30, rnd, now)
            db_uid = str(uuid.uuid4())
            for i in range(0, max(len(r) for r in rows.values()), 4000):
                ingest(conn, sid, {"db_uid": db_uid, "tables": {t: r[i:i + 4000] for t, r in rows.items()}})
            # una sede sin conexión hace 3 h, para ver cómo se muestra
            last = now - 3 * 3600 if name == "Sede El Hatillo" else now
            conn.execute(update(sites).where(sites.c.id == sid).values(last_sync_at=last))
        conn.execute(insert(sites).values(org_id=oid, name="Sede Los Palos Grandes", status="pending"))
        conn.execute(insert(users).values(email="demo@traffiqui.com", name="Gerencia Demo", role="hq", org_id=oid,
                                          password_hash=hash_password("demo1234")))
    print("Empresa Demo creada. Entra con demo@traffiqui.com / demo1234")
    return 0


if __name__ == "__main__":
    sys.exit(main())
