"""Texto sobre cuadros. OpenCV (Hershey) no dibuja tildes ni ñ, así que el
texto no ASCII se renderiza con Pillow y se cachea como sprite."""
from __future__ import annotations

from functools import lru_cache

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    "DejaVuSans.ttf",
]


@lru_cache(maxsize=8)
def _font(size: int):
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


@lru_cache(maxsize=512)
def _sprite(text: str, size: int) -> np.ndarray:
    """Máscara (0–255) del texto renderizado."""
    font = _font(size)
    left, top, right, bottom = font.getbbox(text)
    w, h = max(1, right - left), max(1, bottom - top)
    img = Image.new("L", (w + 2, h + 2), 0)
    ImageDraw.Draw(img).text((1 - left, 1 - top), text, font=font, fill=255)
    return np.array(img)


def text_size(text: str, size: int = 16) -> tuple[int, int]:
    m = _sprite(text, size)
    return m.shape[1], m.shape[0]


def put_text(frame: np.ndarray, text: str, org: tuple[int, int], color, size: int = 16) -> None:
    """Dibuja `text` con su esquina superior izquierda en `org`."""
    mask = _sprite(text, size)
    x, y = org
    h, w = mask.shape
    fh, fw = frame.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(fw, x + w), min(fh, y + h)
    if x1 <= x0 or y1 <= y0:
        return
    m = mask[y0 - y:y1 - y, x0 - x:x1 - x, None].astype(np.float32) / 255.0
    roi = frame[y0:y1, x0:x1]
    roi[:] = (roi * (1 - m) + np.array(color, np.float32) * m).astype(np.uint8)


def label(frame: np.ndarray, text: str, org: tuple[int, int], bg, fg, size: int = 15, pad: int = 4) -> None:
    """Etiqueta con fondo sólido; `org` = esquina inferior izquierda."""
    tw, th = text_size(text, size)
    x, y = org
    y_top = max(0, y - th - 2 * pad)
    cv2.rectangle(frame, (x, y_top), (x + tw + 2 * pad, y_top + th + 2 * pad), bg, -1)
    put_text(frame, text, (x + pad, y_top + pad), fg, size)
