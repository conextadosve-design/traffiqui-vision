"""Salud de cada cámara: sin señal, tapada (o a oscuras) o movida.

- **Sin señal**: la captura lleva más de SIN_SENAL_S sin cuadros.
- **Tapada**: la imagen casi no tiene contraste ni bordes (una mano, un trapo, la lente pintada, la luz
  apagada) durante TAPADA_S.
- **Movida**: los bordes fijos de la escena (estanterías, puertas, el piso) ya no coinciden con los de la
  referencia durante MOVIDA_S. Las personas cambian poco los bordes de toda la imagen; un golpe a la
  cámara los cambia casi todos. La referencia se guarda en disco, así que también se nota si la movieron
  con la app cerrada. Tras recolocarla, "Aceptar la posición actual" toma una referencia nueva.

Todo se calcula sobre una imagen reducida cada CHECK_EVERY_S: no afecta a los FPS.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger("traffiqui.health")

CHECK_EVERY_S = 2.0
SIN_SENAL_S = 15.0
TAPADA_S = 10.0
MOVIDA_S = 30.0
REF_AFTER_S = 20.0          # sin referencia: se toma tras este tiempo de imagen normal
SIZE = (96, 72)
MIN_STD = 6.0               # desviación del gris por debajo de la cual la imagen es "plana"
MIN_EDGES = 0.004           # fracción mínima de píxeles de borde
MIN_MATCH = 0.55            # parecido de bordes con la referencia por debajo del cual está "movida"
                            # (6 personas grandes en cuadro dejan ~0,70; desplazar ~5 % o girar ~8° baja a ~0,5)

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


def edge_match(ref: np.ndarray, cur: np.ndarray) -> float:
    """Qué parte de los bordes de la referencia sigue ahí (0–1)."""
    n = int(ref.sum())
    return float((ref & cur).sum()) / n if n else 1.0


class CameraHealth:
    def __init__(self, camera_id: str, ref_dir: Path | None = None):
        self.camera_id = camera_id
        self.ref_path = Path(ref_dir) / f"{camera_id}-referencia.png" if ref_dir else None
        self.state, self.since = "iniciando", time.time()
        self.match: float | None = None
        self._ref: np.ndarray | None = self._load_ref()
        self._last_check = 0.0
        self._last_frame_at = time.time()
        self._bad = {"tapada": None, "movida": None}
        self._good_since: float | None = None

    def _load_ref(self) -> np.ndarray | None:
        if self.ref_path and self.ref_path.exists():
            img = cv2.imread(str(self.ref_path), cv2.IMREAD_GRAYSCALE)
            if img is not None and img.shape[::-1] == SIZE:
                return img > 0
        return None

    def _save_ref(self, ref: np.ndarray) -> None:
        self._ref = ref
        if self.ref_path:
            try:
                self.ref_path.parent.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(self.ref_path), ref.astype(np.uint8) * 255)  # solo bordes: nada identificable
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
        self._bad["movida"] = None
        self._set("iniciando", time.time())

    def no_signal(self, now: float | None = None) -> None:
        now = now or time.time()
        if now - self._last_frame_at >= SIN_SENAL_S:
            self._set("sin_senal", now)

    def observe(self, frame: np.ndarray, now: float | None = None) -> None:
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
        if self._ref is None:
            self._good_since = self._good_since or now
            if now - self._good_since >= REF_AFTER_S:
                self._save_ref(edges)
                self._set("ok", now)
            elif self.state != "ok":
                self._set("iniciando", now)
            return
        self.match = edge_match(self._ref, edges)
        moved = self.match < MIN_MATCH
        self._bad["movida"] = (self._bad["movida"] or now) if moved else None
        if moved and now - self._bad["movida"] >= MOVIDA_S:
            self._set("movida", now)
        elif not moved:
            self._set("ok", now)

    def snapshot(self) -> dict:
        return {"state": self.state, "since": self.since, "message": MESSAGES[self.state],
                "match": round(self.match, 2) if self.match is not None else None, "ok": self.state == "ok"}
