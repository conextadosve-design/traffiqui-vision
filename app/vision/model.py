"""Carga del modelo YOLO11n: usa OpenVINO si fue exportado, si no el .pt."""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from app.config import MODELS_DIR

log = logging.getLogger("traffiqui.model")
PT_PATH = MODELS_DIR / "yolo11n.pt"
OPENVINO_DIR = MODELS_DIR / "yolo11n_openvino_model"


def ensure_model() -> Path:
    """Descarga yolo11n.pt a models/ la primera vez (única vez que se usa internet)."""
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    if PT_PATH.exists():
        return PT_PATH
    from ultralytics.utils.downloads import attempt_download_asset

    log.info("Descargando yolo11n.pt (solo la primera vez)…")
    downloaded = Path(attempt_download_asset("yolo11n.pt"))
    if downloaded.resolve() != PT_PATH.resolve():
        shutil.move(str(downloaded), PT_PATH)
    return PT_PATH


def load_model():
    from ultralytics import YOLO

    if OPENVINO_DIR.exists():
        try:
            import openvino  # noqa: F401
        except ImportError:
            log.warning("Hay un modelo OpenVINO pero falta el paquete 'openvino' "
                        "(pip install -r requirements-openvino.txt). Se usa PyTorch.")
        else:
            log.info("Usando modelo OpenVINO: %s", OPENVINO_DIR)
            return YOLO(str(OPENVINO_DIR), task="detect"), "openvino"
    path = ensure_model()
    log.info("Usando modelo PyTorch: %s", path)
    return YOLO(str(path), task="detect"), "pytorch"
