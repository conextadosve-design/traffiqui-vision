"""Compara detectores de personas: precisión COCO (solo personas) y velocidad en CPU.

    python tools/detector/evaluar.py coco_val.parquet --n 500 models/candidato-a.onnx models/candidato-b.onnx yolo11n:480

Un .onnx en el formato de Traffiqui (ver app/vision/detector.py) o "yolo11n:<tamaño>" como referencia
(necesita ultralytics, solo para comparar). El parquet es el de Hugging Face detection-datasets/coco.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import statistics
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pyarrow.parquet as pq
from pycocotools.coco import COCO
from pycocotools.cocoeval import COCOeval

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.vision.detector import PersonDetector  # noqa: E402


def load(parquet: str, n: int):
    rows = []
    f = pq.ParquetFile(parquet)
    for rg in range(f.num_row_groups):
        for r in f.read_row_group(rg).to_pylist():
            rows.append(r)
            if len(rows) >= n:
                return rows
    return rows


def gt_coco(rows) -> COCO:
    images, anns, k = [], [], 1
    for r in rows:
        images.append({"id": r["image_id"], "width": r["width"], "height": r["height"]})
        o = r["objects"]
        for cat, (x1, y1, x2, y2), area in zip(o["category"], o["bbox"], o["area"]):
            if cat == 0:
                anns.append({"id": k, "image_id": r["image_id"], "category_id": 1, "bbox": [x1, y1, x2 - x1, y2 - y1],
                             "area": area, "iscrowd": 0})
                k += 1
    c = COCO()
    c.dataset = {"images": images, "annotations": anns, "categories": [{"id": 1, "name": "person"}]}
    with contextlib.redirect_stdout(io.StringIO()):
        c.createIndex()
    return c


def make(spec: str):
    if spec.startswith("yolo11n:"):
        from ultralytics import YOLO
        size = int(spec.split(":")[1])
        m = YOLO("models/yolo11n.pt")

        def run(img):
            r = m.predict(img, imgsz=size, conf=0.01, classes=[0], verbose=False)[0]
            return r.boxes.xyxy.cpu().numpy(), r.boxes.conf.cpu().numpy()
        return spec, run
    det = PersonDetector(spec)

    def run(img):
        d = det.detect(img, conf=0.01)
        return d.xyxy, d.confidence
    return f"{det.name} ({det.size}px)", run


def evaluate(rows, gt, spec):
    name, run = make(spec)
    imgs = [cv2.imdecode(np.frombuffer(r["image"]["bytes"], np.uint8), cv2.IMREAD_COLOR) for r in rows]
    for img in imgs[:5]:
        run(img)  # calentamiento
    res, times = [], []
    for r, img in zip(rows, imgs):
        t0 = time.perf_counter()
        boxes, scores = run(img)
        times.append((time.perf_counter() - t0) * 1000)
        for (x1, y1, x2, y2), s in zip(boxes, scores):
            res.append({"image_id": r["image_id"], "category_id": 1, "bbox": [float(x1), float(y1), float(x2 - x1),
                                                                                  float(y2 - y1)], "score": float(s)})
    with contextlib.redirect_stdout(io.StringIO()):
        dt = gt.loadRes(res) if res else COCO()
        ev = COCOeval(gt, dt, "bbox")
        ev.evaluate(); ev.accumulate(); ev.summarize()
    s = ev.stats
    return {"name": name, "AP": s[0], "AP50": s[1], "AP_small": s[3], "AP_medium": s[4], "AP_large": s[5],
            "AR100": s[8], "ms": statistics.median(times)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("parquet")
    ap.add_argument("specs", nargs="+")
    ap.add_argument("--n", type=int, default=500)
    a = ap.parse_args()
    rows = load(a.parquet, a.n)
    gt = gt_coco(rows)
    print(f"{len(rows)} imágenes, {len(gt.getAnnIds())} personas anotadas\n")
    print(f"{'detector':38} {'AP':>6} {'AP50':>6} {'AP peq':>7} {'AP med':>7} {'AP gr':>6} {'AR100':>6} {'ms CPU':>7}")
    for spec in a.specs:
        m = evaluate(rows, gt, spec)
        print(f"{m['name']:38} {m['AP']:6.3f} {m['AP50']:6.3f} {m['AP_small']:7.3f} {m['AP_medium']:7.3f} "
              f"{m['AP_large']:6.3f} {m['AR100']:6.3f} {m['ms']:7.1f}", flush=True)


if __name__ == "__main__":
    main()
