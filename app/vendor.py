"""Archivos de la interfaz que comparten la app de la tienda y la sede principal (`/vendor/...`).

Solo se sirven los de esta lista: estilos, gráficos, icono, manifiesto (para instalar el panel en el teléfono)
y los scripts comunes (pestañas en el teléfono y tutorial de bienvenida).
"""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse

STATIC = Path(__file__).parent / "static"
FILES = {
    "styles.css": "text/css",
    "chart.umd.min.js": "text/javascript",
    "ui.js": "text/javascript",
    "backup.js": "text/javascript",
    "icono.svg": "image/svg+xml",
    "icono-192.png": "image/png",
    "icono-512.png": "image/png",
    "manifest.webmanifest": "application/manifest+json",
}


def vendor_file(name: str) -> FileResponse:
    if name not in FILES:
        raise HTTPException(404, "No encontrado.")
    return FileResponse(STATIC / name, media_type=FILES[name], headers={"Cache-Control": "no-cache"})
