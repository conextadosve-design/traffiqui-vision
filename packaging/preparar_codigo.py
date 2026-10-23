"""Copia el código de Traffiqui (app/ y cloud/) a dist/Traffiqui/codigo, junto a la base empaquetada.

    python packaging/preparar_codigo.py [--version 1.2.3]

El instalador completo lleva base + código; el de actualización, solo esta carpeta.
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="dev")
    ap.add_argument("--dest", default=str(ROOT / "dist" / "Traffiqui" / "codigo"))
    a = ap.parse_args()
    dest = Path(a.dest)
    if dest.exists():
        shutil.rmtree(dest)
    for pkg in ("app", "cloud"):
        shutil.copytree(ROOT / pkg, dest / pkg, ignore=SKIP)
    (dest / "VERSION").write_text(a.version + "\n", encoding="utf-8")
    size = sum(p.stat().st_size for p in dest.rglob("*") if p.is_file())
    print(f"Código {a.version} en {dest} ({size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
