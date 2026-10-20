import time

import numpy as np
import pytest

from app.storage import analytics
from app.storage.db import Database, pack_grid, unpack_grid


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "t.db")
    d.start_session(0, {"imgsz": 480})
    yield d
    d.close()


def test_config_sobrevive_reinicio(tmp_path):
    path = tmp_path / "c.db"
    d = Database(path)
    d.save_config({"line": {"a": [0.1, 0.2], "b": [0.3, 0.4], "inverted": True}, "zones": [{"id": "z", "name": "Caja"}]})
    d.close()
    again = Database(path).load_config()
    assert again["line"]["inverted"] is True
    assert again["zones"][0]["name"] == "Caja"


def test_grilla_comprimida_ida_y_vuelta():
    g = np.random.rand(48, 64).astype(np.float32)
    assert np.allclose(unpack_grid(pack_grid(g)), g)


def test_eventos_en_lote_y_analitica(db):
    t0 = analytics.local_midnight(time.time()) + 3600 * 10  # 10:00 de hoy
    for tid, dur in ((1, 5.0), (2, 20.0), (3, 200.0)):
        db.on_event("track_start", {"track_id": tid, "first_seen": t0 + tid, "color": "#fff"})
        db.on_event("track_end", {"track_id": tid, "first_seen": t0 + tid, "last_seen": t0 + tid + dur,
                                  "duration": dur, "zones": ["Caja"]})
    db.on_event("line_event", {"track_id": 1, "direction": "in", "ts": t0 + 10})
    db.on_event("line_event", {"track_id": 2, "direction": "in", "ts": t0 + 20})
    db.on_event("line_event", {"track_id": 3, "direction": "out", "ts": t0 + 4000})
    db.on_event("zone_visit", {"track_id": 1, "zone_id": "z1", "zone": "Caja", "enter": t0, "exit": t0 + 3, "duration": 3})
    db.on_event("zone_visit", {"track_id": 2, "zone_id": "z1", "zone": "Caja", "enter": t0, "exit": t0 + 15, "duration": 15})
    db.add_occupancy(t0 + 5, 2, 3, 1.5)
    db.add_occupancy(t0 + 10, 1, 2, 1.0)
    db.add_heatmap(t0, t0 + 300, np.ones((48, 64), np.float32))
    assert db.flush()

    data = analytics.query(db, t0 - 60, t0 + 7200, bucket_minutes=15, stop_seconds=10)
    assert data["totals"] == {"unique": 3, "entries": 2, "exits": 1, "peak": 3, "peak_at": t0 + 5}
    assert data["dwell"]["buckets"]["<10 s"] == 1 and data["dwell"]["buckets"][">3 min"] == 1
    assert data["zones"] == [{"id": "z1", "name": "Caja", "passed": 2, "stopped": 1, "stop_rate": 0.5, "avg_dwell": 9.0}]
    assert sum(u["count"] for u in data["unique"]) == 3
    by_hour = {r["t"]: (r["in"], r["out"]) for r in data["line_by_hour"]}
    assert by_hour[t0] == (2, 0) and by_hour[t0 + 3600] == (0, 1)
    assert db.count_tracks_since(analytics.local_midnight(t0)) == 3

    grid = analytics.heatmap_grid(db, t0 - 60, t0 + 7200, (48, 64))
    assert grid.sum() == 48 * 64
    assert analytics.heatmap_png(db, grid, (640, 480))[:4] == b"\x89PNG"
    csv_text = analytics.to_csv(data)
    assert "Caja;2;1;0,5;9,0" in csv_text


def test_rango_personalizado_invalido():
    with pytest.raises(analytics.RangeError):
        analytics.resolve_range("custom", "2026-10-18T10:00", "2026-10-18T09:00")
    with pytest.raises(analytics.RangeError):
        analytics.resolve_range("custom", "mañana", "2026-10-18T09:00")


def test_buckets_alineados_al_reloj():
    t = analytics.local_midnight(time.time()) + 3600 * 9 + 60 * 37  # 09:37
    assert analytics.bucket_start(t, 900) == t - 60 * 7               # 09:30
    assert analytics.bucket_start(t, 3600) == t - 60 * 37             # 09:00


# ---- semana / mes y tráfico por hora de cada día --------------------------------------------------
def test_rangos_semana_y_mes_empiezan_a_medianoche():
    now = analytics.local_midnight(time.time()) + 15 * 3600
    t0, t1 = analytics.resolve_range("week", None, None, now)
    assert t1 == now and t0 == analytics.local_midnight(now - 6 * 86400)
    t0, _ = analytics.resolve_range("month", None, None, now)
    assert t0 == analytics.local_midnight(now - 29 * 86400)


def test_trafico_por_hora_de_cada_dia(tmp_path):
    from app.storage.store_analytics import hourly_query
    db = Database(tmp_path / "h.db")
    db.start_session(0, {})
    day0 = analytics.local_midnight(time.time()) - 2 * 86400          # anteayer 00:00
    gid = 0
    # anteayer: 3 personas a las 10 h y 1 a las 18 h; ayer: 2 a las 10 h; el personal no cuenta
    for d, h, n, buyer in ((0, 10, 3, True), (0, 18, 1, False), (1, 10, 2, False)):
        for _ in range(n):
            gid += 1
            ts = day0 + d * 86400 + h * 3600 + gid
            db.on_event("global_start", {"global_id": gid, "first_seen": ts})
            db.on_event("global_end", {"global_id": gid, "first_seen": ts, "last_seen": ts + 60, "duration": 60, "cameras": [],
                                       "areas": ["Pasillo 1"], "buyer": buyer, "stopped": False, "staff": False})
            db.on_event("area_visit", {"global_id": gid, "area_id": "p1", "area": "Pasillo 1", "enter": ts + 5, "exit": ts + 20, "duration": 15})
            db.on_event("area_visit", {"global_id": gid, "area_id": "p1", "area": "Pasillo 1", "enter": ts + 30, "exit": ts + 40, "duration": 10})
    db.on_event("global_start", {"global_id": 99, "first_seen": day0 + 10 * 3600})
    db.on_event("global_end", {"global_id": 99, "first_seen": day0 + 10 * 3600, "last_seen": day0 + 15 * 3600, "duration": 18000,
                               "cameras": [], "areas": [], "buyer": False, "stopped": False, "staff": True})
    assert db.flush()
    areas = [{"id": "p1", "name": "Pasillo 1", "kind": "pasillo"}]
    t1 = day0 + 3 * 86400 - 1
    r = hourly_query(db, day0, t1, areas, "store")
    assert r["n_days"] == 3 and r["days"][0]["counts"][10] == 3 and r["days"][0]["counts"][18] == 1
    assert r["days"][1]["counts"][10] == 2 and r["selected"]["peak_hour"] == 10 and r["selected"]["by_hour"][10] == 5
    assert r["selected"]["avg_by_hour"][10] == round(5 / 3, 2)
    a = hourly_query(db, day0, t1, areas, "p1")
    assert a["days"][0]["counts"][10] == 3          # volver al pasillo en la misma hora no suma de nuevo
    assert a["areas"][0]["peak_hour"] == 10 and a["areas"][0]["top_hours"] == [10, 18]
    b = hourly_query(db, day0, t1, areas, "p1", "buyers")
    assert b["selected"]["total"] == 3
    wd = analytics.datetime.fromtimestamp(day0).weekday()
    assert r["selected"]["weekday_avg"][wd][10] == 3
    db.close()
