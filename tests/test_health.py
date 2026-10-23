"""Salud de cámaras: sin señal, tapada y movida (con imágenes sintéticas)."""
import cv2
import numpy as np

from app.vision import health as H
from app.vision.health import CameraHealth


def scene(dx=0, angle=0.0):
    """Una tienda inventada: estanterías, cajas y baldosas de tamaños distintos (bordes fijos)."""
    rng = np.random.default_rng(7)
    img = np.full((480, 640, 3), 90, np.uint8)
    for _ in range(25):
        x, y = int(rng.integers(0, 600)), int(rng.integers(0, 440))
        w, h = int(rng.integers(20, 120)), int(rng.integers(20, 160))
        cv2.rectangle(img, (x, y), (x + w, y + h), tuple(int(v) for v in rng.integers(120, 230, 3)), -1)
    M = cv2.getRotationMatrix2D((320, 240), angle, 1.0)
    M[0, 2] += dx
    return cv2.warpAffine(img, M, (640, 480), borderValue=(90, 90, 90))


def feed(h, frame, t0, seconds, step=2.0):
    t = t0
    while t <= t0 + seconds:
        h.observe(frame, t)
        t += step
    return t


def scene2(seed=7, dx=0, dy=0, angle=0.0, scale=1.0):
    rng = np.random.default_rng(seed)
    img = np.full((480, 640, 3), 90, np.uint8)
    for _ in range(25):
        x, y = int(rng.integers(0, 600)), int(rng.integers(0, 440))
        w, h = int(rng.integers(20, 120)), int(rng.integers(20, 160))
        cv2.rectangle(img, (x, y), (x + w, y + h), tuple(int(v) for v in rng.integers(120, 230, 3)), -1)
    M = cv2.getRotationMatrix2D((320, 240), angle, scale)
    M[0, 2] += dx
    M[1, 2] += dy
    return cv2.warpAffine(img, M, (640, 480), borderValue=(90, 90, 90))


def ready(tmp_path, cam="cam1"):
    h = CameraHealth(cam, tmp_path)
    t = feed(h, scene2(), 1000.0, H.REF_AFTER_S + 4)
    assert h.state == "ok"
    return h, t


def test_referencia_y_camara_movida(tmp_path):
    h, t = ready(tmp_path)
    assert (tmp_path / "cam1-referencia.npz").exists()
    t = feed(h, scene2(dx=60, angle=8), t, H.MOVIDA_S + 4)        # golpe a la cámara
    assert h.state == "movida" and h.snapshot()["shift_pct"] > H.MOVE_SHIFT * 100
    # la referencia sobrevive a reiniciar la app
    h2 = CameraHealth("cam1", tmp_path)
    feed(h2, scene2(dx=60, angle=8), t, H.MOVIDA_S + 4)
    assert h2.state == "movida"
    h2.reset_reference()
    feed(h2, scene2(dx=60, angle=8), t + 100, H.REF_AFTER_S + 4)
    assert h2.state == "ok"


def test_movimientos_pequenos_no_avisan(tmp_path):
    h, t = ready(tmp_path)
    for frame in (scene2(dx=15, dy=8), scene2(angle=2.5), scene2(scale=1.05)):   # vibración, se aflojó un poco
        t = feed(h, frame, t, H.MOVIDA_S * 2)
        assert h.state == "ok", h.snapshot()


def test_persona_delante_mucho_rato_no_es_camara_movida(tmp_path):
    h, t = ready(tmp_path)
    near = scene2().copy()
    cv2.rectangle(near, (120, 60), (520, 480), (40, 70, 160), -1)        # alguien sentado frente a la webcam
    t = feed(h, near, t, H.LOST_S + 60)
    assert h.state == "ok"
    h2, t2 = ready(tmp_path / "b")
    for _ in range(int((H.LOST_S + 60) / 2)):                            # y con su recuadro de persona
        h2.observe(near, t2, people=[(120, 60, 520, 480)])
        t2 += 2
    assert h2.state == "ok"


def test_cambio_de_luz_no_avisa(tmp_path):
    h, t = ready(tmp_path)
    for alpha, beta in ((0.55, -20), (1.4, 25)):
        t = feed(h, cv2.convertScaleAbs(scene2(), alpha=alpha, beta=beta), t, H.MOVIDA_S * 2)
        assert h.state == "ok", h.snapshot()


def test_apunta_a_otro_sitio(tmp_path):
    h, t = ready(tmp_path)
    t = feed(h, scene2(seed=99), t, H.MOVIDA_S + 4)
    assert h.state == "ok"                    # todavía no: podría ser algo pasajero
    feed(h, scene2(seed=99), t, H.LOST_S + 4)
    assert h.state == "movida"


def test_referencia_antigua_de_bordes_se_reemplaza(tmp_path):
    (tmp_path / "cam1-referencia.png").write_bytes(b"x")
    h, _ = ready(tmp_path)
    assert not (tmp_path / "cam1-referencia.png").exists() and (tmp_path / "cam1-referencia.npz").exists()


def test_tapada_y_sin_senal(tmp_path):
    h, t = ready(tmp_path, "cam2")
    t = feed(h, np.full((480, 640, 3), 12, np.uint8), t, H.TAPADA_S + 4)
    assert h.state == "tapada"
    t = feed(h, scene2(), t, 4)
    assert h.state == "ok"
    h.no_signal(t + H.SIN_SENAL_S + 1)
    assert h.state == "sin_senal" and not h.snapshot()["ok"]
