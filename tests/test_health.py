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


def test_referencia_y_camara_movida(tmp_path):
    h = CameraHealth("cam1", tmp_path)
    t = feed(h, scene(), 1000.0, H.REF_AFTER_S + 4)
    assert h.state == "ok" and (tmp_path / "cam1-referencia.png").exists()
    person = scene().copy()
    cv2.rectangle(person, (300, 150), (360, 400), (20, 60, 200), -1)   # alguien pasa: sigue "ok"
    t = feed(h, person, t, 10)
    assert h.state == "ok"
    t = feed(h, scene(dx=60, angle=8), t, H.MOVIDA_S + 4)        # golpe a la cámara
    assert h.state == "movida" and h.snapshot()["match"] < H.MIN_MATCH
    # la referencia sobrevive a reiniciar la app
    h2 = CameraHealth("cam1", tmp_path)
    feed(h2, scene(dx=60, angle=8), t, H.MOVIDA_S + 4)
    assert h2.state == "movida"
    h2.reset_reference()
    feed(h2, scene(dx=60, angle=8), t + 100, H.REF_AFTER_S + 4)
    assert h2.state == "ok"


def test_tapada_y_sin_senal(tmp_path):
    h = CameraHealth("cam2", tmp_path)
    t = feed(h, scene(), 1000.0, H.REF_AFTER_S + 4)
    t = feed(h, np.full((480, 640, 3), 12, np.uint8), t, H.TAPADA_S + 4)
    assert h.state == "tapada"
    t = feed(h, scene(), t, 4)
    assert h.state == "ok"
    h.no_signal(t + H.SIN_SENAL_S + 1)
    assert h.state == "sin_senal" and not h.snapshot()["ok"]
