"""Detector de personas en ONNX (onnxruntime, solo CPU). Sin PyTorch ni Ultralytics en la tienda.

El modelo se exporta con `tools/detector/exportar.py` a un formato único, sea cual sea la red:

  entrada  images  float32 [1, 3, S, S]  RGB en 0–1 (la normalización de cada red va dentro del grafo)
  salidas  boxes   float32 [1, Q, 4]     x1, y1, x2, y2 normalizados a 0–1
           scores  float32 [1, Q]        probabilidad de "persona"

Junto al .onnx va un .json con el nombre, la licencia y el tamaño de entrada S.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from app.config import MODELS_DIR

log = logging.getLogger("traffiqui.detector")
MODEL_NAME = "detector-personas"   # models/detector-personas.onnx + .json


@dataclass
class Detections:
    xyxy: np.ndarray        # [N, 4] en píxeles del cuadro
    confidence: np.ndarray  # [N]


def _nms(boxes: np.ndarray, scores: np.ndarray, iou: float) -> np.ndarray:
    """Las redes DETR no necesitan NMS; este filtro suave solo quita duplicados raros."""
    if len(boxes) == 0:
        return np.zeros(0, dtype=int)
    idx = cv2.dnn.NMSBoxes([[float(x1), float(y1), float(x2 - x1), float(y2 - y1)] for x1, y1, x2, y2 in boxes],
                           scores.astype(float).tolist(), 0.0, iou)
    return np.array(idx, dtype=int).reshape(-1)


class PersonDetector:
    def __init__(self, path: Path | str | None = None, threads: int | None = None):
        import onnxruntime as ort

        self.path = Path(path) if path else MODELS_DIR / f"{MODEL_NAME}.onnx"
        if not self.path.exists():
            raise FileNotFoundError(f"No se encontró el modelo de detección: {self.path}")
        meta_path = self.path.with_suffix(".json")
        self.meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        self.size = int(self.meta.get("input_size", 640))
        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        # deja núcleos libres para la captura, el servidor y las demás cámaras
        opts.intra_op_num_threads = threads or max(1, min(4, (os.cpu_count() or 2) - 1))
        self.session = ort.InferenceSession(str(self.path), sess_options=opts, providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name
        self.name = self.meta.get("name", self.path.stem)
        log.info("Detector %s (%s, entrada %d px, licencia %s)", self.name, self.path.name, self.size,
                 self.meta.get("license", "?"))

    def preprocess(self, frame_bgr: np.ndarray) -> np.ndarray:
        img = cv2.resize(frame_bgr, (self.size, self.size), interpolation=cv2.INTER_LINEAR)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        return np.ascontiguousarray(img.transpose(2, 0, 1)[None])

    def detect(self, frame_bgr: np.ndarray, conf: float = 0.45) -> Detections:
        h, w = frame_bgr.shape[:2]
        outs = self.session.run(None, {self.input_name: self.preprocess(frame_bgr)})
        named = dict(zip([o.name for o in self.session.get_outputs()], outs))
        boxes, scores = named["boxes"][0], named["scores"][0]
        keep = scores >= conf
        boxes, scores = boxes[keep], scores[keep]
        boxes = np.clip(boxes, 0.0, 1.0) * np.array([w, h, w, h], dtype=np.float32)
        ok = (boxes[:, 2] - boxes[:, 0] > 2) & (boxes[:, 3] - boxes[:, 1] > 2)
        boxes, scores = boxes[ok], scores[ok]
        idx = _nms(boxes, scores, 0.7)
        return Detections(boxes[idx].astype(np.float32), scores[idx].astype(np.float32))
