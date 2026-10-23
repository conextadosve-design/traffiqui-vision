"""Alertas de la tienda: esperan a que la condición dure y se cierran solas."""
from app.alerts import HOLD_S, AlertTracker

CAJA = [{"id": "c1", "name": "Caja 1", "kind": "caja", "inside": 6}]
CAMS_OK = [{"id": "cam1", "name": "Entrada", "enabled": True, "connected": True, "health": {"state": "ok"}}]


def test_aforo_y_fila_esperan_y_se_cierran():
    t = AlertTracker()
    cfg = {"alert_capacity": 20, "alert_queue_people": 5}
    assert t.update(cfg, 25, CAJA, CAMS_OK, 100.0) == []                     # recién empieza
    out = t.update(cfg, 25, CAJA, CAMS_OK, 100.0 + HOLD_S["aforo"])
    assert [a["kind"] for a in out] == ["aforo"]
    out = t.update(cfg, 25, CAJA, CAMS_OK, 100.0 + HOLD_S["fila"])
    assert {a["kind"] for a in out} == {"aforo", "fila"} and "Caja 1" in out[1]["title"]
    assert t.update(cfg, 10, [], CAMS_OK, 200.0) == []
    # desactivadas con 0
    assert t.update({"alert_capacity": 0, "alert_queue_people": 0}, 999, CAJA, CAMS_OK, 999.0) == []


def test_camaras():
    t = AlertTracker()
    cams = [{"id": "cam1", "name": "Entrada", "enabled": True, "connected": False, "error": "Sin señal"},
            {"id": "cam2", "name": "Pasillo", "enabled": True, "connected": True, "health": {"state": "movida", "message": "x"}},
            {"id": "cam3", "name": "Apagada", "enabled": False, "connected": False}]
    out = t.update({}, 0, [], cams, 1.0)
    assert {(a["kind"], a["ref"]) for a in out} == {("camara", "cam1"), ("camara", "cam2")}
