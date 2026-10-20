"""Hilo de captura: lee una webcam USB, un stream RTSP/HTTP (CCTV) o un video en bucle,
y guarda solo el último cuadro."""
from __future__ import annotations

import logging
import os
import threading
import time

import cv2
import numpy as np

log = logging.getLogger("traffiqui.capture")
RECONNECT_SECONDS = 3.0
# RTSP por TCP (UDP pierde paquetes en redes de tienda) y timeout de 5 s al conectar
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|stimeout;5000000")
STREAM_PREFIXES = ("rtsp://", "rtsps://", "http://", "https://")


def source_kind(source) -> str:
    """'usb' (índice), 'stream' (RTSP/HTTP) o 'file' (video local)."""
    if isinstance(source, int) or (isinstance(source, str) and source.strip().isdigit()):
        return "usb"
    if isinstance(source, str) and source.strip().lower().startswith(STREAM_PREFIXES):
        return "stream"
    return "file"


def safe_source_label(source) -> str:
    """Fuente para mostrar o registrar, sin usuario ni contraseña de la URL RTSP."""
    s = str(source)
    if source_kind(s) == "stream" and "@" in s:
        scheme, rest = s.split("://", 1)
        return f"{scheme}://***@{rest.split('@', 1)[1]}"
    return s


class CaptureThread(threading.Thread):
    def __init__(self, source: int | str, width: int = 640, height: int = 480):
        super().__init__(name="captura", daemon=True)
        self.source = source
        self.width, self.height = width, height
        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._frame_id = 0
        self._stop_event = threading.Event()
        self._restart = threading.Event()
        self.connected = False
        self.error: str | None = None

    @property
    def kind(self) -> str:
        return source_kind(self.source)

    @property
    def is_file(self) -> bool:
        return self.kind == "file"

    def latest(self) -> tuple[int, np.ndarray | None]:
        with self._lock:
            return self._frame_id, self._frame

    def set_source(self, source: int | str, width: int | None = None, height: int | None = None) -> None:
        """Cambia de cámara o resolución sin reiniciar la app."""
        self.source = source
        if width:
            self.width = width
        if height:
            self.height = height
        self._restart.set()

    def stop(self) -> None:
        self._stop_event.set()

    def _open(self) -> cv2.VideoCapture | None:
        if self.kind == "file":
            cap = cv2.VideoCapture(self.source)
        elif self.kind == "stream":
            cap = cv2.VideoCapture(self.source.strip(), cv2.CAP_FFMPEG)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        else:
            cap = cv2.VideoCapture(int(self.source), cv2.CAP_DSHOW)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not cap.isOpened():
            cap.release()
            return None
        return cap

    def run(self) -> None:
        while not self._stop_event.is_set():
            self._restart.clear()
            cap = self._open()
            if cap is None:
                self.connected = False
                self.error = {
                    "file": f"No se pudo abrir el video '{self.source}'.",
                    "stream": f"No se pudo conectar al stream {safe_source_label(self.source)}. "
                              "Revisa la URL, el usuario/contraseña y que la cámara esté en la misma red.",
                }.get(self.kind, f"No se encontró la cámara {self.source}.")
                log.warning("%s Reintentando en %.0f s", self.error, RECONNECT_SECONDS)
                self._stop_event.wait(RECONNECT_SECONDS)
                continue
            self.connected, self.error = True, None
            log.info("Fuente abierta: %s", safe_source_label(self.source))
            frame_interval = 0.0
            if self.is_file:
                fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
                frame_interval = 1.0 / max(1.0, fps)
            fails = 0
            while not self._stop_event.is_set() and not self._restart.is_set():
                t0 = time.perf_counter()
                ok, frame = cap.read()
                if not ok:
                    if self.is_file:  # modo demo: volver al inicio
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    fails += 1
                    if fails >= (50 if self.kind == "stream" else 10):
                        self.error = "Cámara desconectada." if self.kind != "stream" else "Se perdió el stream de la cámara."
                        log.warning("Cámara desconectada, reintentando…")
                        break
                    time.sleep(0.05)
                    continue
                fails = 0
                if self.kind != "usb" and frame.shape[1] > self.width:
                    # video y CCTV: se reduce al ancho configurado conservando la proporción (menos CPU)
                    h = round(frame.shape[0] * self.width / frame.shape[1])
                    frame = cv2.resize(frame, (self.width, h), interpolation=cv2.INTER_AREA)
                with self._lock:
                    self._frame = frame
                    self._frame_id += 1
                if frame_interval:
                    time.sleep(max(0.0, frame_interval - (time.perf_counter() - t0)))
            cap.release()
            self.connected = False
            if not self._stop_event.is_set() and not self._restart.is_set():
                self._stop_event.wait(RECONNECT_SECONDS)
        log.info("Captura detenida, cámara liberada.")
