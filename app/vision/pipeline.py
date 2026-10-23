"""Hilo de inferencia: detector de personas en ONNX + ByteTrack + overlays."""
from __future__ import annotations

import logging
import threading
import time
import warnings
from collections import deque
from dataclasses import dataclass

import cv2
import numpy as np
import supervision as sv

from app.config import DATA_DIR, Settings
from app.vision.capture import CaptureThread
from app.vision.colors import color_for_id, hex_for_id, text_color_for
from app.vision.fusion import Observation, StoreFusion, appearance_descriptor
from app.vision.health import CameraHealth
from app.vision.metrics import MetricsProcessor
from app.vision.model import load_model
from app.vision.plan import plan_areas, plan_to_image, project_point
from app.vision.textdraw import label, put_text
from app.vision.trails import TrailStore

log = logging.getLogger("traffiqui.pipeline")
# supervision 0.30 avisa que ByteTrack pasará al paquete "trackers"; está fijado en requirements
warnings.filterwarnings("ignore", message=".*ByteTrack.*deprecated", category=FutureWarning)

INK = (43, 32, 23)        # #17202B en BGR
BRASS = (38, 165, 224)    # #E0A526
ALERT = (45, 65, 194)     # #C2412D
JPEG_QUALITY = 80
INITIAL_FPS_GUESS = 10.0
TRACK_LOW_CONF = 0.1    # piso de las detecciones que se pasan a ByteTrack para sostener tracks (su segunda pasada)


@dataclass
class TrackState:
    track_id: int
    first_seen: float
    last_seen: float
    point: tuple[float, float]
    box: tuple[int, int, int, int]

    @property
    def seconds(self) -> float:
        return self.last_seen - self.first_seen


def track_point(box, mode: str) -> tuple[float, float]:
    """Punto de seguimiento: centro del recuadro o base (pies)."""
    x1, y1, x2, y2 = box
    if mode == "bottom":
        return (x1 + x2) / 2.0, float(y2)
    return (x1 + x2) / 2.0, (y1 + y2) / 2.0


def draw_box(frame, box, color, thickness: int = 2) -> None:
    """Recuadro fino con esquinas reforzadas."""
    x1, y1, x2, y2 = box
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 1, cv2.LINE_AA)
    L = max(8, int(min(x2 - x1, y2 - y1) * 0.22))
    t = thickness + 2
    for (cx, cy, dx, dy) in ((x1, y1, 1, 1), (x2, y1, -1, 1), (x1, y2, 1, -1), (x2, y2, -1, -1)):
        cv2.line(frame, (cx, cy), (cx + dx * L, cy), color, t, cv2.LINE_AA)
        cv2.line(frame, (cx, cy), (cx, cy + dy * L), color, t, cv2.LINE_AA)


def blur_face_region(frame, box) -> None:
    """Desenfoca la mitad superior del recuadro (zona de la cara)."""
    x1, y1, x2, y2 = box
    y_mid = y1 + (y2 - y1) // 2
    roi = frame[max(0, y1):max(0, y_mid), max(0, x1):max(0, x2)]
    if roi.size == 0:
        return
    h, w = roi.shape[:2]
    small = cv2.resize(roi, (max(1, w // 14), max(1, h // 14)), interpolation=cv2.INTER_AREA)
    roi[:] = cv2.GaussianBlur(cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR), (0, 0), 3)


APPEARANCE_EVERY = 10  # cuadros entre actualizaciones del descriptor de ropa de cada track


class PipelineThread(threading.Thread):
    def __init__(self, capture: CaptureThread, settings: Settings, camera_id: str = "cam1",
                 primary: bool = True, fusion: StoreFusion | None = None):
        super().__init__(name=f"inferencia-{camera_id}", daemon=True)
        self.capture = capture
        self.settings = settings
        self.camera_id = camera_id
        # la cámara principal mantiene la línea y las zonas dibujadas sobre su imagen (fase 2);
        # las áreas del plano funcionan con todas las cámaras a través de la fusión
        self.primary = primary
        self.fusion = fusion
        self.health = CameraHealth(camera_id, DATA_DIR / "camaras")
        self._gid: dict[int, int] = {}       # track local -> ID global
        self._app_count: dict[int, int] = {}
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self.model = None
        self.backend = "cargando"
        self.error: str | None = None
        self.fps = 0.0
        self.infer_ms = 0.0
        self.tracks: dict[int, TrackState] = {}
        self.visible_ids: list[int] = []
        self.trails = TrailStore(settings.get("trail_seconds"), settings.get("trail_smooth"))
        self._tracker: sv.ByteTrack | None = None
        self._tracker_key = None
        self._id_offset = 0
        self._max_id = 0
        self._jpeg: bytes | None = None
        self._jpeg_id = 0
        self.frame_shape = (settings.get("height"), settings.get("width"))
        self.metrics = MetricsProcessor(settings.get("width"), settings.get("height"),
                                        settings.get("heatmap_grid_w"), settings.get("heatmap_half_life"))
        self.processors: list = [self.metrics]
        # cuadro de referencia para el mapa de calor: se busca uno sin personas
        self.on_reference = None  # callable(jpeg: bytes, w: int, h: int)
        self._reference_deadline: float | None = None
        self.reference_status = "pendiente"

    # ---- salida para el servidor -------------------------------------------------
    def latest_jpeg(self) -> tuple[int, bytes | None]:
        with self._lock:
            return self._jpeg_id, self._jpeg

    def active_people(self) -> list[dict]:
        with self._lock:
            ids = list(self.visible_ids)
        out = []
        for t in ids:
            st = self.tracks.get(t)
            if st is not None:
                gid = self._gid.get(t, t)
                g = self.fusion.global_info(gid) if self.fusion else None
                secs = g.seconds if g is not None else st.seconds
                out.append({"id": gid, "local_id": t, "color": hex_for_id(gid), "seconds": round(secs, 1),
                            "camera_id": self.camera_id})
        return out

    def camera_cfg(self, cfg: dict) -> dict:
        return next((c for c in cfg.get("cameras") or [] if c.get("id") == self.camera_id), {})

    def homography(self, cfg: dict):
        cal = self.camera_cfg(cfg).get("calibration") or {}
        return np.asarray(cal["H"], np.float64) if cal.get("H") else None

    def stop(self) -> None:
        self._stop_event.set()

    # ---- internos ----------------------------------------------------------------
    def _ensure_tracker(self, cfg: dict) -> sv.ByteTrack:
        fps = self.fps or INITIAL_FPS_GUESS
        key = (cfg["lost_track_seconds"], cfg["confidence"])
        if self._tracker is None or key != self._tracker_key:
            if self._tracker is not None:
                # los IDs de un tracker nuevo empiezan de nuevo: se desplazan para no repetir colores
                self._id_offset = self._max_id
            buffer_frames = max(5, int(round(cfg["lost_track_seconds"] * fps)))
            self._tracker = sv.ByteTrack(
                track_activation_threshold=cfg["confidence"],
                lost_track_buffer=buffer_frames,
                minimum_matching_threshold=0.8,
                frame_rate=30,  # con 30, lost_track_buffer queda expresado en cuadros procesados
            )
            self._tracker_key = key
            log.info("ByteTrack: buffer de %d cuadros (~%.1f s a %.1f FPS)",
                     buffer_frames, cfg["lost_track_seconds"], fps)
        elif self.fps:
            # el buffer va en cuadros: se ajusta a los FPS reales para que siga valiendo ~N segundos
            self._tracker.max_time_lost = max(5, int(round(cfg["lost_track_seconds"] * self.fps)))
        return self._tracker

    def _placeholder(self, cfg: dict, message: str, detail: str = "") -> np.ndarray:
        frame = np.full((cfg["height"], cfg["width"], 3), INK, np.uint8)
        put_text(frame, message, (24, frame.shape[0] // 2 - 24), BRASS, 26)
        if detail:
            put_text(frame, detail, (24, frame.shape[0] // 2 + 14), (220, 220, 220), 16)
        return frame

    def _publish(self, frame: np.ndarray) -> None:
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if ok:
            with self._lock:
                self._jpeg = buf.tobytes()
                self._jpeg_id += 1

    def _process(self, frame: np.ndarray, cfg: dict, now: float) -> np.ndarray:
        self.frame_shape = frame.shape[:2]
        t0 = time.perf_counter()
        # ByteTrack necesita también las detecciones dudosas (entre TRACK_LOW_CONF y la confianza mínima):
        # no crean personas nuevas, pero sostienen a alguien ya seguido cuando su puntuación baja un
        # momento (de cerca, de lado, movido, tapado a medias). Sin ellas, cada bajón era un ID nuevo.
        found = self.model.detect(frame, conf=min(TRACK_LOW_CONF, cfg["confidence"]))
        self.infer_ms = (time.perf_counter() - t0) * 1000
        raw = sv.Detections(xyxy=found.xyxy, confidence=found.confidence,
                            class_id=np.zeros(len(found.confidence), dtype=int))
        raw_boxes = [tuple(int(v) for v in b) for b, c in zip(raw.xyxy, raw.confidence) if c >= cfg["confidence"]]
        dets = self._ensure_tracker(cfg).update_with_detections(raw)

        visible = []
        for box, raw_id in zip(dets.xyxy, dets.tracker_id if dets.tracker_id is not None else []):
            tid = int(raw_id) + self._id_offset
            self._max_id = max(self._max_id, tid)
            b = tuple(int(v) for v in box)
            pt = track_point(b, cfg["track_point"])
            st = self.tracks.get(tid)
            if st is None:
                st = self.tracks[tid] = TrackState(tid, now, now, pt, b)
            st.last_seen, st.point, st.box = now, pt, b
            self.trails.add(tid, pt[0], pt[1], now)
            visible.append(tid)

        # olvidar tracks que ByteTrack ya descartó
        forget = cfg["lost_track_seconds"] + 1.0
        for tid in [t for t, s in self.tracks.items() if now - s.last_seen > forget]:
            del self.tracks[tid]

        self.trails.duration = cfg["trail_seconds"]
        self.trails.smooth_window = cfg["trail_smooth"]
        self.trails.prune(now)
        with self._lock:
            self.visible_ids = visible
        if self._reference_deadline is not None:
            self._try_reference(frame, raw_boxes, now)

        H = self.homography(cfg)
        if self.fusion is not None:
            self._observe(frame, visible, H, now)
        for tid in [t for t in self._gid if t not in self.tracks and t not in self.trails.active_ids()]:
            self._gid.pop(tid, None)
            self._app_count.pop(tid, None)

        for p in self.processors:
            p.update(self, cfg, now)

        # ---- overlays (el desenfoque va primero para que nada lo tape) ----
        out = frame.copy()
        if cfg["privacy_blur"]:
            for tid in visible:
                blur_face_region(out, self.tracks[tid].box)
        for p in self.processors:
            p.draw_under(out, cfg, now)
        if cfg.get("show_plan_areas") and H is not None and cfg.get("floorplan"):
            self._draw_plan_areas(out, H, cfg["floorplan"])
        if cfg["show_trails"]:
            self.trails.draw(out, now, lambda tid: color_for_id(self._gid.get(tid, tid)))
        if cfg["show_boxes"]:
            for tid in visible:
                st = self.tracks[tid]
                gid = self._gid.get(tid, tid)
                g = self.fusion.global_info(gid) if self.fusion else None
                secs = g.seconds if g is not None else st.seconds
                color = color_for_id(gid)
                draw_box(out, st.box, color)
                label(out, f"ID {gid} | {int(secs)} s", (st.box[0], st.box[1]),
                      color, text_color_for(color))
        for p in self.processors:
            p.draw_over(out, cfg, now)
        return out

    def _observe(self, frame: np.ndarray, visible: list[int], H, now: float) -> None:
        """Envía a la fusión los pies de cada persona (en el plano si hay calibración) y su ropa."""
        h, w = frame.shape[:2]
        obs = []
        for tid in visible:
            st = self.tracks[tid]
            fx, fy = track_point(st.box, "bottom")  # la homografía vale para puntos del piso
            u, v = fx / w, fy / h
            plan_pos = project_point(H, u, v) if H is not None else None
            n = self._app_count.get(tid, 0)
            app = appearance_descriptor(frame, st.box) if n % APPEARANCE_EVERY == 0 else None
            self._app_count[tid] = n + 1
            obs.append(Observation(self.camera_id, tid, plan_pos, (u, v), app))
        self._gid.update(self.fusion.observe_frame(self.camera_id, obs, now))

    def _draw_plan_areas(self, frame: np.ndarray, H, plan: dict) -> None:
        """Dibuja las áreas del plano sobre el video: sirve para comprobar la calibración."""
        h, w = frame.shape[:2]
        for a in plan_areas(plan):
            pts = plan_to_image(H, a["points"])
            if not np.isfinite(pts).all():
                continue  # parte del área queda detrás del horizonte de esta cámara
            px = (pts * [w, h]).astype(np.int32)
            if (px[:, 0].max() < 0 or px[:, 0].min() > w or px[:, 1].max() < 0 or px[:, 1].min() > h):
                continue
            cv2.polylines(frame, [px], True, (200, 200, 200), 1, cv2.LINE_AA)
            cx, cy = px.mean(axis=0).astype(int)
            if 0 <= cx < w and 0 <= cy < h:
                label(frame, a["name"], (int(cx) - 20, int(cy)), (60, 60, 60), (255, 255, 255), size=12, pad=3)

    def request_reference(self, wait_seconds: float = 10.0) -> None:
        """Toma el próximo cuadro sin personas; si en `wait_seconds` no hay ninguno,
        toma uno con las personas completamente desenfocadas."""
        self._reference_deadline = time.time() + wait_seconds
        self.reference_status = "buscando"

    def _try_reference(self, frame: np.ndarray, boxes: list, now: float) -> None:
        if boxes and now < self._reference_deadline:
            return
        ref = frame.copy()
        for x1, y1, x2, y2 in boxes:  # privacidad: nunca guardar a una persona reconocible
            pad = 16
            box = (max(0, x1 - pad), max(0, y1 - pad), x2 + pad, y2 + pad)
            roi = ref[box[1]:box[3], box[0]:box[2]]
            if roi.size:
                # queda solo una mancha de color: sin rasgos ni silueta reconocible
                h, w = roi.shape[:2]
                small = cv2.resize(roi, (max(1, w // 60), max(1, h // 60)), interpolation=cv2.INTER_AREA)
                roi[:] = cv2.GaussianBlur(cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR),
                                          (0, 0), max(8, min(w, h) / 6))
        self._reference_deadline = None
        self.reference_status = "con personas desenfocadas" if boxes else "sin personas"
        ok, buf = cv2.imencode(".jpg", ref, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if ok and self.on_reference:
            self.on_reference(buf.tobytes(), ref.shape[1], ref.shape[0])
        log.info("Cuadro de referencia tomado (%s).", self.reference_status)

    def _hud(self, frame: np.ndarray) -> None:
        txt = f"{self.fps:4.1f} FPS  |  {self.infer_ms:3.0f} ms  |  {self.backend}"
        label(frame, txt, (8, 30), INK, (255, 255, 255), size=14)

    def _load_detector(self, mode: str) -> None:
        try:
            self.model, self.backend = load_model(mode)
            self.error = None
        except Exception as exc:  # sin modelo no hay visión; el servidor sigue y muestra el error
            self.error = f"No se pudo cargar el modelo: {exc}"
            log.exception(self.error)
        self._detector_mode = mode

    def run(self) -> None:
        self._load_detector(self.settings.get("detector"))
        last_id = -1
        stamps: deque[float] = deque()
        while not self._stop_event.is_set():
            cfg = self.settings.snapshot()
            if cfg["detector"] != self._detector_mode:   # cambio en Configuración: se aplica sin reiniciar
                self._load_detector(cfg["detector"])
            if self.error:
                self._publish(self._placeholder(cfg, "Error al cargar el modelo",
                                                "Falta models/detector-personas.onnx: reinstala Traffiqui."))
                self._stop_event.wait(1.0)
                continue
            if not self.capture.connected:
                self.health.no_signal()
                msg = "Cámara desconectada, reintentando…"
                if self.capture.is_file:
                    msg = "No se pudo abrir el video, reintentando…"
                self._publish(self._placeholder(cfg, msg, self.capture.error or "Se reintenta cada 3 s."))
                self._stop_event.wait(0.5)
                continue
            fid, frame = self.capture.latest()
            if frame is None or fid == last_id:
                self.health.no_signal()
                time.sleep(0.003)
                continue
            self.health.observe(frame)
            max_fps = float(self.camera_cfg(cfg).get("max_fps") or 0)
            if max_fps > 0 and stamps and time.perf_counter() - stamps[-1] < 1.0 / max_fps:
                time.sleep(0.005)  # límite de FPS por cámara para repartir el CPU entre varias
                continue
            last_id = fid
            now = time.time()
            if not self.primary:  # línea y zonas de imagen solo en la cámara principal
                cfg = {**cfg, "line": None, "zones": []}
            try:
                out = self._process(frame, cfg, now)
            except Exception:
                log.exception("Error procesando cuadro")
                continue
            # FPS reales = cuadros procesados en los últimos 2 s
            t = time.perf_counter()
            stamps.append(t)
            while stamps and t - stamps[0] > 2.0:
                stamps.popleft()
            span = stamps[-1] - stamps[0]
            self.fps = (len(stamps) - 1) / span if span > 0 else 0.0
            self._hud(out)
            self._publish(out)
        log.info("Inferencia detenida.")
