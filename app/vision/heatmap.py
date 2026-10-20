"""Mapa de calor: grilla de posiciones con modo en vivo (decae) y acumulado."""
from __future__ import annotations

import threading

import cv2
import numpy as np


def grid_shape(grid_w: int, frame_w: int, frame_h: int) -> tuple[int, int]:
    """(alto, ancho) de la grilla, proporcional al cuadro."""
    return max(1, round(grid_w * frame_h / frame_w)), grid_w


def cell_for(x: float, y: float, frame_w: int, frame_h: int, gh: int, gw: int) -> tuple[int, int]:
    """Celda (fila, columna) del punto (x, y) en píxeles."""
    col = int(np.clip(x / frame_w * gw, 0, gw - 1))
    row = int(np.clip(y / frame_h * gh, 0, gh - 1))
    return row, col


def decay_factor(dt: float, half_life: float) -> float:
    """Factor multiplicativo tras `dt` s con vida media `half_life`."""
    if half_life <= 0:
        return 0.0
    return 0.5 ** (dt / half_life)


class Heatmap:
    def __init__(self, frame_w: int, frame_h: int, grid_w: int = 64, half_life: float = 30.0):
        self._lock = threading.Lock()
        self.half_life = half_life
        self.resize(frame_w, frame_h, grid_w)

    def resize(self, frame_w: int, frame_h: int, grid_w: int) -> None:
        with self._lock:
            self.frame_w, self.frame_h = frame_w, frame_h
            self.gh, self.gw = grid_shape(grid_w, frame_w, frame_h)
            self.live = np.zeros((self.gh, self.gw), np.float32)
            self.accum = np.zeros((self.gh, self.gw), np.float32)
            # posiciones desde la última foto a SQLite; no se borra con reset() porque es histórico
            self.pending = np.zeros((self.gh, self.gw), np.float32)
            self._last_t: float | None = None

    def reset(self) -> None:
        """Reinicia lo que se ve en el video (en vivo y acumulado). El histórico queda."""
        with self._lock:
            self.live[:] = 0
            self.accum[:] = 0

    def take_pending(self) -> np.ndarray:
        with self._lock:
            out = self.pending.copy()
            self.pending[:] = 0
            return out

    def add(self, points: list[tuple[float, float]], t: float) -> None:
        """Agrega las posiciones de un cuadro procesado. El modo en vivo decae antes."""
        with self._lock:
            if self._last_t is not None:
                self.live *= decay_factor(t - self._last_t, self.half_life)
            self._last_t = t
            for x, y in points:
                r, c = cell_for(x, y, self.frame_w, self.frame_h, self.gh, self.gw)
                self.live[r, c] += 1.0
                self.accum[r, c] += 1.0
                self.pending[r, c] += 1.0

    def grid(self, mode: str) -> np.ndarray:
        with self._lock:
            return (self.live if mode == "live" else self.accum).copy()


def render(frame: np.ndarray, grid: np.ndarray, alpha: float = 0.55,
           colormap: int = cv2.COLORMAP_TURBO, sigma: float = 1.2) -> np.ndarray:
    """Superpone la grilla al cuadro: suavizado, normalización, colormap y alfa
    por píxel proporcional al calor (las zonas frías quedan transparentes)."""
    if grid.max() <= 0:
        return frame
    g = cv2.GaussianBlur(grid.astype(np.float32), (0, 0), sigma)
    g = g / (g.max() or 1.0)
    h, w = frame.shape[:2]
    g = cv2.resize(g, (w, h), interpolation=cv2.INTER_CUBIC).clip(0, 1)
    color = cv2.applyColorMap((g * 255).astype(np.uint8), colormap)
    a = (np.sqrt(g) * alpha)[..., None]  # sqrt: el calor bajo también se nota
    return (frame * (1 - a) + color * a).astype(np.uint8)
