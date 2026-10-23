#!/usr/bin/env bash
# Instalación en un entorno Linux sin cámara (sesiones de Claude en la nube, CI).
# Sirve para programar y correr los tests; la cámara y el video en vivo se prueban en la PC local.
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m venv .venv
. .venv/bin/activate
python -m pip install --quiet --upgrade pip
# OpenCV "headless" porque en la nube no hay pantalla (evita depender de libGL)
grep -v -E '^opencv-python==' requirements.txt > /tmp/requirements-cloud.txt
python -m pip install --quiet -r /tmp/requirements-cloud.txt opencv-python-headless==5.0.0.93
# servidor central de la multisede (cloud/)
python -m pip install --quiet -r cloud/requirements.txt
python -m pytest -q tests
