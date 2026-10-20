"""Parámetros de la aplicación. Se guardan en SQLite (fase 3) y se aplican en caliente."""
from __future__ import annotations

import copy
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "models"
DATA_DIR = ROOT / "data"

DEFAULTS: dict = {
    # cámara
    "camera_index": 0,
    "width": 640,
    "height": 480,
    # detección / tracking
    "imgsz": 480,
    "confidence": 0.45,
    "lost_track_seconds": 2.0,
    "min_track_seconds": 1.0,
    # rastros
    "trail_seconds": 3.0,
    "trail_smooth": 4,
    "track_point": "center",  # "center" | "bottom"
    # conteo (coordenadas normalizadas 0–1 para que sobrevivan a cambios de resolución)
    "line": None,          # {"a": [x, y], "b": [x, y], "inverted": false}
    "zones": [],           # [{"id": "z1", "name": "Caja", "points": [[x, y], ...]}]
    "stop_seconds": 10.0,  # permanencia mínima en zona para "se detuvo"
    "buyer_seconds": 20.0,  # segundos en zonas de cajas para contar como "comprador exitoso"
    "staff_hours": 4.0,     # quien supere estas horas en el sistema es personal (0 = desactivado)
    "staff_zone_seconds": 15.0,  # segundos en una "zona de personal" para marcar a alguien como personal
    # mapa de calor
    "heatmap_mode": "live",  # "live" (decae) | "accum"
    "heatmap_half_life": 30.0,
    "heatmap_grid_w": 64,
    # varias cámaras y plano de la tienda
    # [{"id": "cam1", "name": "Cámara 1", "source": "0" | "rtsp://…" | "ruta.mp4", "enabled": true,
    #   "max_fps": 0, "calibration": {"image": [[u, v]…], "plan": [[x, y]…], "H": [[…]], "error_m": 0.1}}]
    "cameras": [],
    "floorplan": None,       # ver app/vision/plan.py
    "reid_reentry_s": 20.0,  # ventana para reconocer a alguien que vuelve a la misma cámara
    "reid_handoff_s": 8.0,   # ventana para el traspaso entre cámaras
    "show_plan_areas": True,  # dibujar las áreas del plano sobre el video (cámaras calibradas)
    # overlays
    "show_boxes": True,
    "show_trails": True,
    "show_heatmap": False,
    "show_zones": True,
    "show_line": True,
    "privacy_blur": False,
}


class Settings:
    """Diccionario de configuración seguro entre hilos."""

    def __init__(self, values: dict | None = None):
        self._lock = threading.Lock()
        self._values = copy.deepcopy(DEFAULTS)
        if values:
            self._values.update(values)
        self.version = 0  # sube con cada cambio; los hilos lo comparan para reaccionar

    def get(self, key: str):
        with self._lock:
            return self._values[key]

    def snapshot(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._values)

    def update(self, changes: dict) -> dict:
        with self._lock:
            for k, v in changes.items():
                if k in DEFAULTS:
                    self._values[k] = v
            self.version += 1
            return copy.deepcopy(self._values)
