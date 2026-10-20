"""Procesador de métricas: une tracks con línea, zonas, permanencia y mapa de calor,
dibuja sus overlays y emite eventos para la base de datos (fase 3)."""
from __future__ import annotations

import json
import threading
import time
from typing import Callable

import cv2
import numpy as np

from app.vision.colors import hex_for_id
from app.vision.counting import LineCounter, ZoneStats, ZoneTracker, dwell_summary
from app.vision.heatmap import Heatmap, render
from app.vision.textdraw import label

BRASS = (38, 165, 224)
INK = (43, 32, 23)
GREEN = (100, 122, 29)
ALERT = (45, 65, 194)
ZONE_COLORS = [  # BGR, distintos entre sí y apagados frente a los colores de personas
    (38, 165, 224), (100, 122, 29), (160, 110, 40), (120, 70, 150), (60, 120, 200), (130, 130, 60),
]

Listener = Callable[[str, dict], None]


def zone_color(index: int):
    return ZONE_COLORS[index % len(ZONE_COLORS)]


class MetricsProcessor:
    def __init__(self, frame_w: int, frame_h: int, grid_w: int = 64, half_life: float = 30.0):
        self._lock = threading.RLock()
        self.frame_w, self.frame_h = frame_w, frame_h
        self.heatmap = Heatmap(frame_w, frame_h, grid_w, half_life)
        self.listeners: list[Listener] = []
        self.session_start = time.time()
        self._line: LineCounter | None = None
        self._line_key = None
        self._zones: dict[str, ZoneTracker] = {}
        self._zone_meta: dict[str, dict] = {}
        self._zones_key = None
        self.reset_counters()

    def reset_counters(self) -> None:
        with self._lock:
            self.entries = 0
            self.exits = 0
            self.unique = 0
            self.peak = 0
            self.peak_at: float | None = None
            self.people_now = 0
            self.durations: list[float] = []
            self.zone_stats: dict[str, ZoneStats] = {zid: ZoneStats() for zid in self._zones}
            self._known: dict[int, tuple[float, float]] = {}   # tid -> (first_seen, last_seen)
            self._confirmed: set[int] = set()
            self._pending_line: dict[int, list[tuple[str, float]]] = {}
            self._track_zones: dict[int, set[str]] = {}
            self._occ_sum, self._occ_n, self._occ_max = 0, 0, 0

    def take_occupancy_window(self) -> tuple[int, int, float]:
        """(personas ahora, máximo, promedio) desde la última llamada."""
        with self._lock:
            n = self._occ_n
            out = (self.people_now, max(self._occ_max, self.people_now),
                   round(self._occ_sum / n, 2) if n else float(self.people_now))
            self._occ_sum, self._occ_n, self._occ_max = 0, 0, 0
            return out

    def _emit(self, kind: str, data: dict) -> None:
        for fn in self.listeners:
            fn(kind, data)

    # ---- sincronizar línea y zonas con la configuración -----------------------------
    def _px(self, p) -> tuple[float, float]:
        return p[0] * self.frame_w, p[1] * self.frame_h

    def _sync(self, cfg: dict) -> None:
        key = json.dumps(cfg["line"], sort_keys=True)
        if key != self._line_key:
            ln = cfg["line"]
            prev = json.loads(self._line_key) if self._line_key else None
            if ln:
                same_geometry = (self._line is not None and prev is not None
                                 and prev["a"] == ln["a"] and prev["b"] == ln["b"])
                if same_geometry:  # solo se invirtió: conservar el lado de cada track
                    self._line.inverted = bool(ln.get("inverted"))
                else:
                    self._line = LineCounter(self._px(ln["a"]), self._px(ln["b"]), bool(ln.get("inverted")))
            else:
                self._line = None
            self._line_key = key
        zkey = json.dumps(cfg["zones"], sort_keys=True)
        if zkey != self._zones_key:
            new: dict[str, ZoneTracker] = {}
            meta: dict[str, dict] = {}
            for i, z in enumerate(cfg["zones"]):
                pts = [self._px(p) for p in z["points"]]
                old = self._zones.get(z["id"])
                if old is not None and old.polygon == pts:
                    new[z["id"]] = old
                else:
                    new[z["id"]] = ZoneTracker(z["id"], pts)
                meta[z["id"]] = {"name": z["name"], "index": i, "points": pts}
                self.zone_stats.setdefault(z["id"], ZoneStats())
            for zid in list(self.zone_stats):
                if zid not in new:
                    del self.zone_stats[zid]
            self._zones, self._zone_meta, self._zones_key = new, meta, zkey

    def set_frame_size(self, w: int, h: int, grid_w: int) -> None:
        with self._lock:
            if (w, h, grid_w) != (self.frame_w, self.frame_h, self.heatmap.gw):
                self.frame_w, self.frame_h = w, h
                self.heatmap.resize(w, h, grid_w)
                self._line_key = self._zones_key = None  # recalcular píxeles

    # ---- por cuadro ----------------------------------------------------------------
    def _record_visit(self, v) -> None:
        if v is None or v.track_id not in self._confirmed or v.duration <= 0:
            return
        self.zone_stats.setdefault(v.zone_id, ZoneStats()).add(v)
        name = self._zone_meta.get(v.zone_id, {}).get("name", v.zone_id)
        self._track_zones.setdefault(v.track_id, set()).add(name)
        self._emit("zone_visit", {"track_id": v.track_id, "zone_id": v.zone_id, "zone": name,
                                  "enter": v.enter, "exit": v.exit, "duration": v.duration})

    def _line_event(self, tid: int, direction: str, t: float) -> None:
        if direction == "in":
            self.entries += 1
        else:
            self.exits += 1
        self._emit("line_event", {"track_id": tid, "direction": direction, "ts": t})

    def _end_track(self, tid: int) -> None:
        first, last = self._known.pop(tid)
        for zt in self._zones.values():
            self._record_visit(zt.finish(tid))
        if self._line:
            self._line.forget(tid)
        self._pending_line.pop(tid, None)
        if tid in self._confirmed:
            self._confirmed.discard(tid)
            self.durations.append(last - first)
            self._emit("track_end", {"track_id": tid, "first_seen": first, "last_seen": last,
                                     "duration": last - first,
                                     "zones": sorted(self._track_zones.pop(tid, set()))})

    def finish_all(self) -> None:
        """Al cerrar la app: termina los tracks activos para que queden completos en la base."""
        with self._lock:
            for tid in list(self._known):
                self._end_track(tid)

    def update(self, pipe, cfg: dict, now: float) -> None:
        with self._lock:
            h, w = pipe.frame_shape
            self.set_frame_size(w, h, cfg["heatmap_grid_w"])
            self.heatmap.half_life = cfg["heatmap_half_life"]
            self._sync(cfg)
            min_s = cfg["min_track_seconds"]

            # tracks que terminaron (ByteTrack los descartó)
            for tid in [t for t in self._known if t not in pipe.tracks]:
                self._end_track(tid)

            heat_points = []
            people_now = 0
            for tid in pipe.visible_ids:
                st = pipe.tracks.get(tid)
                if st is None:
                    continue
                self._known[tid] = (st.first_seen, st.last_seen)
                if tid not in self._confirmed and st.seconds >= min_s:
                    self._confirmed.add(tid)
                    self.unique += 1
                    self._emit("track_start", {"track_id": tid, "first_seen": st.first_seen,
                                               "color": hex_for_id(tid)})
                    for direction, t in self._pending_line.pop(tid, []):
                        self._line_event(tid, direction, t)
                confirmed = tid in self._confirmed
                if self._line:
                    d = self._line.update(tid, st.point)
                    if d:
                        if confirmed:
                            self._line_event(tid, d, now)
                        else:  # se cuenta cuando el track llegue a durar min_track_seconds
                            self._pending_line.setdefault(tid, []).append((d, now))
                for zt in self._zones.values():
                    self._record_visit(zt.update(tid, st.point, now))
                if confirmed:
                    people_now += 1
                    heat_points.append(st.point)

            self.heatmap.add(heat_points, now)
            self.people_now = people_now
            self._occ_sum += people_now
            self._occ_n += 1
            self._occ_max = max(self._occ_max, people_now)
            if people_now > self.peak:
                self.peak, self.peak_at = people_now, now

    # ---- salida ------------------------------------------------------------------------
    def snapshot(self, cfg: dict) -> dict:
        with self._lock:
            zones = []
            for zid, meta in self._zone_meta.items():
                zt = self._zones[zid]
                inside = [t for t in zt.inside_ids() if t in self._confirmed]
                zones.append({"id": zid, "name": meta["name"], "inside": len(inside),
                              **self.zone_stats.get(zid, ZoneStats()).summary(cfg["stop_seconds"])})
            return {
                "people_now": self.people_now,
                "unique_session": self.unique,
                "peak": self.peak,
                "peak_at": self.peak_at,
                "entries": self.entries,
                "exits": self.exits,
                "dwell": dwell_summary(self.durations),
                "zones": zones,
                "session_start": self.session_start,
            }

    def track_zone_names(self, tid: int) -> list[str]:
        with self._lock:
            return sorted(self._track_zones.get(tid, set()))

    # ---- overlays ----------------------------------------------------------------------
    def draw_under(self, frame: np.ndarray, cfg: dict, now: float) -> None:
        if cfg["show_heatmap"]:
            frame[:] = render(frame, self.heatmap.grid(cfg["heatmap_mode"]))
        if cfg["show_zones"] and self._zone_meta:
            with self._lock:
                metas = list(self._zone_meta.items())
                inside = {zid: sum(1 for t in self._zones[zid].inside_ids() if t in self._confirmed)
                          for zid, _ in metas}
            layer = frame.copy()
            for zid, m in metas:
                pts = np.array(m["points"], np.int32)
                cv2.fillPoly(layer, [pts], zone_color(m["index"]))
            cv2.addWeighted(layer, 0.22, frame, 0.78, 0, dst=frame)
            for zid, m in metas:
                pts = np.array(m["points"], np.int32)
                color = zone_color(m["index"])
                cv2.polylines(frame, [pts], True, color, 2, cv2.LINE_AA)
                x, y = int(pts[:, 0].min()), int(pts[:, 1].min())
                label(frame, f"{m['name']} · {inside[zid]}", (x + 2, y + 24), color, (255, 255, 255), size=14)

    def draw_over(self, frame: np.ndarray, cfg: dict, now: float) -> None:
        line = self._line
        if not cfg["show_line"] or line is None:
            return
        a = tuple(int(v) for v in line.a)
        b = tuple(int(v) for v in line.b)
        cv2.line(frame, a, b, INK, 6, cv2.LINE_AA)
        cv2.line(frame, a, b, BRASS, 3, cv2.LINE_AA)
        for p in (a, b):
            cv2.circle(frame, p, 6, BRASS, -1, cv2.LINE_AA)
        # flecha hacia el lado de "entrada"
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = (dx * dx + dy * dy) ** 0.5 or 1.0
        nx, ny = -dy / length, dx / length  # normal del lado positivo
        if line.inverted:
            nx, ny = -nx, -ny
        tip = (int(mx + nx * 40), int(my + ny * 40))
        cv2.arrowedLine(frame, (int(mx), int(my)), tip, GREEN, 3, cv2.LINE_AA, tipLength=0.35)
        lx = tip[0] + 6 if nx >= 0 else tip[0] - 70
        label(frame, "Entrada", (lx, tip[1] + 10), GREEN, (255, 255, 255), size=13)
        label(frame, f"Entradas {self.entries} | Salidas {self.exits}",
              (min(a[0], b[0]), max(18, min(a[1], b[1]) - 8)), INK, (255, 255, 255), size=14)
