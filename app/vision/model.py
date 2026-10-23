"""Carga del detector de personas (ONNX, licencia Apache-2.0; ver app/vision/detector.py)."""
from __future__ import annotations

import logging

from app.config import MODELS_DIR
from app.vision.detector import MODEL_NAME, PersonDetector

log = logging.getLogger("traffiqui.model")
# "preciso" = D-FINE-S (más acierto); "rapido" = D-FINE-N (menos CPU, para PCs con muchas cámaras)
FILES = {"preciso": f"{MODEL_NAME}.onnx", "rapido": f"{MODEL_NAME}-rapido.onnx"}


def load_model(mode: str = "preciso") -> tuple[PersonDetector, str]:
    det = PersonDetector(MODELS_DIR / FILES.get(mode, FILES["preciso"]))
    return det, f"onnx · {det.name}"
