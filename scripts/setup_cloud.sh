#!/usr/bin/env bash
# Instalación en un entorno Linux sin cámara (sesiones de Claude en la nube, CI).
# Sirve para programar y correr los tests; la cámara y el video en vivo se prueban en la PC local.
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m venv .venv
. .venv/bin/activate
python -m pip install --quiet --upgrade pip
# PyTorch solo-CPU (la versión por defecto de Linux trae CUDA y pesa varios GB)
if ! python -m pip install --quiet --retries 1 --timeout 15 torch==2.14.1 torchvision==0.29.1 --index-url https://download.pytorch.org/whl/cpu; then
    # si la red de la sesión bloquea download.pytorch.org, se usa PyPI: el wheel de Linux de PyPI
    # trae las librerías CUDA (varios GB más) pero corre igual en CPU
    echo "AVISO: download.pytorch.org no responde; instalando torch desde PyPI (con CUDA, más pesado)" >&2
    python -m pip install --quiet torch==2.14.1 torchvision==0.29.1
fi
# el resto de requirements.txt; OpenCV "headless" porque en la nube no hay pantalla (evita depender de libGL)
grep -v -E '^(torch|torchvision|opencv-python)==' requirements.txt > /tmp/requirements-cloud.txt
python -m pip install --quiet -r /tmp/requirements-cloud.txt opencv-python-headless==5.0.0.93
# servidor central de la multisede (cloud/)
python -m pip install --quiet -r cloud/requirements.txt
python -m pytest -q tests
