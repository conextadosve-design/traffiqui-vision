"""Traffiqui Vision: servidor FastAPI (video MJPEG, métricas, dashboard)."""
from __future__ import annotations

import argparse
import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import time

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.alerts import AlertTracker
from app.backup import BackupManager
from app.cloud_sync import CloudError, CloudSync
from app.vendor import vendor_file
from app.config import DATA_DIR, DEFAULTS, Settings
from app.storage import analytics
from app.storage.analytics import local_midnight
from app.storage.db import Database, Recorder
from app.storage.store_analytics import buyers_query, grid_payload, hourly_query, plan_heatmap_grid, store_query
from app.vision.capture import CaptureThread, safe_source_label, source_kind
from app.vision.fusion import GlobalTracker, StoreFusion
from app.vision.pipeline import PipelineThread
from app.vision.plan import compute_homography, default_floorplan, footprint, validate_floorplan

log = logging.getLogger("traffiqui")
STATIC_DIR = Path(__file__).parent / "static"


class CameraRuntime:
    """Captura + inferencia de una cámara."""

    def __init__(self, cam: dict, settings: Settings, fusion: StoreFusion, primary: bool, source=None):
        self.id = cam["id"]
        src = source if source is not None else cam["source"]
        src = int(src) if str(src).strip().isdigit() else src
        self.capture = CaptureThread(src, settings.get("width"), settings.get("height"))
        self.pipeline = PipelineThread(self.capture, settings, self.id, primary, fusion)

    def start(self) -> None:
        self.capture.start()
        self.pipeline.start()

    def stop(self) -> None:
        self.pipeline.stop()
        self.capture.stop()
        self.pipeline.join(timeout=5)
        self.capture.join(timeout=5)


def default_camera(index=0) -> dict:
    return {"id": "cam1", "name": "Cámara 1", "source": str(index), "enabled": True, "max_fps": 0,
            "calibration": None}


class Runtime:
    """Cámaras, fusión de la tienda y grabación, compartidos por las rutas."""

    def __init__(self):
        self.settings: Settings | None = None
        self.db: Database | None = None
        self.recorder: Recorder | None = None
        self.cloud: CloudSync | None = None
        self.backup: BackupManager | None = None
        self.alerts = AlertTracker()
        self.fusion: StoreFusion | None = None
        self.cams: dict[str, CameraRuntime] = {}
        self.primary_id = "cam1"
        self.cli_source = None
        self._today_cache = (0.0, 0)
        self._lock = threading.Lock()

    # compatibilidad con las rutas de las fases 1–4: cámara principal
    @property
    def pipeline(self) -> PipelineThread:
        return self.cams[self.primary_id].pipeline

    @property
    def capture(self) -> CaptureThread:
        return self.cams[self.primary_id].capture

    def start(self, source: int | str | None = None, db_path: Path | None = None) -> None:
        self.db = Database(db_path or DATA_DIR / "traffiqui.db")
        self.settings = Settings(self.db.load_config())
        first_run = {}
        if not self.settings.get("cameras"):
            first_run["cameras"] = [default_camera(self.settings.get("camera_index"))]
        if not self.settings.get("floorplan"):
            first_run["floorplan"] = default_floorplan()
        if first_run:
            self.settings.update(first_run)
            self.db.save_config(first_run)
        cfg = self.settings.snapshot()
        self.cli_source = source
        self.db.start_session(source if source is not None else cfg["cameras"][0]["source"], cfg)
        self.fusion = StoreFusion(GlobalTracker(reentry_s=cfg["reid_reentry_s"], handoff_s=cfg["reid_handoff_s"],
                                                min_confirm_s=cfg["min_track_seconds"]), plan=cfg["floorplan"])
        self.fusion.stop_seconds = cfg["stop_seconds"]
        self.fusion.buyer_seconds = cfg["buyer_seconds"]
        self.fusion.staff_hours = cfg["staff_hours"]
        self.fusion.staff_zone_seconds = cfg["staff_zone_seconds"]
        self.fusion.listeners.append(self.db.on_event)
        self.primary_id = cfg["cameras"][0]["id"]  # la primera cámara es la principal
        for cam in cfg["cameras"]:
            if cam.get("enabled", True) or cam["id"] == self.primary_id:
                self._start_cam(cam)
        primary = self.pipeline
        primary.metrics.listeners.append(self.db.on_event)
        primary.on_reference = self.db.save_reference
        primary.request_reference()
        self.recorder = Recorder(self.db, primary.metrics, fusion=self.fusion)
        self.recorder.start()
        self.cloud = CloudSync(self.db, floorplan=lambda: self.settings.get("floorplan"), live=live_payload)
        self.cloud.start()
        self.backup = BackupManager(Path(self.db.path).parent)
        self.backup.start()

    def _start_cam(self, cam: dict) -> None:
        primary = cam["id"] == self.primary_id
        cr = CameraRuntime(cam, self.settings, self.fusion, primary,
                           source=self.cli_source if primary else None)
        self.cams[cam["id"]] = cr
        cr.start()
        log.info("Cámara %s (%s) iniciada", cam["id"], safe_source_label(cr.capture.source))

    def sync_cameras(self) -> None:
        """Aplica la lista de cámaras de la configuración sin reiniciar la app."""
        with self._lock:
            cams = {c["id"]: c for c in self.settings.get("cameras")}
            for cid in list(self.cams):
                if cid == self.primary_id:
                    continue
                if cid not in cams or not cams[cid].get("enabled", True):
                    self.cams.pop(cid).stop()
                    log.info("Cámara %s detenida", cid)
            for cid, cam in cams.items():
                running = self.cams.get(cid)
                if running is None:
                    if cam.get("enabled", True):
                        self._start_cam(cam)
                    continue
                src = cam["source"]
                src = int(src) if str(src).strip().isdigit() else src
                if cid == self.primary_id and self.cli_source is not None:
                    continue  # la fuente de --source manda mientras dure la sesión
                if src != running.capture.source:
                    running.capture.set_source(src)

    def stop(self) -> None:
        for cr in self.cams.values():
            cr.pipeline.stop()
        for cr in self.cams.values():
            cr.pipeline.join(timeout=5)
        if self.cams:
            self.pipeline.metrics.finish_all()
        if self.fusion:
            self.fusion.finish_all(time.time())
        if self.recorder:
            self.recorder.stop()
        if self.backup:
            self.backup.stop()
        if self.cloud:
            self.cloud.stop()  # lo que falte se envía al volver a abrir la app
        for cr in self.cams.values():
            cr.capture.stop()
            cr.capture.join(timeout=5)
        if self.db:
            self.db.close()

    def unique_today(self) -> int:
        return self.today_counts()[0]

    def today_counts(self) -> tuple[int, int]:
        """(personas únicas hoy, pasaron por caja hoy), con caché de 2 s."""
        at, counts = self._today_cache
        if time.time() - at > 2.0 or not isinstance(counts, tuple):
            midnight = local_midnight(time.time())
            counts = (self.db.count_globals_since(midnight), self.db.count_buyers_since(midnight))
            self._today_cache = (time.time(), counts)
        return counts

runtime = Runtime()
CLI_SOURCE: int | str | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    runtime.start(CLI_SOURCE)
    yield
    log.info("Cerrando: liberando cámara…")
    runtime.stop()


app = FastAPI(title="Traffiqui Vision", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def no_stale_frontend(request: Request, call_next):
    """La página y sus scripts se revalidan siempre: tras una actualización el navegador
    no mezcla un index.html nuevo con un app.js viejo guardado en caché."""
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/vendor/{name}")
def vendor(name: str):
    return vendor_file(name)


@app.get("/video")
async def video(cam: str | None = None):
    boundary = "frame"
    cr = runtime.cams.get(cam or runtime.primary_id)
    if cr is None:
        raise HTTPException(404, f"La cámara «{cam}» no existe o está deshabilitada.")

    async def stream():
        last = -1
        while True:
            fid, jpeg = cr.pipeline.latest_jpeg()
            if jpeg is not None and fid != last:
                last = fid
                yield (b"--" + boundary.encode() + b"\r\nContent-Type: image/jpeg\r\n"
                       b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")
            await asyncio.sleep(0.02)

    return StreamingResponse(stream(), media_type=f"multipart/x-mixed-replace; boundary={boundary}",
                             headers={"Cache-Control": "no-store"})


def camera_status() -> list[dict]:
    cfg = runtime.settings.snapshot()
    out = []
    for cam in cfg["cameras"]:
        cr = runtime.cams.get(cam["id"])
        cal = cam.get("calibration") or {}
        out.append({
            "id": cam["id"], "name": cam["name"], "enabled": cam.get("enabled", True),
            "source": safe_source_label(cam["source"]), "kind": source_kind(cam["source"]),
            "primary": cam["id"] == runtime.primary_id, "max_fps": cam.get("max_fps", 0),
            "running": cr is not None,
            "connected": bool(cr and cr.capture.connected),
            "error": cr.capture.error if cr else None,
            "fps": round(cr.pipeline.fps, 1) if cr else 0.0,
            "calibrated": bool(cal.get("H")), "calibration_error_m": cal.get("error_m"),
            "health": cr.pipeline.health.snapshot() if cr else {"state": "apagada", "ok": False,
                                                                "message": "Cámara deshabilitada", "since": None},
        })
    return out


def live_metrics() -> dict:
    p, c = runtime.pipeline, runtime.capture
    cfg = runtime.settings.snapshot()
    now = time.time()
    store = runtime.fusion.snapshot(now)
    cams = camera_status()
    people, seen = [], set()  # una persona vista por dos cámaras aparece una sola vez
    for cr in runtime.cams.values():
        for person in cr.pipeline.active_people():
            if person["id"] not in seen:
                seen.add(person["id"])
                people.append(person)
    return {
        "fps": round(p.fps, 1),
        "infer_ms": round(p.infer_ms, 1),
        "backend": p.backend,
        "camera_connected": c.connected,
        "camera_error": c.error,
        "model_error": p.error,
        "people": people,
        "unique_today": runtime.today_counts()[0],
        "buyers_today": runtime.today_counts()[1],
        "reference_status": p.reference_status,
        **p.metrics.snapshot(cfg),
        # la tienda completa (todas las cámaras, sin duplicar) manda sobre la cámara principal
        "people_now": store["people_now"],
        "unique_session": store["unique_session"],
        "peak": store["peak"],
        "peak_at": store["peak_at"],
        "dwell": store["dwell"],
        "store": store,
        "cameras": cams,
        "alerts": runtime.alerts.update(cfg, store["people_now"], store.get("areas", []), cams, now),
    }


def live_payload() -> dict:
    """Estado en vivo para la sede principal: solo números y posiciones en el plano, nunca imágenes."""
    now = time.time()
    cfg = runtime.settings.snapshot()
    store = runtime.fusion.snapshot(now)
    cams = camera_status()
    today, checkout_today = runtime.today_counts()
    return {
        "ts": now,
        "people_now": store["people_now"], "unique_today": today, "checkout_today": checkout_today,
        "entries": store["entries"], "exits": store["exits"], "peak": store["peak"], "peak_at": store["peak_at"],
        "dwell": store["dwell"], "staff_now": store["staff_now"],
        "areas": [{"id": a["id"], "name": a["name"], "kind": a["kind"], "inside": a["inside"]} for a in store["areas"]],
        "people": [{"gid": p["gid"], "x": p["x"], "y": p["y"], "color": p["color"], "staff": p["staff"],
                    "buyer": p["buyer"]} for p in store["people"] if p["confirmed"] and p["x"] is not None],
        "cameras": [{"id": c["id"], "name": c["name"], "enabled": c["enabled"], "connected": c["connected"],
                     "fps": c["fps"], "health": {k: c["health"].get(k) for k in ("state", "message", "since")}}
                    for c in cams],
        "alerts": runtime.alerts.update(cfg, store["people_now"], store["areas"], cams, now),
    }


@app.get("/api/status")
def status():
    return JSONResponse(live_metrics())


@app.websocket("/ws")
async def ws(socket: WebSocket):
    await socket.accept()
    try:
        while True:
            await socket.send_json(live_metrics())
            await asyncio.sleep(1.0)
    except (WebSocketDisconnect, RuntimeError):
        pass


def _valid_point(p) -> bool:
    return (isinstance(p, (list, tuple)) and len(p) == 2
            and all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in p))


RESOLUTIONS = [(640, 480), (800, 600), (1280, 720), (1920, 1080)]
IMGSZ_OPTIONS = [320, 384, 416, 480, 512, 640]
NUMERIC_RANGES = {  # clave: (mínimo, máximo, nombre para el mensaje)
    "confidence": (0.1, 0.95, "La confianza"),
    "trail_seconds": (1, 10, "La duración del rastro"),
    "heatmap_half_life": (5, 600, "La vida media del mapa de calor"),
    "stop_seconds": (1, 600, "El umbral de \"se detuvo\""),
    "min_track_seconds": (0, 10, "La duración mínima de un track"),
    "lost_track_seconds": (0.5, 10, "El tiempo de espera de un track perdido"),
    "camera_index": (0, 9, "El índice de cámara"),
    "reid_reentry_s": (0, 1800, "La memoria para reconocer a quien vuelve"),
    "reid_handoff_s": (0, 120, "La ventana de traspaso entre cámaras"),
    "buyer_seconds": (5, 600, "El tiempo en cajas para contar como \"pasó por caja\""),
    "staff_hours": (0, 24, "Las horas para considerar a alguien personal"),
    "staff_zone_seconds": (1, 600, "El tiempo en zona de personal"),
    "alert_capacity": (0, 2000, "El aforo máximo"),
    "alert_queue_people": (0, 50, "Las personas en fila para avisar"),
}
CHOICES = {
    "track_point": ("center", "bottom"),
    "detector": ("preciso", "rapido"),
    "heatmap_mode": ("live", "accum"),
}
BOOLEANS = ("show_boxes", "show_trails", "show_heatmap", "show_zones", "show_line", "privacy_blur",
            "show_plan_areas")
MANAGED_KEYS = {"cameras": "/api/cams", "floorplan": "/api/floorplan"}  # tienen su propia ruta


def validate_config(changes: dict) -> str | None:
    """Mensaje de error en español, o None si los cambios son válidos."""
    unknown = [k for k in changes if k not in DEFAULTS]
    if unknown:
        return f"Parámetros desconocidos: {', '.join(unknown)}."
    managed = [k for k in changes if k in MANAGED_KEYS]
    if managed:
        return f"«{managed[0]}» se cambia en {MANAGED_KEYS[managed[0]]}."
    for k, (lo, hi, name) in NUMERIC_RANGES.items():
        if k in changes:
            v = changes[k]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
                return f"{name} debe estar entre {lo} y {hi}."
    for k, options in CHOICES.items():
        if k in changes and changes[k] not in options:
            return f"Valor no válido para {k}: {changes[k]}."
    for k in BOOLEANS:
        if k in changes and not isinstance(changes[k], bool):
            return f"{k} debe ser verdadero o falso."
    if "imgsz" in changes and changes["imgsz"] not in IMGSZ_OPTIONS:
        return f"imgsz debe ser uno de {IMGSZ_OPTIONS}."
    if "width" in changes or "height" in changes:
        cur = runtime.settings.snapshot() if runtime.settings else DEFAULTS
        res = (changes.get("width", cur["width"]), changes.get("height", cur["height"]))
        if res not in RESOLUTIONS:
            return "Resolución no soportada. Usa 640×480, 800×600, 1280×720 o 1920×1080."
    line = changes.get("line", "sin cambio")
    if line not in ("sin cambio", None):
        if not (isinstance(line, dict) and _valid_point(line.get("a")) and _valid_point(line.get("b"))):
            return "La línea necesita dos puntos dentro del video."
    for z in changes.get("zones", []):
        if not (isinstance(z, dict) and z.get("id") and str(z.get("name", "")).strip()):
            return "Cada zona necesita un nombre."
        pts = z.get("points") or []
        if len(pts) < 3 or not all(_valid_point(p) for p in pts):
            return f"La zona «{z.get('name')}» necesita al menos 3 puntos dentro del video."
    return None


@app.get("/api/config")
def get_config():
    return runtime.settings.snapshot()


@app.patch("/api/config")
async def patch_config(request: Request):
    changes = await request.json()
    if not isinstance(changes, dict):
        raise HTTPException(400, "Se esperaba un objeto JSON.")
    err = validate_config(changes)
    if err:
        raise HTTPException(400, err)
    before = runtime.settings.snapshot()
    updated = runtime.settings.update(changes)
    runtime.db.save_config(changes)
    if updated["camera_index"] != before["camera_index"]:
        # "Usar esta cámara" de la tarjeta de webcam cambia la fuente de la cámara principal
        cams = [dict(c) for c in updated["cameras"]]
        cams[0]["source"] = str(updated["camera_index"])
        runtime.cli_source = None
        updated = runtime.settings.update({"cameras": cams})
        runtime.db.save_config({"cameras": cams})
        runtime.sync_cameras()
    if (updated["width"], updated["height"]) != (before["width"], before["height"]):
        for cr in runtime.cams.values():
            cr.capture.set_source(cr.capture.source, updated["width"], updated["height"])
    tr = runtime.fusion.tracker
    tr.reentry_s, tr.handoff_s = updated["reid_reentry_s"], updated["reid_handoff_s"]
    tr.min_confirm_s = updated["min_track_seconds"]
    runtime.fusion.stop_seconds = updated["stop_seconds"]
    runtime.fusion.buyer_seconds = updated["buyer_seconds"]
    runtime.fusion.staff_hours = updated["staff_hours"]
    runtime.fusion.staff_zone_seconds = updated["staff_zone_seconds"]
    return updated


def _probe_camera(index: int) -> bytes | None:
    """Abre la cámara `index`, toma un cuadro y la libera. Solo para probar; no se guarda."""
    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    try:
        if not cap.isOpened():
            return None
        for _ in range(5):  # los primeros cuadros suelen salir negros
            ok, frame = cap.read()
        if not ok:
            return None
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return buf.tobytes() if ok else None
    finally:
        cap.release()


def _usb_in_use() -> dict[int, CameraRuntime]:
    """Índices USB abiertos por alguna cámara en marcha (no se pueden abrir dos veces)."""
    return {int(cr.capture.source): cr for cr in runtime.cams.values() if cr.capture.kind == "usb"}


@app.get("/api/cameras")
async def list_cameras():
    """Índices 0–5 que responden. La cámara en uso se reporta sin abrirla de nuevo."""
    in_use = _usb_in_use()
    found = []
    for i in range(6):
        if i in in_use:
            found.append({"index": i, "in_use": True, "ok": in_use[i].capture.connected})
            continue
        ok = await asyncio.to_thread(lambda i=i: _probe_camera(i) is not None)
        if ok:
            found.append({"index": i, "in_use": False, "ok": True})
    return {"cameras": found, "demo_source": runtime.capture.source if runtime.capture.is_file else None}


@app.get("/api/cameras/{index}/test")
async def test_camera(index: int):
    in_use = _usb_in_use()
    if index in in_use:
        _, frame = in_use[index].capture.latest()
        ok, buf = cv2.imencode(".jpg", frame) if frame is not None else (False, None)
        jpeg = buf.tobytes() if ok else None
    else:
        jpeg = await asyncio.to_thread(_probe_camera, index)
    if jpeg is None:
        raise HTTPException(404, f"La cámara {index} no respondió. Revisa que esté conectada y que "
                                 "ninguna otra aplicación (Zoom, Teams, Cámara) la esté usando.")
    return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


# ---- plano de la tienda ----------------------------------------------------------------
@app.get("/api/floorplan")
def get_floorplan():
    return runtime.settings.get("floorplan")


@app.put("/api/floorplan")
async def put_floorplan(request: Request):
    plan = await request.json()
    err = validate_floorplan(plan)
    if err:
        raise HTTPException(400, err)
    cam_ids = {c["id"] for c in runtime.settings.get("cameras")}
    for e in plan["elements"]:
        if e["type"] == "area":
            e["cameras"] = [c for c in e.get("cameras", []) if c in cam_ids]
    runtime.settings.update({"floorplan": plan})
    runtime.db.save_config({"floorplan": plan})
    runtime.fusion.set_plan(plan)
    return plan


# ---- cámaras de la tienda -------------------------------------------------------------
MAX_CAMERAS = 8


def _cam_error(body: dict, cams: list[dict], cid: str | None = None) -> str | None:
    if "name" in body and not (isinstance(body["name"], str) and 0 < len(body["name"].strip()) <= 40):
        return "El nombre de la cámara debe tener entre 1 y 40 caracteres."
    if "source" in body:
        src = body["source"]
        if not isinstance(src, (str, int)) or not str(src).strip():
            return "Indica la fuente: un índice USB (0, 1…), una URL rtsp://… o la ruta de un video."
        src = str(src).strip()
        if source_kind(src) == "usb" and any(c["id"] != cid and str(c["source"]).strip() == src for c in cams):
            return f"La webcam {src} ya está asignada a otra cámara."
    if "max_fps" in body:
        v = body["max_fps"]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 30:
            return "El límite de FPS debe estar entre 0 (sin límite) y 30."
    if "enabled" in body and not isinstance(body["enabled"], bool):
        return "«enabled» debe ser verdadero o falso."
    return None


def _save_cams(cams: list[dict]) -> None:
    runtime.settings.update({"cameras": cams})
    runtime.db.save_config({"cameras": cams})
    runtime.sync_cameras()


def _find_cam(cid: str) -> tuple[list[dict], dict]:
    cams = [dict(c) for c in runtime.settings.get("cameras")]
    cam = next((c for c in cams if c["id"] == cid), None)
    if cam is None:
        raise HTTPException(404, f"La cámara «{cid}» no existe.")
    return cams, cam


@app.get("/api/cams")
def list_cams():
    return {"cameras": camera_status(), "max": MAX_CAMERAS}


@app.post("/api/cams")
async def add_cam(request: Request):
    body = await request.json()
    cams = [dict(c) for c in runtime.settings.get("cameras")]
    if len(cams) >= MAX_CAMERAS:
        raise HTTPException(400, f"Máximo {MAX_CAMERAS} cámaras en esta PC. Para más, reparte las cámaras en varios equipos.")
    body = {"name": f"Cámara {len(cams) + 1}", "enabled": True, "max_fps": 8, **body}
    if "source" not in body:
        raise HTTPException(400, "Indica la fuente de la cámara.")
    err = _cam_error(body, cams)
    if err:
        raise HTTPException(400, err)
    n = 1
    while any(c["id"] == f"cam{n}" for c in cams):
        n += 1
    cam = {"id": f"cam{n}", "name": body["name"].strip(), "source": str(body["source"]).strip(),
           "enabled": body["enabled"], "max_fps": body["max_fps"], "calibration": None}
    cams.append(cam)
    _save_cams(cams)
    return cam


@app.patch("/api/cams/{cid}")
async def patch_cam(cid: str, request: Request):
    body = await request.json()
    cams, cam = _find_cam(cid)
    allowed = {k: body[k] for k in ("name", "source", "enabled", "max_fps") if k in body}
    err = _cam_error(allowed, cams, cid)
    if err:
        raise HTTPException(400, err)
    if cid == runtime.primary_id and allowed.get("enabled") is False:
        raise HTTPException(400, "La cámara principal no se puede deshabilitar (puedes cambiar su fuente).")
    if "source" in allowed:
        allowed["source"] = str(allowed["source"]).strip()
        if cid == runtime.primary_id:
            runtime.cli_source = None
    if "name" in allowed:
        allowed["name"] = allowed["name"].strip()
    cam.update(allowed)
    _save_cams(cams)
    return cam


@app.post("/api/cams/{cid}/health/reset")
def cam_health_reset(cid: str):
    cr = runtime.cams.get(cid)
    if cr is None:
        raise HTTPException(404, "Esa cámara no está en marcha.")
    cr.pipeline.health.reset_reference()
    return cr.pipeline.health.snapshot()


@app.delete("/api/cams/{cid}")
def delete_cam(cid: str):
    cams, cam = _find_cam(cid)
    if cid == runtime.primary_id:
        raise HTTPException(400, "La cámara principal no se puede borrar (puedes cambiar su fuente).")
    _save_cams([c for c in cams if c["id"] != cid])
    plan = runtime.settings.get("floorplan")
    for e in plan["elements"]:  # quitarla de las áreas a las que estaba asignada
        if e["type"] == "area" and cid in e.get("cameras", []):
            e["cameras"] = [c for c in e["cameras"] if c != cid]
    runtime.settings.update({"floorplan": plan})
    runtime.db.save_config({"floorplan": plan})
    runtime.fusion.set_plan(plan)
    return {"ok": True}


@app.get("/api/cams/{cid}/snapshot")
def cam_snapshot(cid: str):
    """Cuadro actual sin overlays para calibrar. Solo se muestra; no se guarda."""
    cr = runtime.cams.get(cid)
    if cr is None:
        raise HTTPException(409, "La cámara no está en marcha. Habilítala primero.")
    _, frame = cr.capture.latest()
    if frame is None:
        raise HTTPException(409, "La cámara todavía no entrega imagen. Revisa la conexión y reintenta.")
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return Response(buf.tobytes(), media_type="image/jpeg",
                    headers={"Cache-Control": "no-store", "X-Frame-Size": f"{frame.shape[1]}x{frame.shape[0]}"})


@app.put("/api/cams/{cid}/calibration")
async def put_calibration(cid: str, request: Request):
    body = await request.json()
    img, pln = body.get("image") or [], body.get("plan") or []
    if not (isinstance(img, list) and isinstance(pln, list)) or len(img) != len(pln) or len(img) < 4:
        raise HTTPException(400, "Marca al menos 4 pares de puntos: cada punto del piso en la imagen y su lugar en el plano.")
    if not all(_valid_point(p) for p in img):
        raise HTTPException(400, "Los puntos de la imagen deben estar dentro del video.")
    plan = runtime.settings.get("floorplan")
    if not all(isinstance(p, list) and len(p) == 2 and 0 <= p[0] <= plan["width"] and 0 <= p[1] <= plan["depth"]
               for p in pln):
        raise HTTPException(400, "Los puntos del plano deben estar dentro del local.")
    try:
        H, err_m = compute_homography(img, pln)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    cams, cam = _find_cam(cid)
    cam["calibration"] = {"image": img, "plan": pln, "H": H.tolist(), "error_m": round(err_m, 3)}
    _save_cams(cams)
    return {"error_m": round(err_m, 3), "footprint": footprint(H, plan["width"], plan["depth"])}


@app.delete("/api/cams/{cid}/calibration")
def delete_calibration(cid: str):
    cams, cam = _find_cam(cid)
    cam["calibration"] = None
    _save_cams(cams)
    return {"ok": True}


@app.get("/api/cams/footprints")
def cam_footprints():
    plan = runtime.settings.get("floorplan")
    out = {}
    for cam in runtime.settings.get("cameras"):
        H = (cam.get("calibration") or {}).get("H")
        if H:
            out[cam["id"]] = footprint(np.asarray(H), plan["width"], plan["depth"])
    return out


@app.post("/api/heatmap/reset")
def reset_heatmap():
    for cr in runtime.cams.values():
        cr.pipeline.metrics.heatmap.reset()
    runtime.fusion.reset_heatmap()
    return {"ok": True}


@app.post("/api/reference/recapture")
def recapture_reference():
    runtime.pipeline.request_reference()
    return {"ok": True, "message": "Buscando un cuadro sin personas (hasta 10 s)…"}


# ---- analítica ---------------------------------------------------------------------------
def _range(range_: str, start: str | None, end: str | None) -> tuple[float, float]:
    try:
        return analytics.resolve_range(range_, start, end)
    except analytics.RangeError as exc:
        raise HTTPException(400, str(exc))


def _analytics(range_: str, start, end, bucket: int) -> dict:
    if bucket not in (5, 15, 60, 1440):
        raise HTTPException(400, "El intervalo debe ser 5, 15 o 60 minutos, o 1 día.")
    t0, t1 = _range(range_, start, end)
    # rangos largos con intervalos chicos darían miles de barras: se sube al intervalo que alcance
    for b in (bucket, 60, 1440):
        if b >= bucket and (t1 - t0) / (b * 60) <= 800:
            bucket = b
            break
    else:
        bucket = 1440
    runtime.db.flush(timeout=2)  # incluir lo que esté en la cola
    return analytics.query(runtime.db, t0, t1, bucket, runtime.settings.get("stop_seconds"))


@app.get("/api/analytics")
def get_analytics(range: str = "today", start: str | None = None, end: str | None = None, bucket: int = 15):
    return _analytics(range, start, end, bucket)


@app.get("/api/analytics/heatmap.png")
def analytics_heatmap(range: str = "today", start: str | None = None, end: str | None = None):
    t0, t1 = _range(range, start, end)
    runtime.db.flush(timeout=2)
    hm = runtime.pipeline.metrics.heatmap
    extra = hm.pending.copy() if t1 >= time.time() - 5 else None  # lo de los últimos minutos aún no guardado
    grid = analytics.heatmap_grid(runtime.db, t0, t1, (hm.gh, hm.gw), extra)
    png = analytics.heatmap_png(runtime.db, grid, (hm.frame_w, hm.frame_h))
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.get("/api/analytics/export.csv")
def export_csv(range: str = "today", start: str | None = None, end: str | None = None, bucket: int = 15):
    data = _analytics(range, start, end, bucket)
    store = _store(range, start, end)
    buyers = _buyers(range, start, end)
    hourly = _hourly(range, start, end)
    name = time.strftime("traffiqui_%Y%m%d_%H%M.csv")
    return Response("﻿" + analytics.to_csv(data, store, buyers, hourly), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ---- analítica de la tienda (plano) ----------------------------------------------------
def _store(range_: str, start, end) -> dict:
    t0, t1 = _range(range_, start, end)
    runtime.db.flush(timeout=2)
    areas = [e for e in runtime.settings.get("floorplan")["elements"] if e["type"] == "area"]
    return store_query(runtime.db, t0, t1, areas, runtime.settings.get("stop_seconds"))


def _buyers(range_: str, start, end) -> dict:
    t0, t1 = _range(range_, start, end)
    runtime.db.flush(timeout=2)
    areas = [e for e in runtime.settings.get("floorplan")["elements"] if e["type"] == "area"]
    return buyers_query(runtime.db, t0, t1, areas, runtime.settings.get("buyer_seconds"))


def _hourly(range_: str, start, end, area: str = "store", metric: str = "people") -> dict:
    if metric not in ("people", "buyers"):
        raise HTTPException(400, "La métrica debe ser personas o pasaron por caja.")
    t0, t1 = _range(range_, start, end)
    runtime.db.flush(timeout=2)
    areas = [e for e in runtime.settings.get("floorplan")["elements"] if e["type"] == "area"]
    return hourly_query(runtime.db, t0, t1, areas, area, metric)



# ---- multisede: conexión con el servidor central ------------------------------------------
@app.get("/api/cloud")
def cloud_status():
    return runtime.cloud.status()


@app.put("/api/cloud")
async def cloud_connect(request: Request):
    body = await request.json()
    try:
        status = await asyncio.to_thread(runtime.cloud.connect, str(body.get("url", "")), str(body.get("site_key", "")))
    except CloudError as e:
        raise HTTPException(400, str(e)) from e
    return status


@app.delete("/api/cloud")
def cloud_disconnect():
    runtime.cloud.disconnect()
    return runtime.cloud.status()


@app.post("/api/cloud/sync")
def cloud_sync_now():
    runtime.cloud.sync_now()
    return {"ok": True}


# ---- copias de seguridad ---------------------------------------------------------------------
@app.get("/api/backup")
def backup_status():
    return runtime.backup.status()


@app.post("/api/backup/now")
async def backup_now():
    try:
        await asyncio.to_thread(runtime.backup.run_now)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"No se pudo hacer la copia: {e}") from e
    return runtime.backup.status()


@app.put("/api/backup")
async def backup_config(request: Request):
    try:
        return runtime.backup.set_extra_dir(str((await request.json()).get("extra_dir", "")))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/store/hourly")
def get_hourly(range: str = "week", start: str | None = None, end: str | None = None,
               area: str = "store", metric: str = "people"):
    """Personas por día y hora (0–23) de la tienda o de un área, y la hora pico de cada área."""
    return _hourly(range, start, end, area, metric)


@app.get("/api/store/buyers")
def get_buyers(range: str = "today", start: str | None = None, end: str | None = None):
    return _buyers(range, start, end)


@app.get("/api/store/analytics")
def get_store_analytics(range: str = "today", start: str | None = None, end: str | None = None):
    return _store(range, start, end)


@app.get("/api/store/heatmap")
def get_store_heatmap(range: str = "today", start: str | None = None, end: str | None = None, mode: str = "range"):
    """mode=live: calor en vivo (con decaimiento). mode=range: acumulado del rango desde SQLite."""
    f = runtime.fusion
    plan = runtime.settings.get("floorplan")
    if mode == "live":
        grid = f.plan_heatmap("live")
    else:
        t0, t1 = _range(range, start, end)
        runtime.db.flush(timeout=2)
        extra = f.peek_plan_pending() if t1 >= time.time() - 5 else None
        grid = plan_heatmap_grid(runtime.db, t0, t1, (f.heatmap.rows, f.heatmap.cols), extra)
    return grid_payload(grid, f.heatmap.cell, plan["width"], plan["depth"])


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Traffiqui Vision")
    ap.add_argument("--source", help="Índice de cámara (0, 1…) o ruta a un video para modo demo")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--open", action="store_true", help="Abrir el dashboard en el navegador al arrancar")
    return ap.parse_args(argv)


def open_browser_when_ready(port: int) -> None:
    import threading
    import urllib.request
    import webbrowser

    def wait_and_open():
        for _ in range(120):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/api/config", timeout=1)
                webbrowser.open(f"http://localhost:{port}")
                return
            except OSError:
                time.sleep(0.5)

    threading.Thread(target=wait_and_open, name="abrir-navegador", daemon=True).start()


def main(argv=None):
    global CLI_SOURCE
    import uvicorn

    args = parse_args(argv)
    if args.source is not None:
        CLI_SOURCE = int(args.source) if args.source.isdigit() else args.source
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.open:
        open_browser_when_ready(args.port)
    log.info("Traffiqui Vision en http://localhost:%d  (Ctrl+C para cerrar)", args.port)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
