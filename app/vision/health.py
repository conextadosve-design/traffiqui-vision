"""Salud de cada cámara: sin señal, tapada (o a oscuras) o movida.

- **Sin señal**: la captura lleva más de SIN_SENAL_S sin cuadros.
- **Tapada**: la imagen casi no tiene contraste ni bordes (una mano, un trapo, la lente pintada, la luz
  apagada) durante TAPADA_S.
- **Movida**: se mide cuánto se desplazó, giró o acercó la escena respecto de la referencia, con puntos
  fijos de la imagen (esquinas de estanterías, puertas, baldosas) emparejados entre las dos. Solo se avisa si
  el cambio es grande (más del MOVE_SHIFT del ancho, MOVE_ROT_DEG grados o MOVE_SCALE de zoom) durante
  MOVIDA_S. Las personas no cuentan: sus recuadros se tapan antes de buscar puntos, y si alguien tapa casi
  toda la imagen no se puede comparar y no se avisa. Un cambio de luz o una vibración pequeña tampoco avisan.
  Si la cámara apunta a otro sitio (una escena con tantos puntos como la referencia, pero que no coinciden) sin
  nadie delante durante LOST_S, también es "movida".
  La referencia (solo coordenadas y descriptores de puntos, ninguna imagen) se guarda en disco, así que también
  se nota si la movieron con la app cerrada. Tras recolocarla, "Aceptar la posición actual" toma una nueva.

Todo se calcula sobre una imagen reducida cada CHECK_EVERY_S: no afecta a los FPS.
"""
from __future__ import annotations

import logging
import math
import time
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger("traffiqui.health")

CHECK_EVERY_S = 2.0
SIN_SENAL_S = 15.0
TAPADA_S = 10.0
MOVIDA_S = 45.0
LOST_S = 180.0              # casi nada coincide y no hay nadie delante: apunta a otro sitio
REF_AFTER_S = 20.0          # sin referencia: se toma tras este tiempo de imagen normal
SIZE = (96, 72)             # para "tapada"
MIN_STD = 6.0               # desviación del gris por debajo de la cual la imagen es "plana"
MIN_EDGES = 0.004           # fracción mínima de píxeles de borde
REF_SIZE = (320, 240)       # para "movida": puntos fijos de la escena
MIN_REF_POINTS = 40         # una referencia con menos puntos no sirve (pared lisa, oscuridad): se espera
MIN_MATCHES = 15            # menos puntos coincidentes: no se puede comparar (alguien tapa casi todo)
MOVE_SHIFT = 0.08           # desplazamiento de la escena, en fracción del ancho, para avisar
MOVE_ROT_DEG = 6.0          # giro, en grados
MOVE_SCALE = 0.12           # acercamiento o alejamiento (12 %)
_ORB = cv2.ORB_create(nfeatures=600, fastThreshold=12)
_MATCHER = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)

MESSAGES = {
    "ok": "Funcionando",
    "iniciando": "Comprobando la imagen…",
    "sin_senal": "Sin señal: revisa el cable, la alimentación o la red de la cámara.",
    "tapada": "Imagen tapada o a oscuras: revisa que nada cubra la cámara y que haya luz.",
    "movida": "La cámara se movió: la imagen ya no coincide con su posición. Recolócala o acepta la posición nueva "
              "(y vuelve a calibrarla si cuenta en el plano).",
}


def edge_map(frame: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    gray = cv2.cvtColor(cv2.resize(frame, SIZE, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 40, 120)
    return gray, cv2.dilate(edges, np.ones((3, 3), np.uint8)) > 0


def scene_points(frame: np.ndarray, people=()) -> tuple[np.ndarray, np.ndarray | None]:
    """Puntos fijos de la escena (coordenadas en REF_SIZE y descriptores ORB), sin mirar dentro de las personas."""
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(cv2.resize(frame, REF_SIZE, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4)).apply(gray)   # menos sensible a la luz
    mask = np.full(gray.shape, 255, np.uint8)
    sx, sy = REF_SIZE[0] / w, REF_SIZE[1] / h
    for x1, y1, x2, y2 in people:
        cv2.rectangle(mask, (int(x1 * sx) - 6, int(y1 * sy) - 6), (int(x2 * sx) + 6, int(y2 * sy) + 6), 0, -1)
    kp, des = _ORB.detectAndCompute(gray, mask)
    pts = np.float32([k.pt for k in kp]).reshape(-1, 2)
    return pts, des


def displacement(ref, cur) -> tuple[float, float, float, int] | None:
    """(desplazamiento en fracción del ancho, giro en grados, cambio de escala, puntos que coinciden) de la
    escena actual respecto de la referencia, o None si no hay suficientes puntos para saberlo."""
    (rp, rd), (cp, cd) = ref, cur
    if rd is None or cd is None or len(rp) < MIN_MATCHES or len(cp) < MIN_MATCHES:
        return None
    pairs = _MATCHER.match(rd, cd)
    if len(pairs) < MIN_MATCHES:
        return None
    src = rp[[m.queryIdx for m in pairs]]
    dst = cp[[m.trainIdx for m in pairs]]
    A, inliers = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=4.0)
    if A is None or inliers is None or int(inliers.sum()) < MIN_MATCHES:
        return None
    scale = math.hypot(A[0, 0], A[1, 0])
    rot = math.degrees(math.atan2(A[1, 0], A[0, 0]))
    center = np.array([REF_SIZE[0] / 2, REF_SIZE[1] / 2])
    shift = float(np.linalg.norm(A[:, :2] @ center + A[:, 2] - center)) / REF_SIZE[0]
    return shift, abs(rot), abs(scale - 1), int(inliers.sum())


class CameraHealth:
    def __init__(self, camera_id: str, ref_dir: Path | None = None):
        self.camera_id = camera_id
        self.ref_path = Path(ref_dir) / f"{camera_id}-referencia.npz" if ref_dir else None
        self.state, self.since = "iniciando", time.time()
        self.match: float | None = None     # parte de los puntos de la referencia que siguen en su sitio
        self.shift: tuple[float, float, float] | None = None   # último (desplazamiento, giro, escala) medido
        self._ref = self._load_ref()
        self._last_check = 0.0
        self._last_frame_at = time.time()
        self._bad = {"tapada": None, "movida": None, "perdida": None}
        self._good_since: float | None = None

    def _load_ref(self):
        if not self.ref_path:
            return None
        self.ref_path.with_suffix(".png").unlink(missing_ok=True)   # referencia de bordes de versiones anteriores
        try:
            with np.load(self.ref_path) as z:
                return z["pts"], z["des"]
        except (OSError, KeyError, ValueError):
            return None

    def _save_ref(self, ref) -> None:
        self._ref = ref
        if self.ref_path:
            try:
                self.ref_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.ref_path, "wb") as f:   # solo puntos y descriptores: nada identificable
                    np.savez(f, pts=ref[0], des=ref[1])
            except OSError:
                log.warning("No se pudo guardar la referencia de la cámara %s", self.camera_id)

    def _set(self, state: str, now: float) -> None:
        if state != self.state:
            log.info("Cámara %s: %s → %s", self.camera_id, self.state, state)
            self.state, self.since = state, now

    def reset_reference(self) -> None:
        """La posición actual pasa a ser la buena (después de recolocar o mover la cámara a propósito)."""
        self._ref = None
        if self.ref_path:
            self.ref_path.unlink(missing_ok=True)
        self._good_since = None
        self._bad["movida"] = self._bad["perdida"] = None
        self._set("iniciando", time.time())

    def no_signal(self, now: float | None = None) -> None:
        now = now or time.time()
        if now - self._last_frame_at >= SIN_SENAL_S:
            self._set("sin_senal", now)

    def observe(self, frame: np.ndarray, now: float | None = None, people=()) -> None:
        """`people`: recuadros (x1, y1, x2, y2) de las personas del cuadro, en píxeles; no cuentan como escena."""
        now = now or time.time()
        self._last_frame_at = now
        if now - self._last_check < CHECK_EVERY_S:
            return
        self._last_check = now
        gray, edges = edge_map(frame)
        flat = float(gray.std()) < MIN_STD or float(edges.mean()) < MIN_EDGES
        self._bad["tapada"] = (self._bad["tapada"] or now) if flat else None
        if flat:
            self._good_since = None
            if now - self._bad["tapada"] >= TAPADA_S:
                self._set("tapada", now)
            return
        cur = scene_points(frame, people)
        if self._ref is None:
            self._good_since = self._good_since or now
            if now - self._good_since >= REF_AFTER_S and len(cur[0]) >= MIN_REF_POINTS:
                self._save_ref(cur)
                self._set("ok", now)
            elif self.state != "ok":
                self._set("iniciando", now)
            return
        d = displacement(self._ref, cur)
        if d is None:
            # no se puede comparar. Si hay alguien delante o algo tapa gran parte de la imagen (quedan pocos
            # puntos), no se sabe y no se avisa. Si la imagen tiene tantos puntos como la referencia pero casi
            # ninguno coincide durante LOST_S, la cámara apunta a otro sitio.
            self._bad["movida"] = None
            other_scene = not people and len(cur[0]) >= max(MIN_REF_POINTS, 0.5 * len(self._ref[0]))
            self.match = 0.0 if other_scene else None
            if not other_scene:
                self._bad["perdida"] = None
                return
            self._bad["perdida"] = self._bad["perdida"] or now
            if now - self._bad["perdida"] >= LOST_S:
                self._set("movida", now)
            return
        shift, rot, scale, inliers = d
        self.shift, self.match = (shift, rot, scale), min(1.0, inliers / max(1, len(self._ref[0])))
        self._bad["perdida"] = None
        moved = shift > MOVE_SHIFT or rot > MOVE_ROT_DEG or scale > MOVE_SCALE
        self._bad["movida"] = (self._bad["movida"] or now) if moved else None
        if moved and now - self._bad["movida"] >= MOVIDA_S:
            self._set("movida", now)
        elif not moved:
            self._set("ok", now)

    def snapshot(self) -> dict:
        return {"state": self.state, "since": self.since, "message": MESSAGES[self.state],
                "match": round(self.match, 2) if self.match is not None else None,
                "shift_pct": round(self.shift[0] * 100, 1) if self.shift else None,
                "rot_deg": round(self.shift[1], 1) if self.shift else None, "ok": self.state == "ok"}
