"""Exporta YOLO11n a OpenVINO para acelerar la inferencia en CPU.

Uso (con el venv activo y con internet la primera vez):
    .venv\\Scripts\\python.exe -m pip install -r requirements-openvino.txt
    .venv\\Scripts\\python.exe export_openvino.py

El modelo queda en models/yolo11n_openvino_model/ y la app lo usa
automáticamente al iniciar (si existe). Para volver a PyTorch, borra esa carpeta.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from app.vision.model import OPENVINO_DIR, ensure_model


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Exporta YOLO11n a OpenVINO")
    ap.add_argument("--imgsz", type=int, default=480, help="Tamaño de entrada por defecto (480)")
    args = ap.parse_args(argv)
    try:
        import openvino  # noqa: F401
    except ImportError:
        print("Falta el paquete 'openvino'. Instálalo con:\n"
              "  .venv\\Scripts\\python.exe -m pip install -r requirements-openvino.txt")
        return 1
    from ultralytics import YOLO

    pt = ensure_model()
    print(f"Exportando {pt} a OpenVINO (imgsz={args.imgsz}, forma dinámica para poder cambiar imgsz)…")
    out = Path(YOLO(str(pt)).export(format="openvino", imgsz=args.imgsz, dynamic=True, half=False))
    if out.resolve() != OPENVINO_DIR.resolve():
        if OPENVINO_DIR.exists():
            shutil.rmtree(OPENVINO_DIR)
        shutil.move(str(out), OPENVINO_DIR)
    print(f"Listo: {OPENVINO_DIR}\nReinicia la app (run.bat) y verás 'openvino' junto a los FPS.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
