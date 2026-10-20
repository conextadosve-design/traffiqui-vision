"""Rastros del recorrido con desvanecimiento por antigüedad.

Cada track guarda una cola de puntos (x, y, t). Al dibujar:
  * se suavizan las posiciones con una media móvil;
  * cada segmento recibe opacidad y grosor que bajan linealmente con la edad
    hasta 0 a los `duration` segundos;
  * la transparencia es mezcla alfa real: los segmentos se agrupan en niveles
    de opacidad y cada nivel se dibuja en una capa que se mezcla con
    cv2.addWeighted, solo dentro del rectángulo que ocupan los rastros.
Un track que sale del cuadro deja de recibir puntos pero su rastro sigue
aquí hasta que el último punto envejece; por eso no desaparece de golpe.
"""
from __future__ import annotations

import threading
from collections import deque
from typing import Callable

import cv2
import numpy as np

ALPHA_LEVELS = 6  # niveles de opacidad (más niveles = degradado más fino, más costo)


def alpha_for_age(age: float, duration: float) -> float:
    """Opacidad en [0, 1]: 1 para un punto recién creado, 0 a los `duration` s."""
    if duration <= 0 or age >= duration:
        return 0.0
    return max(0.0, 1.0 - age / duration)


def thickness_for_age(age: float, duration: float, max_thickness: int) -> int:
    """Grosor en px que baja linealmente con la edad (0 = no se dibuja)."""
    return int(round(max_thickness * alpha_for_age(age, duration)))


def smooth_points(points: list[tuple[float, float, float]], window: int) -> list[tuple[float, float, float]]:
    """Media móvil centrada sobre x, y. Conserva el timestamp de cada punto."""
    n = len(points)
    if window <= 1 or n < 3:
        return points
    half = window // 2
    xs = np.fromiter((p[0] for p in points), float, n)
    ys = np.fromiter((p[1] for p in points), float, n)
    cx = np.concatenate(([0.0], np.cumsum(xs)))
    cy = np.concatenate(([0.0], np.cumsum(ys)))
    out = []
    for i in range(n):
        a, b = max(0, i - half), min(n, i + half + 1)
        out.append(((cx[b] - cx[a]) / (b - a), (cy[b] - cy[a]) / (b - a), points[i][2]))
    return out


class TrailStore:
    def __init__(self, duration: float = 3.0, smooth_window: int = 4, max_thickness: int = 6):
        self.duration = duration
        self.smooth_window = smooth_window
        self.max_thickness = max_thickness
        self._trails: dict[int, deque] = {}
        self._lock = threading.Lock()

    def add(self, track_id: int, x: float, y: float, t: float) -> None:
        with self._lock:
            self._trails.setdefault(track_id, deque()).append((x, y, t))

    def prune(self, now: float) -> None:
        """Quita puntos más viejos que `duration` y rastros vacíos."""
        limit = now - self.duration
        with self._lock:
            for tid in list(self._trails):
                q = self._trails[tid]
                while q and q[0][2] < limit:
                    q.popleft()
                if not q:
                    del self._trails[tid]

    def clear(self) -> None:
        with self._lock:
            self._trails.clear()

    def active_ids(self) -> list[int]:
        with self._lock:
            return list(self._trails)

    def _segments(self, now: float):
        """(nivel, p1, p2, grosor, track_id) de todos los segmentos visibles."""
        with self._lock:
            snapshot = {tid: list(q) for tid, q in self._trails.items()}
        segs = []
        for tid, pts in snapshot.items():
            pts = smooth_points(pts, self.smooth_window)
            for (x1, y1, _), (x2, y2, t2) in zip(pts, pts[1:]):
                age = now - t2
                a = alpha_for_age(age, self.duration)
                th = thickness_for_age(age, self.duration, self.max_thickness)
                if a <= 0 or th <= 0:
                    continue
                level = min(ALPHA_LEVELS - 1, int(a * ALPHA_LEVELS))
                segs.append((level, (int(x1), int(y1)), (int(x2), int(y2)), th, tid))
        return segs

    def draw(self, frame: np.ndarray, now: float, color_fn: Callable[[int], tuple[int, int, int]]) -> None:
        segs = self._segments(now)
        if not segs:
            return
        h, w = frame.shape[:2]
        pad = self.max_thickness + 2
        xs = [p[0] for s in segs for p in (s[1], s[2])]
        ys = [p[1] for s in segs for p in (s[1], s[2])]
        x0, x1 = max(0, min(xs) - pad), min(w, max(xs) + pad)
        y0, y1 = max(0, min(ys) - pad), min(h, max(ys) + pad)
        if x1 <= x0 or y1 <= y0:
            return
        roi = frame[y0:y1, x0:x1]
        by_level: dict[int, list] = {}
        for s in segs:
            by_level.setdefault(s[0], []).append(s)
        # de más transparente a más opaco, para que lo reciente quede encima
        for level in sorted(by_level):
            alpha = (level + 1) / ALPHA_LEVELS
            layer = roi.copy()
            for _, p1, p2, th, tid in by_level[level]:
                cv2.line(layer, (p1[0] - x0, p1[1] - y0), (p2[0] - x0, p2[1] - y0),
                         color_fn(tid), th, cv2.LINE_AA)
            cv2.addWeighted(layer, alpha, roi, 1 - alpha, 0, dst=roi)
