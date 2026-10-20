"""Color único y estable por track_id.

El tono se avanza con la proporción áurea para que IDs consecutivos queden
lejos en la rueda de color; saturación y brillo altos para que se vean sobre
cualquier fondo.
"""
from __future__ import annotations

import colorsys
from functools import lru_cache

GOLDEN_RATIO_CONJUGATE = 0.6180339887498949
_HUE_OFFSET = 0.11  # evita que el ID 0 sea rojo puro (rojo = color de alerta)
_SATURATION = 0.85
_VALUE = 0.95


def hue_for_id(track_id: int) -> float:
    """Tono en [0, 1) determinístico a partir del ID."""
    return (_HUE_OFFSET + int(track_id) * GOLDEN_RATIO_CONJUGATE) % 1.0


@lru_cache(maxsize=4096)
def color_for_id(track_id: int) -> tuple[int, int, int]:
    """Color BGR (para OpenCV) del track."""
    r, g, b = colorsys.hsv_to_rgb(hue_for_id(track_id), _SATURATION, _VALUE)
    return int(b * 255), int(g * 255), int(r * 255)


def hex_for_id(track_id: int) -> str:
    """Color en hex (#RRGGBB) para la UI y la base de datos."""
    b, g, r = color_for_id(track_id)
    return f"#{r:02X}{g:02X}{b:02X}"


def text_color_for(bgr: tuple[int, int, int]) -> tuple[int, int, int]:
    """Blanco o negro según la luminancia relativa del fondo (WCAG)."""

    def lin(c: int) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    b, g, r = bgr
    lum = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
    # contraste con negro = (lum+0.05)/0.05, con blanco = 1.05/(lum+0.05)
    return (0, 0, 0) if (lum + 0.05) / 0.05 > 1.05 / (lum + 0.05) else (255, 255, 255)
