"""Persistencia en SQLite.

Esquema (todas las marcas de tiempo son epoch en segundos, REAL):

  sessions           una fila por arranque de la app, con la configuración usada
  tracks             una fila por persona confirmada (≥ min_track_seconds);
                     se inserta al confirmarse y se completa al terminar
  line_events        cada cruce de la línea virtual con su dirección
  zone_visits        cada visita a una zona con entrada, salida y duración
  occupancy_samples  cada 5 s: personas en cuadro al cierre de la ventana,
                     máximo y promedio dentro de la ventana
  heatmap_snapshots  cada 5 min: grilla con las posiciones de ESE intervalo
                     (numpy comprimido). Sumar las del rango da el acumulado.
  config             clave → valor JSON; se recarga al iniciar
  reference_frame    único cuadro de referencia (JPEG) para el mapa de calor;
                     se toma sin personas y, si no se logra, con las personas
                     desenfocadas por completo

Nunca se guarda video ni imágenes de personas: solo números, coordenadas de
la grilla y el cuadro de referencia.

Las escrituras pasan por una cola y un hilo que las aplica en lotes (una
transacción por lote) para no frenar la inferencia.
"""
from __future__ import annotations

import io
import json
import logging
import queue
import sqlite3
import threading
import time
from pathlib import Path

import numpy as np

log = logging.getLogger("traffiqui.db")

SCHEMA = """
PRAGMA journal_mode = WAL;
CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  REAL NOT NULL,
    ended_at    REAL,
    source      TEXT,
    config_json TEXT
);
CREATE TABLE IF NOT EXISTS tracks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES sessions(id),
    track_id    INTEGER NOT NULL,
    first_seen  REAL NOT NULL,
    last_seen   REAL,
    duration    REAL,
    color       TEXT,
    zones_json  TEXT NOT NULL DEFAULT '[]',
    UNIQUE (session_id, track_id)
);
CREATE INDEX IF NOT EXISTS idx_tracks_first_seen ON tracks(first_seen);
CREATE TABLE IF NOT EXISTS line_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES sessions(id),
    track_id    INTEGER NOT NULL,
    direction   TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    ts          REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_line_events_ts ON line_events(ts);
CREATE TABLE IF NOT EXISTS zone_visits (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES sessions(id),
    track_id    INTEGER NOT NULL,
    zone_id     TEXT NOT NULL,
    zone_name   TEXT NOT NULL,
    enter_ts    REAL NOT NULL,
    exit_ts     REAL NOT NULL,
    duration    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_zone_visits_enter ON zone_visits(enter_ts);
CREATE TABLE IF NOT EXISTS occupancy_samples (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES sessions(id),
    ts          REAL NOT NULL,
    people      INTEGER NOT NULL,
    people_max  INTEGER NOT NULL,
    people_avg  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_occupancy_ts ON occupancy_samples(ts);
CREATE TABLE IF NOT EXISTS heatmap_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES sessions(id),
    ts_start    REAL NOT NULL,
    ts_end      REAL NOT NULL,
    rows        INTEGER NOT NULL,
    cols        INTEGER NOT NULL,
    grid        BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_heatmap_ts_end ON heatmap_snapshots(ts_end);
CREATE TABLE IF NOT EXISTS config (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS reference_frame (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    ts          REAL NOT NULL,
    width       INTEGER NOT NULL,
    height      INTEGER NOT NULL,
    jpeg        BLOB NOT NULL
);
-- ---- tienda completa: varias cámaras, ID global y plano en metros ----
CREATE TABLE IF NOT EXISTS global_tracks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   INTEGER NOT NULL REFERENCES sessions(id),
    global_id    INTEGER NOT NULL,
    first_seen   REAL NOT NULL,
    last_seen    REAL,
    duration     REAL,
    color        TEXT,
    cameras_json TEXT NOT NULL DEFAULT '[]',
    areas_json   TEXT NOT NULL DEFAULT '[]',   -- recorrido: áreas en orden de visita
    UNIQUE (session_id, global_id)
);
CREATE INDEX IF NOT EXISTS idx_global_tracks_first_seen ON global_tracks(first_seen);
CREATE TABLE IF NOT EXISTS track_links (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES sessions(id),
    camera_id   TEXT NOT NULL,
    track_id    INTEGER NOT NULL,
    global_id   INTEGER NOT NULL,
    reason      TEXT NOT NULL,   -- nueva | superposición | traspaso | re-entrada
    ts          REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_track_links_ts ON track_links(ts);
CREATE TABLE IF NOT EXISTS area_visits (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES sessions(id),
    global_id   INTEGER NOT NULL,
    area_id     TEXT NOT NULL,
    area_name   TEXT NOT NULL,
    enter_ts    REAL NOT NULL,
    exit_ts     REAL NOT NULL,
    duration    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_area_visits_enter ON area_visits(enter_ts);
CREATE TABLE IF NOT EXISTS area_transitions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES sessions(id),
    global_id   INTEGER NOT NULL,
    from_id     TEXT NOT NULL,
    from_name   TEXT NOT NULL,
    to_id       TEXT NOT NULL,
    to_name     TEXT NOT NULL,
    ts          REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_area_transitions_ts ON area_transitions(ts);
CREATE TABLE IF NOT EXISTS plan_heatmap_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES sessions(id),
    ts_start    REAL NOT NULL,
    ts_end      REAL NOT NULL,
    rows        INTEGER NOT NULL,
    cols        INTEGER NOT NULL,
    cell_m      REAL NOT NULL,
    grid        BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_plan_heatmap_ts_end ON plan_heatmap_snapshots(ts_end);
CREATE TABLE IF NOT EXISTS store_door_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES sessions(id),
    global_id   INTEGER NOT NULL,
    door_id     TEXT NOT NULL,
    door_name   TEXT NOT NULL,
    direction   TEXT NOT NULL CHECK (direction IN ('in', 'out')),   -- in = entró al local
    ts          REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_store_door_events_ts ON store_door_events(ts);
-- ---- multisede: conexión con el servidor central (una sola fila) ----
CREATE TABLE IF NOT EXISTS cloud_link (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    url         TEXT,
    site_key    TEXT,             -- clave de la sede; nunca sale por la API local
    db_uid      TEXT NOT NULL,    -- identifica esta base en el servidor (no cambia al reconectar)
    site_name   TEXT,
    org_name    TEXT,
    cursors     TEXT NOT NULL DEFAULT '{}'   -- hasta dónde se envió cada tabla
);
"""

# columnas agregadas después de la primera versión (se crean si faltan en una base existente)
MIGRATIONS = {
    "global_tracks": {
        "is_buyer": "INTEGER NOT NULL DEFAULT 0",          # pasó >= buyer_seconds en zonas de cajas
        "checkout_seconds": "REAL NOT NULL DEFAULT 0",
        "stopped_any": "INTEGER NOT NULL DEFAULT 0",       # se detuvo en alguna área
        "is_staff": "INTEGER NOT NULL DEFAULT 0",          # personal: excluido de las estadísticas de clientes
        "staff_reason": "TEXT",
        "checkout_area_id": "TEXT",                        # caja donde más tiempo estuvo (a la que se asigna)
        "checkout_area": "TEXT",
        "changed_at": "REAL NOT NULL DEFAULT 0",          # última escritura: la sincronización envía lo cambiado
    },
}

BATCH_MAX = 500
BATCH_WAIT = 1.0  # s máximos que una escritura espera en la cola
_STOP = object()


def pack_grid(grid: np.ndarray) -> bytes:
    buf = io.BytesIO()
    np.savez_compressed(buf, grid=grid.astype(np.float32))
    return buf.getvalue()


def unpack_grid(blob: bytes) -> np.ndarray:
    with np.load(io.BytesIO(blob)) as data:
        return data["grid"]


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            for table, cols in MIGRATIONS.items():
                have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
                for col, decl in cols.items():
                    if col not in have:
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        self.session_id: int | None = None
        self._q: queue.Queue = queue.Queue()
        self._writer = threading.Thread(target=self._write_loop, name="sqlite-escritor", daemon=True)
        self._writer.start()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    # ---- escritor en lotes -----------------------------------------------------------
    def enqueue(self, sql: str, params: tuple = ()) -> None:
        self._q.put((sql, params))

    def _write_loop(self) -> None:
        conn = self.connect()
        stopping = False
        while not stopping:
            batch = []
            try:
                item = self._q.get(timeout=BATCH_WAIT)
            except queue.Empty:
                continue
            deadline = time.monotonic() + BATCH_WAIT
            while True:
                if item is _STOP:
                    stopping = True
                    # vaciar lo que quede antes de salir
                    while True:
                        try:
                            rest = self._q.get_nowait()
                        except queue.Empty:
                            break
                        if rest is not _STOP:
                            batch.append(rest)
                    break
                batch.append(item)
                if len(batch) >= BATCH_MAX:
                    break
                try:
                    item = self._q.get(timeout=max(0.0, deadline - time.monotonic()))
                except queue.Empty:
                    break
            waiters = [p for s, p in batch if s is None]
            rows = [(s, p) for s, p in batch if s is not None]
            if rows:
                try:
                    with conn:
                        for sql, params in rows:
                            conn.execute(sql, params)
                except sqlite3.Error:
                    log.exception("Error escribiendo un lote de %d filas en SQLite", len(rows))
            for ev in waiters:
                ev.set()
        conn.close()

    def flush(self, timeout: float = 5.0) -> bool:
        """Espera a que todo lo encolado hasta ahora esté escrito."""
        ev = threading.Event()
        self._q.put((None, ev))
        return ev.wait(timeout)

    def close(self) -> None:
        if self.session_id is not None:
            self.enqueue("UPDATE sessions SET ended_at = ? WHERE id = ?", (time.time(), self.session_id))
        self._q.put(_STOP)
        self._writer.join(timeout=10)
        log.info("Cola de SQLite vaciada.")

    # ---- sesiones y configuración (escritura directa: son pocas y se necesitan ya) ------
    def start_session(self, source, cfg: dict) -> int:
        with self.connect() as conn:
            cur = conn.execute("INSERT INTO sessions (started_at, source, config_json) VALUES (?, ?, ?)",
                               (time.time(), str(source), json.dumps(cfg, ensure_ascii=False)))
            self.session_id = cur.lastrowid
        return self.session_id

    def heartbeat(self) -> None:
        """Mantiene ended_at al día para que una sesión cortada (corte de luz) tenga fin."""
        if self.session_id is not None:
            self.enqueue("UPDATE sessions SET ended_at = ? WHERE id = ?", (time.time(), self.session_id))

    def load_config(self) -> dict:
        with self.connect() as conn:
            rows = conn.execute("SELECT key, value FROM config").fetchall()
        out = {}
        for r in rows:
            try:
                out[r["key"]] = json.loads(r["value"])
            except json.JSONDecodeError:
                log.warning("Valor de configuración inválido para %s; se ignora", r["key"])
        return out

    def save_config(self, values: dict) -> None:
        now = time.time()
        with self.connect() as conn:
            conn.executemany(
                "INSERT INTO config (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                [(k, json.dumps(v, ensure_ascii=False), now) for k, v in values.items()])

    # ---- cuadro de referencia ----------------------------------------------------------
    def save_reference(self, jpeg: bytes, width: int, height: int) -> None:
        self.enqueue("INSERT INTO reference_frame (id, ts, width, height, jpeg) VALUES (1, ?, ?, ?, ?) "
                     "ON CONFLICT(id) DO UPDATE SET ts = excluded.ts, width = excluded.width, "
                     "height = excluded.height, jpeg = excluded.jpeg",
                     (time.time(), width, height, jpeg))

    def get_reference(self) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT ts, width, height, jpeg FROM reference_frame WHERE id = 1").fetchone()

    # ---- eventos del procesador de métricas ------------------------------------------------
    def on_event(self, kind: str, d: dict) -> None:
        sid = self.session_id
        if kind == "track_start":
            self.enqueue("INSERT OR IGNORE INTO tracks (session_id, track_id, first_seen, color) VALUES (?, ?, ?, ?)",
                         (sid, d["track_id"], d["first_seen"], d.get("color")))
        elif kind == "track_end":
            self.enqueue("UPDATE tracks SET last_seen = ?, duration = ?, zones_json = ? "
                         "WHERE session_id = ? AND track_id = ?",
                         (d["last_seen"], d["duration"], json.dumps(d["zones"], ensure_ascii=False),
                          sid, d["track_id"]))
        elif kind == "line_event":
            self.enqueue("INSERT INTO line_events (session_id, track_id, direction, ts) VALUES (?, ?, ?, ?)",
                         (sid, d["track_id"], d["direction"], d["ts"]))
        elif kind == "zone_visit":
            self.enqueue("INSERT INTO zone_visits (session_id, track_id, zone_id, zone_name, enter_ts, exit_ts, "
                         "duration) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (sid, d["track_id"], d["zone_id"], d["zone"], d["enter"], d["exit"], d["duration"]))
        # ---- eventos de la fusión (tienda completa) ----
        elif kind == "global_start":
            self.enqueue("INSERT OR IGNORE INTO global_tracks (session_id, global_id, first_seen, color, changed_at) "
                         "VALUES (?, ?, ?, ?, ?)", (sid, d["global_id"], d["first_seen"], d.get("color"), time.time()))
        elif kind == "global_end":
            self.enqueue("UPDATE global_tracks SET last_seen = ?, duration = ?, cameras_json = ?, areas_json = ?, "
                         "is_buyer = ?, checkout_seconds = ?, stopped_any = ?, is_staff = ?, staff_reason = ?, "
                         "checkout_area_id = ?, checkout_area = ?, changed_at = ? WHERE session_id = ? AND global_id = ?",
                         (d["last_seen"], d["duration"], json.dumps(d["cameras"]),
                          json.dumps(d["areas"], ensure_ascii=False), int(bool(d.get("buyer"))),
                          d.get("checkout_seconds", 0), int(bool(d.get("stopped"))), int(bool(d.get("staff"))),
                          d.get("staff_reason"), d.get("checkout_area_id"), d.get("checkout_area"), time.time(),
                          sid, d["global_id"]))
        elif kind == "global_buyer":
            self.enqueue("UPDATE global_tracks SET is_buyer = 1, checkout_seconds = MAX(checkout_seconds, ?), "
                         "checkout_area_id = ?, checkout_area = ?, changed_at = ? WHERE session_id = ? AND global_id = ?",
                         (d["checkout_seconds"], d.get("checkout_area_id"), d.get("checkout_area"), time.time(),
                          sid, d["global_id"]))
        elif kind == "global_staff":
            self.enqueue("UPDATE global_tracks SET is_staff = 1, is_buyer = 0, staff_reason = ?, changed_at = ? "
                         "WHERE session_id = ? AND global_id = ?", (d["reason"], time.time(), sid, d["global_id"]))
        elif kind == "door_event":
            self.enqueue("INSERT INTO store_door_events (session_id, global_id, door_id, door_name, direction, ts) "
                         "VALUES (?, ?, ?, ?, ?, ?)",
                         (sid, d["global_id"], d["door_id"], d["door"], d["direction"], d["ts"]))
        elif kind == "track_link":
            self.enqueue("INSERT INTO track_links (session_id, camera_id, track_id, global_id, reason, ts) "
                         "VALUES (?, ?, ?, ?, ?, ?)",
                         (sid, d["camera_id"], d["track_id"], d["global_id"], d["reason"], d["ts"]))
        elif kind == "area_visit":
            self.enqueue("INSERT INTO area_visits (session_id, global_id, area_id, area_name, enter_ts, exit_ts, duration) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (sid, d["global_id"], d["area_id"], d["area"], d["enter"], d["exit"], d["duration"]))
        elif kind == "area_transition":
            self.enqueue("INSERT INTO area_transitions (session_id, global_id, from_id, from_name, to_id, to_name, ts) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (sid, d["global_id"], d["from_id"], d["from"], d["to_id"], d["to"], d["ts"]))

    def add_plan_heatmap(self, ts_start: float, ts_end: float, grid: np.ndarray, cell_m: float) -> None:
        self.enqueue("INSERT INTO plan_heatmap_snapshots (session_id, ts_start, ts_end, rows, cols, cell_m, grid) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (self.session_id, ts_start, ts_end, grid.shape[0], grid.shape[1], cell_m, pack_grid(grid)))

    def count_globals_since(self, ts: float) -> int:
        with self.connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM global_tracks WHERE first_seen >= ? AND is_staff = 0",
                                (ts,)).fetchone()[0]

    def count_buyers_since(self, ts: float) -> int:
        with self.connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM global_tracks WHERE first_seen >= ? AND is_buyer = 1 "
                                "AND is_staff = 0", (ts,)).fetchone()[0]

    def add_occupancy(self, ts: float, people: int, people_max: int, people_avg: float) -> None:
        self.enqueue("INSERT INTO occupancy_samples (session_id, ts, people, people_max, people_avg) "
                     "VALUES (?, ?, ?, ?, ?)", (self.session_id, ts, people, people_max, people_avg))

    def add_heatmap(self, ts_start: float, ts_end: float, grid: np.ndarray) -> None:
        self.enqueue("INSERT INTO heatmap_snapshots (session_id, ts_start, ts_end, rows, cols, grid) "
                     "VALUES (?, ?, ?, ?, ?, ?)",
                     (self.session_id, ts_start, ts_end, grid.shape[0], grid.shape[1], pack_grid(grid)))

    def count_tracks_since(self, ts: float) -> int:
        with self.connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM tracks WHERE first_seen >= ?", (ts,)).fetchone()[0]


class Recorder(threading.Thread):
    """Cada 5 s guarda la ocupación; cada 5 min, las grillas del mapa de calor (imagen y plano).

    Con fusión, la ocupación es la de la TIENDA (personas únicas vistas por cualquier
    cámara, sin duplicar las zonas superpuestas).
    """

    def __init__(self, db: Database, metrics, occupancy_every: float = 5.0, heatmap_every: float = 300.0,
                 fusion=None):
        super().__init__(name="muestreo", daemon=True)
        self.db, self.metrics, self.fusion = db, metrics, fusion
        self.occupancy_every, self.heatmap_every = occupancy_every, heatmap_every
        self._stop_event = threading.Event()
        self._heat_start = time.time()

    def _save_heatmap(self) -> None:
        now = time.time()
        grid = self.metrics.heatmap.take_pending()
        if grid.sum() > 0:
            self.db.add_heatmap(self._heat_start, now, grid)
        if self.fusion is not None:
            pgrid = self.fusion.take_plan_heatmap()
            if pgrid.sum() > 0:
                self.db.add_plan_heatmap(self._heat_start, now, pgrid, self.fusion.heatmap.cell)
        self._heat_start = now

    def run(self) -> None:
        next_heat = time.monotonic() + self.heatmap_every
        while not self._stop_event.wait(self.occupancy_every):
            if self.fusion is not None:
                self.fusion.tick(time.time())  # cierra globales aunque ninguna cámara vea a nadie
                people, pmax, pavg = self.fusion.take_occupancy_window()
                self.metrics.take_occupancy_window()
            else:
                people, pmax, pavg = self.metrics.take_occupancy_window()
            self.db.add_occupancy(time.time(), people, pmax, pavg)
            self.db.heartbeat()
            if time.monotonic() >= next_heat:
                self._save_heatmap()
                next_heat = time.monotonic() + self.heatmap_every

    def stop(self) -> None:
        self._stop_event.set()
        self.join(timeout=5)
        self._save_heatmap()  # lo que quedó del último intervalo
