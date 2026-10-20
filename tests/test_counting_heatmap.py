import numpy as np
import pytest

from app.vision.counting import (LineCounter, ZoneStats, ZoneTracker, dwell_summary,
                                 point_in_polygon)
from app.vision.heatmap import Heatmap, cell_for, decay_factor, grid_shape, render


def walk(counter, tid, points):
    return [d for d in (counter.update(tid, p) for p in points) if d]


# ---- línea --------------------------------------------------------------------------
def test_cruce_en_ambas_direcciones():
    # línea horizontal y=100 de x=0 a x=200; normal positiva apunta hacia y creciente (abajo)
    lc = LineCounter((0, 100), (200, 100))
    assert walk(lc, 1, [(100, 50), (100, 90), (100, 110), (100, 150)]) == ["in"]
    assert walk(lc, 2, [(100, 150), (100, 110), (100, 90), (100, 50)]) == ["out"]


def test_invertir_direccion():
    lc = LineCounter((0, 100), (200, 100), inverted=True)
    assert walk(lc, 1, [(100, 50), (100, 150)]) == ["out"]


def test_quedarse_sobre_la_linea_no_suma():
    lc = LineCounter((0, 100), (200, 100), margin=6)
    assert walk(lc, 1, [(100, 50), (100, 98), (100, 103), (100, 97), (100, 104), (100, 50)]) == []


def test_cruce_fuera_del_segmento_no_cuenta():
    lc = LineCounter((0, 100), (200, 100))
    assert walk(lc, 1, [(400, 50), (400, 150)]) == []


def test_ida_y_vuelta():
    lc = LineCounter((0, 100), (200, 100))
    assert walk(lc, 1, [(50, 50), (50, 150), (60, 40)]) == ["in", "out"]


# ---- polígono -----------------------------------------------------------------------
SQUARE = [(0, 0), (100, 0), (100, 100), (0, 100)]


@pytest.mark.parametrize("p,expected", [((50, 50), True), ((150, 50), False), ((-1, 50), False),
                                        ((50, 101), False), ((99, 1), True)])
def test_punto_en_poligono(p, expected):
    assert point_in_polygon(p, SQUARE) is expected


def test_poligono_concavo():
    L = [(0, 0), (100, 0), (100, 40), (40, 40), (40, 100), (0, 100)]
    assert point_in_polygon((20, 80), L)
    assert not point_in_polygon((80, 80), L)


# ---- permanencia por zona -------------------------------------------------------------
def test_permanencia_por_zona():
    zt = ZoneTracker("z", SQUARE, grace=1.0)
    assert zt.update(1, (50, 50), 10.0) is None
    assert zt.update(1, (60, 50), 22.0) is None
    assert zt.inside_ids() == [1]
    assert zt.update(1, (200, 50), 22.5) is None       # afuera, todavía en gracia
    v = zt.update(1, (200, 50), 23.6)                  # gracia cumplida: visita cerrada
    assert v.enter == 10.0 and v.exit == 22.0 and v.duration == 12.0


def test_parpadeo_en_el_borde_no_corta_la_visita():
    zt = ZoneTracker("z", SQUARE, grace=1.0)
    zt.update(1, (50, 50), 0.0)
    zt.update(1, (101, 50), 5.0)
    zt.update(1, (99, 50), 5.4)                        # volvió dentro de la gracia
    v = zt.finish(1)
    assert v.enter == 0.0 and v.exit == 5.4


def test_estadisticas_de_zona():
    stats = ZoneStats()
    zt = ZoneTracker("z", SQUARE)
    for tid, dur in ((1, 4.0), (2, 15.0), (3, 30.0)):
        zt.update(tid, (50, 50), 0.0)
        zt.update(tid, (50, 50), dur)
        stats.add(zt.finish(tid))
    s = stats.summary(stop_seconds=10)
    assert s == {"passed": 3, "stopped": 2, "stop_rate": round(2 / 3, 3), "avg_dwell": round(49 / 3, 1)}


def test_distribucion_de_permanencia():
    s = dwell_summary([5, 12, 45, 90, 200, 8])
    assert s["buckets"] == {"<10 s": 2, "10–30 s": 1, "30–60 s": 1, "1–3 min": 1, ">3 min": 1}
    assert s["median"] == 28.5


# ---- mapa de calor ---------------------------------------------------------------------
def test_grilla_proporcional():
    assert grid_shape(64, 1280, 720) == (36, 64)
    assert grid_shape(64, 640, 480) == (48, 64)


def test_binning():
    assert cell_for(0, 0, 640, 480, 48, 64) == (0, 0)
    assert cell_for(639, 479, 640, 480, 48, 64) == (47, 63)
    assert cell_for(320, 240, 640, 480, 48, 64) == (24, 32)
    assert cell_for(9999, -5, 640, 480, 48, 64) == (0, 63)  # se recorta al borde


def test_decaimiento_vida_media():
    assert decay_factor(30, 30) == pytest.approx(0.5)
    assert decay_factor(60, 30) == pytest.approx(0.25)
    hm = Heatmap(640, 480, 64, half_life=30)
    hm.add([(320, 240)], t=0.0)
    hm.add([], t=30.0)
    assert hm.grid("live")[24, 32] == pytest.approx(0.5)
    assert hm.grid("accum")[24, 32] == 1.0               # el acumulado no decae


def test_reiniciar_mapa():
    hm = Heatmap(640, 480)
    hm.add([(10, 10)] * 5, t=0.0)
    hm.reset()
    assert hm.grid("live").sum() == 0 and hm.grid("accum").sum() == 0


def test_render_deja_transparente_lo_frio():
    frame = np.full((480, 640, 3), 100, np.uint8)
    hm = Heatmap(640, 480)
    hm.add([(600, 440)] * 10, t=0.0)
    out = render(frame, hm.grid("accum"))
    assert (out[10, 10] == 100).all()                   # zona sin calor: intacta
    assert not (out[440, 600] == 100).all()             # zona caliente: coloreada
