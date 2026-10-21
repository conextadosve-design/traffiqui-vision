"""Multisede: servidor central, agente de sincronización y reporte consolidado (sin red real)."""
import time

import numpy as np
import pytest

pytest.importorskip("sqlalchemy", reason="servidor central: pip install -r cloud/requirements.txt")
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import cloud_sync
from app.cloud_sync import CloudError, CloudSync
from app.storage.db import Database
from cloud import admin, config
from cloud.db import global_tracks, make_engine, occupancy_samples, plan_heatmaps, sites
from cloud.main import create_app
from cloud.reports import resolve_range
from cloud.security import hash_password, verify_password

URL = "http://testserver"


@pytest.fixture
def engine(tmp_path):
    return make_engine(f"sqlite:///{tmp_path / 'cloud.db'}")


@pytest.fixture
def client(engine, monkeypatch):
    monkeypatch.setattr(config, "COOKIE_SECURE", False)
    return TestClient(create_app(engine))


def run_admin(engine, capsys, *args) -> str:
    assert admin.main(list(args), engine=engine) == 0
    return capsys.readouterr().out


@pytest.fixture
def org(engine, capsys):
    """Empresa 1 con dos sedes activas, una pendiente y usuarios de cada rol; empresa 2 aparte."""
    run_admin(engine, capsys, "crear-empresa", "Farmacias Sol")
    run_admin(engine, capsys, "crear-sede", "1", "Chacao")
    run_admin(engine, capsys, "crear-sede", "1", "Altamira")
    run_admin(engine, capsys, "crear-sede", "1", "Las Mercedes")       # queda pendiente de pago
    keys = {}
    for sid in (1, 2):
        out = run_admin(engine, capsys, "activar-sede", str(sid), "--pago", "Pago móvil")
        keys[sid] = out.strip().splitlines()[-1]
        assert keys[sid].startswith("tqs_")
    run_admin(engine, capsys, "crear-usuario", "ana@sol.com", "Ana", "hq", "--empresa", "1", "--clave", "gerencia123")
    run_admin(engine, capsys, "crear-usuario", "luis@sol.com", "Luis", "site", "--empresa", "1", "--sede", "2",
              "--clave", "encargado1")
    run_admin(engine, capsys, "crear-empresa", "Otra empresa")
    run_admin(engine, capsys, "crear-sede", "2", "Ajena")
    run_admin(engine, capsys, "activar-sede", "4")
    return keys


def poster(client):
    def post(url, key, path, payload):
        r = client.post(path, json=payload, headers={"Authorization": f"Bearer {key}"})
        if r.status_code >= 400:
            raise CloudError(r.json()["detail"], blocked=r.status_code in (401, 403))
        return r.json()
    return post


@pytest.fixture
def local_db(tmp_path):
    d = Database(tmp_path / "tienda.db")
    d.start_session(0, {})
    yield d
    d.close()


def add_person(db, gid, first_seen, duration=60.0, buyer=False, staff=False):
    db.on_event("global_start", {"global_id": gid, "first_seen": first_seen})
    db.on_event("global_end", {"global_id": gid, "last_seen": first_seen + duration, "duration": duration,
                               "cameras": ["cam1"], "areas": ["p1"], "buyer": buyer, "staff": staff,
                               "checkout_seconds": 25 if buyer else 0})


# ---- seguridad -------------------------------------------------------------------------------
def test_contrasena_con_scrypt():
    h = hash_password("secreta123")
    assert h.startswith("scrypt$") and "secreta123" not in h
    assert verify_password("secreta123", h)
    assert not verify_password("otra", h)
    assert not verify_password("x", "formato-raro")


def test_login_y_permisos(client, org):
    assert client.get("/api/report").status_code == 401
    assert client.post("/api/auth/login", json={"email": "ana@sol.com", "password": "mal"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "ANA@sol.com ", "password": "gerencia123"}).status_code == 200
    me = client.get("/api/me").json()
    assert me["role"] == "hq" and me["org_name"] == "Farmacias Sol"
    # la sede principal ve las 3 sedes de su empresa (no la de la otra empresa), aunque pida otra empresa
    rep = client.get("/api/report", params={"org_id": 2}).json()
    assert {s["name"] for s in rep["sites"]} == {"Chacao", "Altamira", "Las Mercedes"}
    client.post("/api/auth/logout")
    assert client.get("/api/report").status_code == 401
    # el encargado de sede solo ve la suya
    client.post("/api/auth/login", json={"email": "luis@sol.com", "password": "encargado1"})
    assert [s["name"] for s in client.get("/api/report").json()["sites"]] == ["Altamira"]


# ---- agente --------------------------------------------------------------------------------------
def test_clave_invalida_o_sede_pendiente(client, org, engine, capsys):
    post = poster(client)
    with pytest.raises(CloudError) as e:
        post(URL, "tqs_inventada", "/api/agent/hello", {})
    assert e.value.blocked and "no válida" in str(e.value)
    run_admin(engine, capsys, "suspender-sede", "1")
    with pytest.raises(CloudError) as e:
        post(URL, org[1], "/api/agent/hello", {})
    assert e.value.blocked and "suspendida" in str(e.value)
    assert post(URL, org[2], "/api/agent/hello", {})["site"] == "Altamira"


def test_sincronizacion_completa_sin_duplicados(client, org, engine, local_db, monkeypatch):
    monkeypatch.setattr(cloud_sync, "SETTLE_S", 0)
    now = time.time()
    add_person(local_db, 1, now - 300, buyer=True)
    add_person(local_db, 2, now - 200)
    add_person(local_db, 3, now - 100, staff=True)
    local_db.add_occupancy(now - 50, 2, 3, 2.5)
    local_db.add_plan_heatmap(now - 300, now, np.ones((4, 5), np.float32), 0.25)
    local_db.flush()

    plan = {"width_m": 10, "depth_m": 8, "elements": []}
    agent = CloudSync(local_db, floorplan=lambda: plan, post=poster(client))
    assert agent.status()["configured"] is False
    with pytest.raises(CloudError):
        agent.connect(URL, "sin-prefijo")
    st = agent.connect(URL, org[1])
    assert st["site"] == "Chacao" and st["org"] == "Farmacias Sol" and st["key_hint"] == f"…{org[1][-4:]}"

    assert agent.sync_once() == 5
    assert agent.state["state"] == "ok"
    # volver a sincronizar no reenvía nada y no duplica
    assert agent.sync_once() == 0
    with engine.connect() as c:
        assert c.execute(select(func.count()).select_from(global_tracks)).scalar_one() == 3
        assert c.execute(select(func.count()).select_from(occupancy_samples)).scalar_one() == 1
        grid = c.execute(select(plan_heatmaps.c.grid)).scalar_one()
        site = c.execute(select(sites).where(sites.c.id == 1)).mappings().one()
    assert len(grid) > 0 and site["floorplan_json"] and site["agent_version"] == cloud_sync.AGENT_VERSION

    # una persona que cambia después (pasa por caja) se actualiza en el servidor, sin fila nueva
    time.sleep(0.01)
    local_db.on_event("global_buyer", {"global_id": 2, "checkout_seconds": 30})
    local_db.flush()
    assert agent.sync_once() == 1
    with engine.connect() as c:
        assert c.execute(select(func.count()).select_from(global_tracks)).scalar_one() == 3
        assert c.execute(select(global_tracks.c.is_buyer).where(global_tracks.c.global_id == 2)).scalar_one() == 1

    # si se borra el cursor (p. ej. al reconectar), reenviar todo tampoco duplica
    with local_db.connect() as c:
        c.execute("UPDATE cloud_link SET cursors = '{}'")
    agent.sync_once()
    with engine.connect() as c:
        assert c.execute(select(func.count()).select_from(global_tracks)).scalar_one() == 3


def test_sin_conexion_no_pierde_datos(client, org, engine, local_db, monkeypatch):
    monkeypatch.setattr(cloud_sync, "SETTLE_S", 0)
    online = {"up": True}
    real = poster(client)

    def flaky(*a):
        if not online["up"]:
            raise CloudError("No se pudo conectar con el servidor central. Se reintentará solo.")
        return real(*a)

    agent = CloudSync(local_db, post=flaky)
    agent.connect(URL, org[1])
    online["up"] = False
    add_person(local_db, 1, time.time() - 60)
    local_db.flush()
    assert agent.sync_once() == 0
    assert agent.status()["state"] == "error" and "reintentará" in agent.status()["message"]
    online["up"] = True
    assert agent.sync_once() == 1
    assert agent.status()["state"] == "ok"


def test_rechaza_tablas_desconocidas(client, org):
    r = client.post("/api/agent/sync", json={"db_uid": "12345678-abcd", "tables": {"reference_frame": []}},
                    headers={"Authorization": f"Bearer {org[1]}"})
    assert r.status_code == 400 and "desconocidas" in r.json()["detail"]


# ---- reporte consolidado -----------------------------------------------------------------------
def test_reporte_consolidado(client, org, engine, tmp_path, monkeypatch):
    monkeypatch.setattr(cloud_sync, "SETTLE_S", 0)
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    yesterday = (datetime.now(ZoneInfo("America/Caracas")) - timedelta(days=1)).strftime("%Y-%m-%d")
    t0, _ = resolve_range("custom", "America/Caracas", yesterday, yesterday)
    base = t0 + 10 * 3600  # ayer a las 10:00, hora de Caracas
    for sid, people in ((1, [(0, True), (60, False), (120, True), (130, False)]), (2, [(3600, False)])):
        db = Database(tmp_path / f"sede{sid}.db")
        db.start_session(0, {})
        for i, (dt, buyer) in enumerate(people):
            add_person(db, i + 1, base + dt, duration=100 + 20 * i, buyer=buyer)
        add_person(db, 99, base, staff=True)    # el personal no cuenta
        db.flush()
        agent = CloudSync(db, post=poster(client))
        agent.connect(URL, org[sid])
        agent.sync_once()
        db.close()

    client.post("/api/auth/login", json={"email": "ana@sol.com", "password": "gerencia123"})
    rep = client.get("/api/report", params={"range": "custom", "start": yesterday, "end": yesterday}).json()
    t = rep["totals"]
    assert t["visits"] == 5 and t["checkout"] == 2 and t["checkout_rate"] == 0.4
    assert t["peak_hour"] == 10 and t["sites_active"] == 2 and t["sites_online"] == 2 and t["sites_pending"] == 1
    chacao, altamira, pendiente = rep["sites"]
    assert (chacao["name"], chacao["visits"], chacao["checkout"]) == ("Chacao", 4, 2)
    assert chacao["avg_dwell"] == 130.0 and chacao["peak_hour"] == 10
    assert (altamira["name"], altamira["peak_hour"]) == ("Altamira", 11)
    assert pendiente["status"] == "pending" and pendiente["visits"] == 0
    assert rep["range"]["unit"] == "hour" and sum(chacao["series"]) == 4


def test_rangos():
    t0, t1 = resolve_range("custom", "America/Caracas", "2026-10-01", "2026-10-07", now=2e9)
    assert t1 - t0 == 7 * 86400
    with pytest.raises(ValueError):
        resolve_range("custom", "America/Caracas", "2026-10-07", "2026-10-01")
    with pytest.raises(ValueError):
        resolve_range("custom", "America/Caracas", "07/10/2026", "2026-10-08")
    w0, w1 = resolve_range("week", "America/Caracas", now=2e9)
    assert 6 * 86400 < w1 - w0 <= 7 * 86400
