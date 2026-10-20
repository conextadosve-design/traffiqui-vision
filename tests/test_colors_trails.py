import numpy as np

from app.vision.colors import color_for_id, hue_for_id, text_color_for
from app.vision.trails import TrailStore, alpha_for_age, smooth_points, thickness_for_age


def test_color_estable_por_id():
    assert color_for_id(7) == color_for_id(7)
    assert all(0 <= c <= 255 for c in color_for_id(7))


def test_ids_consecutivos_tienen_tonos_lejanos():
    for i in range(1, 200):
        d = abs(hue_for_id(i) - hue_for_id(i + 1))
        assert min(d, 1 - d) > 0.2


def test_texto_legible():
    assert text_color_for((255, 255, 255)) == (0, 0, 0)
    assert text_color_for((40, 20, 10)) == (255, 255, 255)


def test_opacidad_lineal_por_antiguedad():
    assert alpha_for_age(0, 3) == 1.0
    assert abs(alpha_for_age(1.5, 3) - 0.5) < 1e-9
    assert alpha_for_age(3, 3) == 0.0
    assert alpha_for_age(10, 3) == 0.0
    assert thickness_for_age(0, 3, 6) == 6
    assert thickness_for_age(3, 3, 6) == 0


def test_suavizado_quita_zigzag():
    pts = [(i * 10.0, 0.0 if i % 2 else 10.0, float(i)) for i in range(10)]
    sm = smooth_points(pts, 4)
    assert np.ptp([p[1] for p in sm[2:-2]]) < np.ptp([p[1] for p in pts])
    assert [p[2] for p in sm] == [p[2] for p in pts]


def test_rastro_se_desvanece_despues_de_salir():
    ts = TrailStore(duration=3.0)
    for i in range(5):
        ts.add(1, 10 * i, 10, 100.0 + i * 0.1)
    ts.prune(102.0)          # la persona ya no está, pero el rastro sigue
    assert ts.active_ids() == [1]
    ts.prune(103.5)          # todos los puntos tienen más de 3 s
    assert ts.active_ids() == []


def test_dibujo_mezcla_alfa_sin_tapar():
    frame = np.zeros((50, 100, 3), np.uint8)
    ts = TrailStore(duration=3.0, smooth_window=1)
    ts.add(1, 5, 25, 0.0)
    ts.add(1, 95, 25, 0.0)
    ts.draw(frame, now=1.5, color_fn=lambda _: (255, 255, 255))
    v = int(frame[25, 50, 0])
    assert 0 < v < 255   # semitransparente, no color sólido
