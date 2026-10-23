"""Una sola persona frente a la cámara debe ser UNA persona, aunque el detector dude por momentos."""
import numpy as np

from app.config import Settings
from app.vision import pipeline as pl
from app.vision.detector import Detections
from app.vision.fusion import GlobalTracker, Observation


class FlickerModel:
    """Una persona quieta cuya puntuación baja por debajo del umbral 1 de cada 3 cuadros (de cerca, de lado…)."""

    def __init__(self):
        self.n = 0
        self.asked = []

    def detect(self, frame, conf):
        self.asked.append(conf)
        self.n += 1
        score = 0.35 if self.n % 3 == 0 else 0.85
        box = np.array([[200 + self.n % 5, 100, 420, 470]], np.float32)   # se mueve un poco
        keep = np.array([score]) >= conf
        return Detections(box[keep], np.array([score], np.float32)[keep])


def test_la_puntuacion_que_baja_no_crea_personas_nuevas(tmp_path, monkeypatch):
    monkeypatch.setattr(pl, "DATA_DIR", tmp_path)
    p = pl.PipelineThread(capture=None, settings=Settings())
    p.model = FlickerModel()
    cfg = Settings().snapshot()
    ids = set()
    for i in range(120):   # 12 s a 10 FPS
        p._process(np.zeros((480, 640, 3), np.uint8), cfg, 1000 + i / 10)
        ids |= set(p.visible_ids)
    assert p.model.asked[0] < cfg["confidence"]   # las detecciones dudosas llegan a ByteTrack
    assert len(ids) == 1, ids


MIXED = np.zeros(128, np.float32)
MIXED[0], MIXED[40], MIXED[64], MIXED[100] = 0.36, 0.64, 0.36, 0.64   # parecido 0,6 a RED (otra luz, de lado)
RED = np.zeros(128, np.float32)
RED[0] = RED[64] = 1.0


def obs(tid, app, img):
    return Observation("A", tid, None, img, app)


def test_reaparece_en_el_mismo_sitio_al_momento_es_la_misma_persona():
    gt = GlobalTracker()
    g1, _ = gt.observe(obs(1, RED, (0.5, 0.95)), 10.0)
    g2, why = gt.observe(obs(2, MIXED, (0.52, 0.95)), 12.0)
    assert g1 == g2 and why == "re-entrada"


def test_reaparicion_rapida_pero_lejos_o_tarde_exige_ropa_parecida():
    gt = GlobalTracker()
    g1, _ = gt.observe(obs(1, RED, (0.1, 0.95)), 10.0)
    far, _ = gt.observe(obs(2, MIXED, (0.9, 0.95)), 12.0)      # otro lado de la imagen
    assert far != g1
    gt = GlobalTracker()
    g1, _ = gt.observe(obs(1, RED, (0.5, 0.95)), 10.0)
    late, _ = gt.observe(obs(2, MIXED, (0.5, 0.95)), 18.0)     # 8 s después: hace falta ropa parecida de verdad
    assert late != g1


BLUE = np.zeros(128, np.float32)
BLUE[40] = BLUE[100] = 1.0
CLOSE = 0.9 * RED + 0.1 * MIXED    # la misma ropa con otra luz: parecido ~0,95


def test_memoria_de_cinco_minutos():
    gt = GlobalTracker()                                    # valores por defecto: 5 min
    g1, _ = gt.observe(obs(1, RED, (0.2, 0.95)), 1000.0)
    g2, why = gt.observe(obs(2, CLOSE, (0.8, 0.95)), 1000.0 + 4 * 60)   # vuelve a los 4 min por otro lado
    assert g1 == g2 and why == "re-entrada"
    gt.expire(1000.0 + 4 * 60 + 1)
    g3, _ = gt.observe(obs(3, CLOSE, (0.8, 0.95)), 1000.0 + 4 * 60 + 5 * 60 + 30)   # 5,5 min después: visita nueva
    assert g3 != g1


def test_tras_un_minuto_se_exige_ropa_mas_parecida():
    gt = GlobalTracker()
    g1, _ = gt.observe(obs(1, RED, (0.5, 0.95)), 1000.0)
    other, _ = gt.observe(obs(2, BLUE, (0.5, 0.95)), 1030.0)      # otra ropa: nunca
    assert other != g1
    gt = GlobalTracker()
    g1, _ = gt.observe(obs(1, RED, (0.5, 0.95)), 1000.0)
    MID = 0.55 * RED + 0.45 * BLUE                                  # parecido ~0,74: vale al rato, no a los 3 min
    late, _ = gt.observe(obs(2, MID, (0.2, 0.95)), 1000.0 + 180)
    assert late != g1
    gt = GlobalTracker()
    g1, _ = gt.observe(obs(1, RED, (0.5, 0.95)), 1000.0)
    soon, _ = gt.observe(obs(2, MID, (0.2, 0.95)), 1000.0 + 30)
    assert soon == g1


def test_la_visita_sigue_abierta_mientras_dura_la_memoria():
    gt = GlobalTracker()
    gt.observe(obs(1, RED, (0.5, 0.95)), 1000.0)
    assert gt.expire(1000.0 + 120) == []                    # salió hace 2 min: puede volver
    ended = gt.expire(1000.0 + 301)
    assert len(ended) == 1 and ended[0].seconds == 0        # el tiempo de espera no cuenta como permanencia
