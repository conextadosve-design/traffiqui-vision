"""Fase 2: tiempo real, alertas con historial, sede sin datos, informe por sede y comparativas."""
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pytest

pytest.importorskip("sqlalchemy")
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import update  # noqa: E402

from app import cloud_sync  # noqa: E402
from app.cloud_sync import CloudError, CloudSync  # noqa: E402
from app.storage.db import Database  # noqa: E402
from cloud import config, licencia  # noqa: E402
from cloud.db import make_engine, sites  # noqa: E402
from cloud.main import create_app  # noqa: E402
from cloud.reports import comparison_ranges, pct  # noqa: E402

TZ = "America/Caracas"
PLAN = {"width": 10, "depth": 8, "elements": [
    {"id": "a1", "type": "area", "name": "Pasillo 1", "kind": "pasillo", "points": [[1, 1], [4, 1], [4, 7], [1, 7]]},
    {"id": "a2", "type": "area", "name": "Caja 1", "kind": "caja", "points": [[6, 1], [9, 1], [9, 3], [6, 3]]}],
    "background": "data:image/png;base64,AAAA"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    priv = Ed25519PrivateKey.generate()
    monkeypatch.setattr(licencia, "public_key", lambda *a: priv.public_key())
    monkeypatch.setattr(config, "COOKIE_SECURE", False)
    monkeypatch.setattr(cloud_sync, "SETTLE_S", 0)
    engine = make_engine(f"sqlite:///{tmp_path / 'hq.db'}")
    c = TestClient(create_app(engine))
    c.post("/api/setup", json={"empresa": "Sol", "nombre": "Ana", "email": "ana@sol.com", "password": "gerencia123"})
    raw = priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    c.post("/api/manage/license", json={"code": licencia.issue("Sol", 3, licencia._b64e(raw))})
    site = c.post("/api/manage/sites", json={"name": "Chacao"}).json()

    def post(url, key, path, payload):
        r = c.post(path, json=payload, headers={"Authorization": f"Bearer {key}"})
        if r.status_code >= 400:
            raise CloudError(r.json()["detail"], blocked=r.status_code in (401, 403))
        return r.json()
    return c, engine, site, post, tmp_path


def live_state(alerts=(), people_now=3):
    return {"ts": time.time(), "people_now": people_now, "unique_today": 40, "checkout_today": 12, "entries": 41,
            "exits": 38, "peak": 9, "peak_at": time.time(), "dwell": {"avg": 95}, "staff_now": 1,
            "areas": [{"id": "a1", "name": "Pasillo 1", "kind": "pasillo", "inside": 2},
                      {"id": "a2", "name": "Caja 1", "kind": "caja", "inside": 1}],
            "people": [{"gid": 7, "x": 2.0, "y": 3.0, "color": "#ff0000", "staff": False, "buyer": False}],
            "cameras": [{"id": "cam1", "name": "Entrada", "enabled": True, "connected": True, "fps": 9.5,
                         "health": {"state": "ok", "message": "Funcionando", "since": 1}}],
            "alerts": list(alerts)}


def test_estado_en_vivo_y_plano_sin_fondo(env, tmp_path):
    c, engine, site, post, _ = env
    db = Database(tmp_path / "t.db")
    db.start_session(0, {})
    agent = CloudSync(db, floorplan=lambda: PLAN, post=post, live=live_state)
    agent.connect("http://x", site["key"])
    agent.sync_once()
    assert agent.push_live()
    d = c.get(f"/api/sites/{site['id']}/live").json()
    assert d["live"]["people_now"] == 3 and d["live"]["people"][0]["gid"] == 7
    assert d["floorplan"]["width"] == 10 and "background" not in d["floorplan"]   # el croquis de fondo no viaja
    db.close()


def test_alertas_se_abren_cierran_y_guardan_historial(env):
    c, engine, site, post, _ = env
    aforo = {"kind": "aforo", "ref": "", "title": "Aforo superado: 31 personas", "message": "", "since": time.time() - 40}
    post("http://x", site["key"], "/api/agent/live", {"db_uid": "x" * 12, **live_state([aforo])})
    open_ = c.get("/api/alerts").json()["alerts"]
    assert [a["kind"] for a in open_] == ["aforo"] and open_[0]["site"] == "Chacao"
    # se repite: no se duplica
    post("http://x", site["key"], "/api/agent/live", {"db_uid": "x" * 12, **live_state([aforo])})
    assert len(c.get("/api/alerts").json()["alerts"]) == 1
    assert c.post(f"/api/alerts/{open_[0]['id']}/ack").status_code == 200
    assert c.get("/api/alerts").json()["alerts"][0]["ack_by"] == "Ana"
    # deja de llegar: se cierra y queda en el historial
    post("http://x", site["key"], "/api/agent/live", {"db_uid": "x" * 12, **live_state([])})
    assert c.get("/api/alerts").json()["alerts"] == []
    hist = c.get("/api/alerts", params={"state": "all"}).json()["alerts"]
    assert hist[0]["ended_at"] is not None


def test_sede_sin_enviar_datos(env):
    c, engine, site, post, _ = env
    post("http://x", site["key"], "/api/agent/live", {"db_uid": "x" * 12, **live_state()})
    assert c.get("/api/alerts").json()["alerts"] == []
    assert c.put("/api/manage/alerts-config", json={"offline_min": 1}).status_code == 400
    c.put("/api/manage/alerts-config", json={"offline_min": 5})
    with engine.begin() as conn:
        conn.execute(update(sites).where(sites.c.id == site["id"]).values(last_sync_at=time.time() - 6 * 60))
    a = c.get("/api/alerts").json()["alerts"]
    assert a[0]["kind"] == "sin_datos" and "5 min" in a[0]["message"]
    post("http://x", site["key"], "/api/agent/live", {"db_uid": "x" * 12, **live_state()})
    assert c.get("/api/alerts").json()["alerts"] == []


def add_person(db, gid, first_seen, buyer=False, checkout="Caja 1", areas=()):
    db.on_event("global_start", {"global_id": gid, "first_seen": first_seen})
    for i, (name, dur) in enumerate(areas):
        db.on_event("area_visit", {"global_id": gid, "area_id": name, "area": name, "enter": first_seen + i,
                                   "exit": first_seen + i + dur, "duration": dur})
    if len(areas) > 1:
        db.on_event("area_transition", {"global_id": gid, "from_id": areas[0][0], "from": areas[0][0],
                                        "to_id": areas[1][0], "to": areas[1][0], "ts": first_seen + 5})
    db.on_event("global_end", {"global_id": gid, "last_seen": first_seen + 120, "duration": 120, "cameras": ["cam1"],
                               "areas": [a for a, _ in areas], "buyer": buyer, "checkout_seconds": 30 if buyer else 0,
                               "checkout_area": checkout if buyer else None})


def test_informe_de_una_sede_con_comparativas(env, tmp_path):
    c, engine, site, post, _ = env
    zone = ZoneInfo(TZ)
    yday = (datetime.now(zone) - timedelta(days=1)).replace(hour=11, minute=0, second=0, microsecond=0)
    db = Database(tmp_path / "t2.db")
    db.start_session(0, {})
    for i in range(4):   # ayer: 4 visitas, 2 pasan por caja
        add_person(db, i + 1, yday.timestamp() + i * 60, buyer=i < 2,
                   areas=[("Pasillo 1", 20), ("Caja 1", 30)] if i < 2 else [("Pasillo 1", 5)])
    for i in range(2):   # el mismo día de la semana anterior: 2 visitas
        add_person(db, 100 + i, (yday - timedelta(days=7)).timestamp() + i * 60)
    db.on_event("door_event", {"global_id": 1, "door_id": "d1", "door": "Entrada", "direction": "in", "ts": yday.timestamp()})
    db.add_plan_heatmap(yday.timestamp(), yday.timestamp() + 300, np.ones((32, 40), np.float32), 0.25)
    db.flush()
    agent = CloudSync(db, floorplan=lambda: PLAN, post=post)
    agent.connect("http://x", site["key"])
    agent.sync_once()
    day = yday.strftime("%Y-%m-%d")
    r = c.get(f"/api/sites/{site['id']}/report", params={"range": "custom", "start": day, "end": day}).json()
    assert r["summary"]["visits"] == 4 and r["summary"]["checkout"] == 2 and r["summary"]["peak_hour"] == 11
    assert r["compare"]["week"]["visits"] == 100.0 and r["compare"]["week"]["prev_visits"] == 2
    areas = {a["name"]: a for a in r["areas"]}
    assert areas["Pasillo 1"]["people"] == 4 and areas["Pasillo 1"]["stopped"] == 2
    assert r["transitions"][0] == {"from": "Pasillo 1", "to": "Caja 1", "count": 2}
    assert r["checkouts"][0]["name"] == "Caja 1" and r["checkouts"][0]["people"] == 2
    assert r["doors"] == [{"name": "Entrada", "in": 1, "out": 0}]
    assert r["heatmap"]["rows"] == 32 and max(r["heatmap"]["values"]) == 1.0
    # el resumen de todas las sedes trae las mismas comparativas
    org = c.get("/api/report", params={"range": "custom", "start": day, "end": day}).json()
    assert org["compare"]["week"]["visits"] == 100.0 and org["sites"][0]["compare"]["week"]["visits"] == 100.0
    assert c.get("/api/sites/999/report").status_code == 404
    db.close()


def test_rangos_de_comparacion():
    zone = ZoneInfo(TZ)
    t0 = datetime(2026, 3, 31, 0, 0, tzinfo=zone).timestamp()
    t1 = datetime(2026, 3, 31, 15, 0, tzinfo=zone).timestamp()
    r = comparison_ranges(t0, t1, TZ)
    assert datetime.fromtimestamp(r["week"][0], zone).date().isoformat() == "2026-03-24"
    assert datetime.fromtimestamp(r["month"][1], zone).isoformat().startswith("2026-02-28T15:00")
    assert pct(12, 10) == 20.0 and pct(5, 0) is None
