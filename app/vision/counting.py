"""Conteo: línea virtual, zonas y permanencia.

La lógica geométrica y de estado es pura (sin OpenCV) para poder probarla
sin cámara. Las coordenadas que llegan aquí están en píxeles del cuadro.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

Point = tuple[float, float]

DWELL_BUCKETS = [  # (etiqueta, desde s, hasta s)
    ("<10 s", 0, 10),
    ("10–30 s", 10, 30),
    ("30–60 s", 30, 60),
    ("1–3 min", 60, 180),
    (">3 min", 180, float("inf")),
]


# ---- geometría -------------------------------------------------------------------
def signed_distance(p: Point, a: Point, b: Point) -> float:
    """Distancia con signo de p a la recta a→b. Positivo = lado de la normal (-dy, dx)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = (dx * dx + dy * dy) ** 0.5 or 1.0
    return (dx * (p[1] - a[1]) - dy * (p[0] - a[0])) / length


def projection_t(p: Point, a: Point, b: Point) -> float:
    """Posición de la proyección de p sobre a→b (0 = a, 1 = b)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    l2 = dx * dx + dy * dy or 1.0
    return ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2


def point_in_polygon(p: Point, poly: list[Point]) -> bool:
    """Ray casting. Los puntos sobre el borde pueden caer de cualquier lado."""
    x, y = p
    inside = False
    n = len(poly)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


# ---- línea virtual -----------------------------------------------------------------
class LineCounter:
    """Cuenta cruces de una línea por dirección.

    Para evitar dobles conteos de alguien parado sobre la línea, cada track
    tiene un "lado estable" que solo cambia cuando el punto se aleja más de
    `margin` px de la línea. Un cambio de lado estable dentro del largo del
    segmento es un cruce. Del lado negativo al positivo = entrada (o al revés
    si `inverted`).
    """

    def __init__(self, a: Point, b: Point, inverted: bool = False, margin: float = 6.0):
        self.a, self.b, self.inverted, self.margin = a, b, inverted, margin
        self._side: dict[int, int] = {}

    def update(self, track_id: int, p: Point) -> str | None:
        d = signed_distance(p, self.a, self.b)
        if abs(d) < self.margin:
            return None
        side = 1 if d > 0 else -1
        prev = self._side.get(track_id)
        self._side[track_id] = side
        if prev is None or prev == side:
            return None
        t = projection_t(p, self.a, self.b)
        if t < -0.05 or t > 1.05:  # cruzó la prolongación, no el segmento dibujado
            return None
        entering = (side == 1) != self.inverted
        return "in" if entering else "out"

    def forget(self, track_id: int) -> None:
        self._side.pop(track_id, None)


# ---- zonas ----------------------------------------------------------------------------
@dataclass
class ZoneVisit:
    track_id: int
    zone_id: str
    enter: float
    exit: float

    @property
    def duration(self) -> float:
        return self.exit - self.enter


@dataclass
class ZoneStats:
    dwell_by_track: dict[int, float] = field(default_factory=dict)  # total de s por track

    def add(self, visit: ZoneVisit) -> None:
        self.dwell_by_track[visit.track_id] = self.dwell_by_track.get(visit.track_id, 0.0) + visit.duration

    def summary(self, stop_seconds: float) -> dict:
        dwell = list(self.dwell_by_track.values())
        stopped = sum(1 for d in dwell if d >= stop_seconds)
        return {
            "passed": len(dwell),
            "stopped": stopped,
            "stop_rate": round(stopped / len(dwell), 3) if dwell else 0.0,
            "avg_dwell": round(sum(dwell) / len(dwell), 1) if dwell else 0.0,
        }


class ZoneTracker:
    """Entradas y salidas de tracks a un polígono.

    Una salida se confirma recién cuando el track lleva `grace` s afuera; si
    vuelve antes, la visita continúa (evita cortar visitas por parpadeos del
    detector en el borde).
    """

    def __init__(self, zone_id: str, polygon: list[Point], grace: float = 1.0):
        self.zone_id, self.polygon, self.grace = zone_id, polygon, grace
        self._enter: dict[int, float] = {}       # dentro desde
        self._last_inside: dict[int, float] = {}  # último instante visto dentro
        self._outside_since: dict[int, float] = {}

    def inside_ids(self) -> list[int]:
        return [t for t in self._enter if t not in self._outside_since]

    def update(self, track_id: int, p: Point, t: float) -> ZoneVisit | None:
        if point_in_polygon(p, self.polygon):
            self._outside_since.pop(track_id, None)
            self._enter.setdefault(track_id, t)
            self._last_inside[track_id] = t
            return None
        if track_id not in self._enter:
            return None
        since = self._outside_since.setdefault(track_id, t)
        if t - since >= self.grace:
            return self._close(track_id)
        return None

    def current_duration(self, track_id: int, t: float) -> float:
        """Segundos de la visita en curso (0 si no está dentro)."""
        if track_id in self._enter and track_id not in self._outside_since:
            return max(0.0, t - self._enter[track_id])
        return 0.0

    def finish(self, track_id: int) -> ZoneVisit | None:
        """El track terminó (salió de cámara): cierra su visita si tenía una."""
        if track_id in self._enter:
            return self._close(track_id)
        return None

    def _close(self, track_id: int) -> ZoneVisit:
        enter = self._enter.pop(track_id)
        exit_ = self._last_inside.pop(track_id, enter)
        self._outside_since.pop(track_id, None)
        return ZoneVisit(track_id, self.zone_id, enter, exit_)


# ---- permanencia general ------------------------------------------------------------
def dwell_summary(durations: list[float]) -> dict:
    buckets = {label: 0 for label, _, _ in DWELL_BUCKETS}
    for d in durations:
        for label, lo, hi in DWELL_BUCKETS:
            if lo <= d < hi:
                buckets[label] += 1
                break
    return {
        "avg": round(sum(durations) / len(durations), 1) if durations else 0.0,
        "median": round(statistics.median(durations), 1) if durations else 0.0,
        "buckets": buckets,
    }
