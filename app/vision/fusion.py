"""Fusión entre cámaras: un ID GLOBAL por persona.

Cada cámara sigue a las personas con su propio ByteTrack (IDs locales). Aquí
se decide cuándo un track local nuevo es una persona que ya conocemos:

  1. Superposición: otra cámara la está viendo AHORA en el mismo lugar del
     plano (< `same_place_m`). Requiere cámaras calibradas.
  2. Traspaso entre cámaras: un global que se perdió hace poco en otra cámara,
     a una distancia alcanzable caminando (≤ velocidad máx. × tiempo + holgura),
     con apariencia parecida.
  3. Re-entrada en la misma cámara: salió y volvió en menos de `reentry_s`.
     Si reaparece casi en el mismo sitio en menos de `quick_reentry_s` (el detector la perdió un
     momento: se giró, se tapó la cara, movió la cámara), basta un parecido de ropa menor.

La apariencia es un histograma de color HSV de la mitad superior e inferior
del cuerpo (ropa), no la cara. Vive solo en memoria y se descarta cuando el
global termina. Si dos candidatos quedan casi empatados no se une a ninguno:
es preferible contar de más que mezclar a dos personas.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

from app.vision.counting import LineCounter, ZoneStats, ZoneTracker, dwell_summary, point_in_polygon, signed_distance
from app.vision.colors import hex_for_id
from app.vision.heatmap import decay_factor

HIST_BINS = (16, 4)  # tono × saturación


# ---- apariencia ------------------------------------------------------------------------
def appearance_descriptor(frame: np.ndarray, box) -> np.ndarray | None:
    """Histogramas HSV normalizados (torso y piernas) concatenados. None si el recuadro es muy chico."""
    x1, y1, x2, y2 = (int(v) for v in box)
    h, w = frame.shape[:2]
    x1, x2 = max(0, x1), min(w, x2)
    y1, y2 = max(0, y1), min(h, y2)
    bh, bw = y2 - y1, x2 - x1
    if bh < 40 or bw < 16:
        return None
    # recorte central horizontal para evitar fondo; se salta la cabeza (15 % superior)
    cx1, cx2 = x1 + bw // 6, x2 - bw // 6
    parts = [(y1 + int(bh * 0.15), y1 + int(bh * 0.55)), (y1 + int(bh * 0.55), y1 + int(bh * 0.95))]
    out = []
    for a, b in parts:
        roi = frame[a:b, cx1:cx2]
        if roi.size == 0:
            return None
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        # se ignoran píxeles casi negros o sin color (sombras), que no aportan identidad
        mask = cv2.inRange(hsv, (0, 30, 30), (180, 255, 255))
        hist = cv2.calcHist([hsv], [0, 1], mask, list(HIST_BINS), [0, 180, 0, 256]).flatten()
        if hist.sum() < 20:  # ropa negra/blanca/gris: usar brillo en vez de tono
            hist = cv2.calcHist([hsv], [2], None, [HIST_BINS[0] * HIST_BINS[1]], [0, 256]).flatten()
        out.append(hist / (hist.sum() or 1.0))
    return np.concatenate(out).astype(np.float32)


def appearance_similarity(a: np.ndarray | None, b: np.ndarray | None) -> float | None:
    """1 = idénticos, 0 = sin nada en común (1 − distancia de Bhattacharyya por parte)."""
    if a is None or b is None or a.shape != b.shape:
        return None
    half = len(a) // 2
    sims = []
    for sa, sb in ((a[:half], b[:half]), (a[half:], b[half:])):
        bc = float(np.sum(np.sqrt(np.clip(sa, 0, None) * np.clip(sb, 0, None))))  # coeficiente de Bhattacharyya
        sims.append(max(0.0, min(1.0, bc)))
    return float(np.mean(sims))


# ---- tracker global ----------------------------------------------------------------------
@dataclass
class GlobalTrack:
    gid: int
    first_seen: float
    last_seen: float
    last_cam: str
    pos: tuple[float, float] | None = None              # último punto en el plano (m)
    img_pos: dict = field(default_factory=dict)          # cámara -> (u, v) normalizado
    appearance: np.ndarray | None = None
    cameras: set = field(default_factory=set)
    confirmed: bool = False
    announced: bool = False  # ya se emitió global_start
    buyer: bool = False      # pasó >= buyer_seconds en zonas de cajas
    checkout_s: float = 0.0  # segundos en cajas de visitas ya cerradas
    stopped: bool = False    # se detuvo (>= stop_seconds) en alguna área
    staff: bool = False      # personal / trabajador: no cuenta en las estadísticas de clientes
    staff_reason: str | None = None
    staff_zone_s: float = 0.0                                   # segundos en zonas de personal (visitas cerradas)
    checkout_by_area: dict = field(default_factory=dict)       # caja (área) -> segundos en su zona de cliente
    checkout_union_s: float = 0.0   # segundos dentro de AL MENOS una zona de caja (sin duplicar si se superponen)
    caja_last: float | None = None  # última vez que se lo vio dentro de alguna zona de caja

    @property
    def seconds(self) -> float:
        return self.last_seen - self.first_seen


@dataclass
class Observation:
    camera_id: str
    track_id: int
    plan_pos: tuple[float, float] | None   # pies proyectados al plano (m), None sin calibración
    img_pos: tuple[float, float]           # pies en la imagen, normalizado 0–1
    appearance: np.ndarray | None = None


class GlobalTracker:
    def __init__(self, same_place_m: float = 0.9, handoff_s: float = 8.0, reentry_s: float = 20.0,
                 max_speed: float = 2.0, slack_m: float = 1.0, min_app_sim: float = 0.6,
                 min_app_sim_no_space: float = 0.72, ambiguity_margin: float = 0.06,
                 live_after_s: float = 1.0, min_confirm_s: float = 1.0,
                 quick_reentry_s: float = 5.0, min_app_sim_quick: float = 0.5):
        self.same_place_m, self.handoff_s, self.reentry_s = same_place_m, handoff_s, reentry_s
        self.max_speed, self.slack_m = max_speed, slack_m
        self.min_app_sim, self.min_app_sim_no_space = min_app_sim, min_app_sim_no_space
        self.ambiguity_margin, self.live_after_s, self.min_confirm_s = ambiguity_margin, live_after_s, min_confirm_s
        self.quick_reentry_s, self.min_app_sim_quick = quick_reentry_s, min_app_sim_quick
        self.globals: dict[int, GlobalTrack] = {}
        self.links: dict[tuple[str, int], int] = {}        # (cámara, track local) -> gid
        self.link_seen: dict[tuple[str, int], float] = {}  # última vez que se vio ese track local
        self._next = 1
        self.last_reason: dict[tuple[str, int], str] = {}

    def live_links(self, gid: int, t: float) -> list[tuple[str, int]]:
        return [k for k, g in self.links.items() if g == gid and t - self.link_seen.get(k, -1e9) <= self.live_after_s]

    def is_live(self, gid: int, t: float) -> bool:
        return bool(self.live_links(gid, t))

    def _candidates(self, obs: Observation, t: float) -> list[tuple[float, int, str]]:
        out = []
        for g in self.globals.values():
            live = self.live_links(g.gid, t)
            if any(cam == obs.camera_id for cam, _ in live):
                continue  # la misma cámara ya la ve con otro track: son personas distintas
            app = appearance_similarity(obs.appearance, g.appearance)
            if live:
                # 1) superposición: otra cámara la ve ahora mismo en el mismo lugar
                if obs.plan_pos is None or g.pos is None:
                    continue
                d = math.dist(obs.plan_pos, g.pos)
                if d > self.same_place_m:
                    continue
                if app is not None and app < self.min_app_sim * 0.8:
                    continue
                spatial = 1 - d / self.same_place_m
                score = 0.7 * spatial + 0.3 * (app if app is not None else 0.5)
                out.append((score + 0.2, g.gid, "superposición"))
                continue
            dt = t - g.last_seen
            same_cam = g.last_cam == obs.camera_id
            window = self.reentry_s if same_cam else self.handoff_s
            if dt < 0 or dt > window:
                continue
            spatial = None
            if obs.plan_pos is not None and g.pos is not None:
                reach = self.max_speed * dt + self.slack_m
                d = math.dist(obs.plan_pos, g.pos)
                if d > reach:
                    continue  # físicamente imposible llegar ahí en ese tiempo
                spatial = 1 - d / reach
            elif same_cam and obs.camera_id in g.img_pos:
                d = math.dist(obs.img_pos, g.img_pos[obs.camera_id])
                spatial = max(0.0, 1 - d / 0.6)
            quick = same_cam and spatial is not None and spatial > 0.75 and dt <= self.quick_reentry_s
            if app is None:
                # sin apariencia solo se acepta una re-entrada inmediata y muy cercana
                if quick:
                    out.append((spatial * 0.8, g.gid, "re-entrada" if same_cam else "traspaso"))
                continue
            needed = self.min_app_sim if (spatial is not None and obs.plan_pos is not None) else self.min_app_sim_no_space
            if quick:
                needed = min(needed, self.min_app_sim_quick)
            if app < needed:
                continue
            sp = spatial if spatial is not None else 0.3
            score = 0.45 * sp + 0.55 * app - 0.15 * (dt / window)
            out.append((score, g.gid, "re-entrada" if same_cam else "traspaso"))
        return sorted(out, reverse=True)

    def observe(self, obs: Observation, t: float) -> tuple[int, str | None]:
        """Devuelve (gid, motivo de la unión o None si ya estaba unido)."""
        key = (obs.camera_id, obs.track_id)
        reason = None
        gid = self.links.get(key)
        if gid is None or gid not in self.globals:
            cands = self._candidates(obs, t)
            ambiguous = len(cands) > 1 and cands[0][0] - cands[1][0] < self.ambiguity_margin
            if cands and not ambiguous:
                _, gid, reason = cands[0]
            else:
                gid, reason = self._next, "nueva"
                self._next += 1
                self.globals[gid] = GlobalTrack(gid, t, t, obs.camera_id)
            self.links[key] = gid
            self.last_reason[key] = reason
        g = self.globals[gid]
        g.last_seen = t
        g.last_cam = obs.camera_id
        g.cameras.add(obs.camera_id)
        if obs.plan_pos is not None:
            g.pos = obs.plan_pos
        g.img_pos[obs.camera_id] = obs.img_pos
        if obs.appearance is not None:
            g.appearance = obs.appearance if g.appearance is None else (0.8 * g.appearance + 0.2 * obs.appearance)
        if not g.confirmed and g.seconds >= self.min_confirm_s:
            g.confirmed = True
        self.link_seen[key] = t
        return gid, reason

    def expire(self, t: float) -> list[GlobalTrack]:
        """Termina los globales sin tracks vivos más allá de las ventanas de re-entrada y traspaso."""
        horizon = max(self.reentry_s, self.handoff_s)
        ended = [g for g in self.globals.values() if not self.is_live(g.gid, t) and t - g.last_seen > horizon]
        for g in ended:
            del self.globals[g.gid]
        if ended:
            gone = {g.gid for g in ended}
            for k in [k for k, v in self.links.items() if v in gone]:
                self.links.pop(k, None)
                self.link_seen.pop(k, None)
                self.last_reason.pop(k, None)
        return ended

    def finish_all(self) -> list[GlobalTrack]:
        ended = list(self.globals.values())
        self.globals.clear()
        self.links.clear()
        self.link_seen.clear()
        return ended


# ---- métricas sobre el plano ------------------------------------------------------------
class PlanHeatmap:
    """Grilla en metros (celdas de `cell_m`) con modo en vivo (decae) y pendiente para SQLite."""

    def __init__(self, width_m: float, depth_m: float, cell_m: float = 0.25, half_life: float = 30.0):
        self.cell = cell_m
        self.half_life = half_life
        self.resize(width_m, depth_m)

    def resize(self, width_m: float, depth_m: float) -> None:
        self.width, self.depth = width_m, depth_m
        self.rows = max(1, math.ceil(depth_m / self.cell))
        self.cols = max(1, math.ceil(width_m / self.cell))
        self.live = np.zeros((self.rows, self.cols), np.float32)
        self.accum = np.zeros_like(self.live)
        self.pending = np.zeros_like(self.live)
        self._last_t = None

    def cell_for(self, x: float, y: float) -> tuple[int, int] | None:
        if not (0 <= x < self.width and 0 <= y < self.depth):
            return None
        return min(self.rows - 1, int(y / self.cell)), min(self.cols - 1, int(x / self.cell))

    def add(self, points, t: float) -> None:
        if self._last_t is not None:
            self.live *= decay_factor(t - self._last_t, self.half_life)
        self._last_t = t
        for x, y in points:
            c = self.cell_for(x, y)
            if c:
                self.live[c] += 1
                self.accum[c] += 1
                self.pending[c] += 1

    def take_pending(self) -> np.ndarray:
        out = self.pending.copy()
        self.pending[:] = 0
        return out


class StoreFusion:
    """Orquesta el ID global, las áreas del plano, los recorridos y el calor del plano.

    Lo llaman los hilos de inferencia de todas las cámaras (con un lock).
    """

    HEAT_EVERY_S = 0.2  # una muestra de calor por persona cada 0.2 s, sin importar cuántas cámaras la vean

    def __init__(self, tracker: GlobalTracker | None = None, plan: dict | None = None):
        import threading
        self._lock = threading.RLock()
        self.tracker = tracker or GlobalTracker()
        self.listeners: list = []
        self.areas: dict[str, dict] = {}
        self._zones: dict[str, ZoneTracker] = {}
        self.area_stats: dict[str, ZoneStats] = {}
        self.transitions: dict[tuple[str, str], int] = {}
        self._last_area: dict[int, str] = {}
        self._track_areas: dict[int, list[str]] = {}
        self._last_heat: dict[int, float] = {}
        self.heatmap = PlanHeatmap(20, 12)
        self.durations: list[float] = []
        self.unique = 0
        self.people_now = 0
        self.peak, self.peak_at = 0, None
        self._occ_sum = self._occ_n = self._occ_max = 0
        self.links_by_reason: dict[str, int] = {}
        self.stop_seconds = 10.0
        self.buyer_seconds = 20.0   # en zonas de cajas para contar como "pasó por caja"
        self.buyers = 0
        # personal: quien supera staff_hours en el sistema o pasa staff_zone_seconds en una zona de personal
        self.staff_hours = 4.0
        self.staff_zone_seconds = 15.0
        self.staff_count = 0
        self.doors: dict[str, dict] = {}            # id -> {counter, role, name}
        self.door_counts: dict[str, dict] = {}      # id -> {"in": n, "out": n}
        self._pending_doors: dict[int, list] = {}   # cruces de tracks aún no confirmados
        if plan:
            self.set_plan(plan)

    def _emit(self, kind: str, data: dict) -> None:
        for fn in self.listeners:
            fn(kind, data)

    def set_plan(self, plan: dict) -> None:
        with self._lock:
            if (plan["width"], plan["depth"]) != (self.heatmap.width, self.heatmap.depth):
                self.heatmap.resize(plan["width"], plan["depth"])
            areas = {a["id"]: a for a in plan.get("elements", []) if a.get("type") == "area"}
            for aid, a in areas.items():
                pts = [tuple(p) for p in a["points"]]
                old = self._zones.get(aid)
                if old is None or old.polygon != pts:
                    self._zones[aid] = ZoneTracker(aid, pts, grace=1.0)
                self.area_stats.setdefault(aid, ZoneStats())
            for aid in [a for a in self._zones if a not in areas]:
                self._zones.pop(aid, None)
                self.area_stats.pop(aid, None)
            self.areas = areas
            self._set_doors(plan)

    def _set_doors(self, plan: dict) -> None:
        """Puertas del plano: el lado positivo de cada contador es el INTERIOR del local."""
        center = (plan["width"] / 2, plan["depth"] / 2)
        doors = {}
        for e in plan.get("elements", []):
            if e.get("type") != "door" or len(e.get("points", [])) < 2:
                continue
            a, b = tuple(e["points"][0]), tuple(e["points"][-1])
            interior_positive = signed_distance(center, a, b) > 0
            inverted = (not interior_positive) != bool(e.get("flip"))
            old = self.doors.get(e["id"])
            if old and old["a"] == a and old["b"] == b and old["inverted"] == inverted:
                counter = old["counter"]
            else:
                counter = LineCounter(a, b, inverted=inverted, margin=0.3)
            doors[e["id"]] = {"counter": counter, "a": a, "b": b, "inverted": inverted,
                              "role": e.get("role", "both"), "name": e.get("label") or "Puerta"}
            self.door_counts.setdefault(e["id"], {"in": 0, "out": 0})
        self.doors = doors

    def _door_event(self, gid: int, door_id: str, direction: str, t: float) -> None:
        self.door_counts.setdefault(door_id, {"in": 0, "out": 0})[direction] += 1
        self._emit("door_event", {"global_id": gid, "door_id": door_id, "door": self.doors[door_id]["name"],
                                  "direction": direction, "ts": t})

    def _ongoing(self, g: GlobalTrack, t: float, kind: str) -> dict[str, float]:
        return {aid: zt.current_duration(g.gid, t) for aid, zt in self._zones.items()
                if self.areas[aid].get("kind") == kind}

    def _checkout_seconds(self, g: GlobalTrack, t: float) -> float:
        return g.checkout_union_s

    def _accumulate_checkout(self, g: GlobalTrack, pos, camera_id: str, t: float) -> None:
        """Suma el tiempo dentro de cualquier zona de caja una sola vez, aunque las zonas se superpongan."""
        inside = False
        for aid, zt in self._zones.items():
            a = self.areas[aid]
            if a.get("kind") != "caja" or (a.get("cameras") and camera_id not in a["cameras"]):
                continue
            if point_in_polygon(pos, zt.polygon):
                inside = True
                break
        if inside:
            if g.caja_last is not None and 0 < t - g.caja_last <= 1.5:
                g.checkout_union_s += t - g.caja_last
            if g.caja_last is None or t > g.caja_last:
                g.caja_last = t
        elif g.caja_last is not None and t - g.caja_last > 1.0:
            g.caja_last = None  # salió (con 1 s de tolerancia a parpadeos del detector)

    def _checkout_area(self, g: GlobalTrack, t: float) -> str | None:
        """La caja (zona de cliente) donde más tiempo pasó: es la caja a la que se asigna."""
        per = dict(g.checkout_by_area)
        for aid, s in self._ongoing(g, t, "caja").items():
            per[aid] = per.get(aid, 0.0) + s
        per = {k: v for k, v in per.items() if v > 0}
        return max(per, key=per.get) if per else None

    def _check_staff(self, g: GlobalTrack, t: float) -> None:
        if g.staff or not g.confirmed:
            return
        reason = None
        if self.staff_hours > 0 and g.seconds >= self.staff_hours * 3600:
            reason = f"más de {self.staff_hours:g} h en la tienda"
        elif g.staff_zone_s + sum(self._ongoing(g, t, "personal").values()) >= self.staff_zone_seconds:
            reason = "estuvo en una zona de personal"
        if reason is None:
            return
        g.staff, g.staff_reason = True, reason
        self.staff_count += 1
        if g.announced:
            self.unique -= 1        # deja de contar como cliente
        if g.buyer:
            g.buyer = False
            self.buyers -= 1
        self._emit("global_staff", {"global_id": g.gid, "ts": t, "reason": reason})

    def _check_buyer(self, g: GlobalTrack, t: float) -> None:
        if g.buyer or g.staff or not g.confirmed:
            return
        secs = self._checkout_seconds(g, t)
        if secs >= self.buyer_seconds:
            g.buyer = True
            self.buyers += 1
            aid = self._checkout_area(g, t)
            self._emit("global_buyer", {"global_id": g.gid, "ts": t, "checkout_seconds": secs,
                                        "checkout_area_id": aid, "checkout_area": self._area_name(aid) if aid else None})

    def _area_name(self, aid: str) -> str:
        return self.areas.get(aid, {}).get("name", aid)

    def _record_visit(self, v, g: GlobalTrack | None = None) -> None:
        if v is None or v.duration <= 0:
            return
        # al terminar un global ya no está en el tracker: se pasa explícito para no perder su última visita
        g = g or self.tracker.globals.get(v.track_id)
        if g is not None and not g.confirmed:
            return
        if g is None or not g.staff:
            self.area_stats.setdefault(v.zone_id, ZoneStats()).add(v)
        if g is not None:
            kind = self.areas.get(v.zone_id, {}).get("kind")
            if kind == "caja":
                g.checkout_s += v.duration
                g.checkout_by_area[v.zone_id] = g.checkout_by_area.get(v.zone_id, 0.0) + v.duration
            elif kind == "personal":
                g.staff_zone_s += v.duration
            if v.duration >= self.stop_seconds:
                g.stopped = True
        self._emit("area_visit", {"global_id": v.track_id, "area_id": v.zone_id, "area": self._area_name(v.zone_id),
                                  "enter": v.enter, "exit": v.exit, "duration": v.duration})

    def observe_frame(self, camera_id: str, observations: list[Observation], t: float) -> dict[int, int]:
        """Procesa las observaciones de una cámara. Devuelve {track local: gid}."""
        out = {}
        with self._lock:
            for obs in observations:
                gid, reason = self.tracker.observe(obs, t)
                out[obs.track_id] = gid
                g = self.tracker.globals[gid]
                if reason:
                    self.links_by_reason[reason] = self.links_by_reason.get(reason, 0) + 1
                    self._emit("track_link", {"camera_id": camera_id, "track_id": obs.track_id,
                                              "global_id": gid, "reason": reason, "ts": t})
                if g.confirmed and not g.announced:
                    g.announced = True
                    self.unique += 1
                    self._emit("global_start", {"global_id": gid, "first_seen": g.first_seen, "color": hex_for_id(gid)})
                    for door_id, d, td in self._pending_doors.pop(gid, []):
                        self._door_event(gid, door_id, d, td)
                if obs.plan_pos is None:
                    continue
                for door_id, door in self.doors.items():
                    d = door["counter"].update(gid, obs.plan_pos)
                    if not d or (door["role"] == "entry" and d != "in") or (door["role"] == "exit" and d != "out"):
                        continue
                    if g.staff:
                        continue  # el personal no suma entradas ni salidas de clientes
                    if g.confirmed:
                        self._door_event(gid, door_id, d, t)
                    else:  # se cuenta cuando la persona dure lo mínimo (filtra falsos positivos)
                        self._pending_doors.setdefault(gid, []).append((door_id, d, t))
                for aid, zt in self._zones.items():
                    cams = self.areas[aid].get("cameras") or []
                    if cams and camera_id not in cams:
                        continue  # el área solo se mide con las cámaras asignadas
                    was_inside = gid in zt.inside_ids()
                    self._record_visit(zt.update(gid, obs.plan_pos, t))
                    if not was_inside and gid in zt.inside_ids():
                        self._entered_area(gid, aid, t)
                if not g.stopped and any(zt.current_duration(gid, t) >= self.stop_seconds for zt in self._zones.values()):
                    g.stopped = True
                self._accumulate_checkout(g, obs.plan_pos, camera_id, t)
                self._check_staff(g, t)
                self._check_buyer(g, t)
                if g.confirmed and not g.staff and t - self._last_heat.get(gid, 0) >= self.HEAT_EVERY_S:
                    self._last_heat[gid] = t
                    self.heatmap.add([obs.plan_pos], t)
            self._refresh(t)
        return out

    def _entered_area(self, gid: int, aid: str, t: float) -> None:
        prev = self._last_area.get(gid)
        self._track_areas.setdefault(gid, [])
        if not self._track_areas[gid] or self._track_areas[gid][-1] != aid:
            self._track_areas[gid].append(aid)
        if prev and prev != aid:
            self.transitions[(prev, aid)] = self.transitions.get((prev, aid), 0) + 1
            self._emit("area_transition", {"global_id": gid, "from_id": prev, "from": self._area_name(prev),
                                           "to_id": aid, "to": self._area_name(aid), "ts": t})
        self._last_area[gid] = aid

    def _refresh(self, t: float) -> None:
        for g in self.tracker.expire(t):
            self._end_global(g)
        for g in self.tracker.globals.values():
            self._check_staff(g, t)  # la regla de horas también corre aunque nadie se mueva
        now = sum(1 for g in self.tracker.globals.values()
                  if g.confirmed and not g.staff and self.tracker.is_live(g.gid, t))
        self.people_now = now
        self._occ_sum += now
        self._occ_n += 1
        self._occ_max = max(self._occ_max, now)
        if now > self.peak:
            self.peak, self.peak_at = now, t

    def _end_global(self, g: GlobalTrack) -> None:
        for zt in self._zones.values():
            self._record_visit(zt.finish(g.gid), g)
        areas = [self._area_name(a) for a in self._track_areas.pop(g.gid, [])]
        self._last_area.pop(g.gid, None)
        self._last_heat.pop(g.gid, None)
        self._pending_doors.pop(g.gid, None)
        for door in self.doors.values():
            door["counter"].forget(g.gid)
        if g.confirmed:
            self._check_staff(g, g.last_seen)
            self._check_buyer(g, g.last_seen)
            if not g.staff:
                self.durations.append(g.seconds)
            aid = self._checkout_area(g, g.last_seen)
            self._emit("global_end", {"global_id": g.gid, "first_seen": g.first_seen, "last_seen": g.last_seen,
                                      "duration": g.seconds, "cameras": sorted(g.cameras), "areas": areas,
                                      "buyer": g.buyer, "checkout_seconds": round(g.checkout_union_s, 1),
                                      "stopped": g.stopped, "staff": g.staff, "staff_reason": g.staff_reason,
                                      "checkout_area_id": aid, "checkout_area": self._area_name(aid) if aid else None})

    def tick(self, t: float) -> None:
        """Llamado periódicamente aunque ninguna cámara vea a nadie (para cerrar globales)."""
        with self._lock:
            self._refresh(t)

    def finish_all(self, t: float) -> None:
        with self._lock:
            for g in self.tracker.finish_all():
                self._end_global(g)

    def take_occupancy_window(self) -> tuple[int, int, float]:
        with self._lock:
            n = self._occ_n
            out = (self.people_now, max(self._occ_max, self.people_now),
                   round(self._occ_sum / n, 2) if n else float(self.people_now))
            self._occ_sum = self._occ_n = self._occ_max = 0
            return out

    def reset_heatmap(self) -> None:
        """Reinicia lo que se ve en vivo y acumulado; lo pendiente de guardar es histórico y se conserva."""
        with self._lock:
            self.heatmap.live[:] = 0
            self.heatmap.accum[:] = 0

    def peek_plan_pending(self) -> np.ndarray:
        with self._lock:
            return self.heatmap.pending.copy()

    def take_plan_heatmap(self) -> np.ndarray:
        with self._lock:
            return self.heatmap.take_pending()

    def plan_heatmap(self, mode: str = "live") -> np.ndarray:
        with self._lock:
            return (self.heatmap.live if mode == "live" else self.heatmap.accum).copy()

    def global_info(self, gid: int) -> GlobalTrack | None:
        with self._lock:
            return self.tracker.globals.get(gid)

    def snapshot(self, t: float) -> dict:
        with self._lock:
            people = []
            for g in self.tracker.globals.values():
                if not self.tracker.is_live(g.gid, t):
                    continue
                people.append({"gid": g.gid, "color": hex_for_id(g.gid), "seconds": round(g.seconds, 1),
                               "x": None if g.pos is None else round(g.pos[0], 2),
                               "y": None if g.pos is None else round(g.pos[1], 2),
                               "cameras": sorted(g.cameras), "confirmed": g.confirmed,
                               "buyer": g.buyer, "checkout_s": round(self._checkout_seconds(g, t), 1),
                               "stopped": g.stopped, "staff": g.staff, "staff_reason": g.staff_reason})
            areas = []
            for aid, a in self.areas.items():
                inside = [gid for gid in self._zones[aid].inside_ids()
                          if gid in self.tracker.globals and self.tracker.globals[gid].confirmed
                          and not self.tracker.globals[gid].staff]
                areas.append({"id": aid, "name": a["name"], "kind": a.get("kind", "pasillo"), "inside": len(inside),
                              "checkout_id": a.get("checkout_id"),
                              **self.area_stats.get(aid, ZoneStats()).summary(self.stop_seconds)})
            staff_now = sum(1 for g in self.tracker.globals.values() if g.staff and self.tracker.is_live(g.gid, t))
            return {
                "people": people,
                "people_now": self.people_now,
                "unique_session": self.unique,
                "peak": self.peak,
                "peak_at": self.peak_at,
                "dwell": dwell_summary(self.durations),
                "areas": areas,
                "transitions": [{"from": self._area_name(a), "to": self._area_name(b), "count": n}
                                for (a, b), n in sorted(self.transitions.items(), key=lambda kv: -kv[1])[:10]],
                "links": dict(self.links_by_reason),
                "buyers_session": self.buyers,
                "buyer_seconds": self.buyer_seconds,
                "has_checkout": any(a.get("kind") == "caja" for a in self.areas.values()),
                "doors": [{"id": did, "name": d["name"], "role": d["role"], **self.door_counts.get(did, {"in": 0, "out": 0})}
                          for did, d in self.doors.items()],
                "entries": sum(c["in"] for did, c in self.door_counts.items() if did in self.doors),
                "exits": sum(c["out"] for did, c in self.door_counts.items() if did in self.doors),
                "staff_now": staff_now,
                "staff_session": self.staff_count,
                "staff_hours": self.staff_hours,
            }

