"""Agente de sincronización con el servidor central (multisede, ver docs/MULTISEDE.md).

Cada 30 s envía al servidor lo nuevo de las tablas de la tienda. Si no hay internet, no se pierde
nada: la próxima vez sigue desde donde quedó (`cloud_link.cursors`). Solo salen números y
posiciones en el plano, nunca video ni imágenes.

- Tablas que solo crecen: se envían por id.
- `global_tracks` cambia después de insertarse (sale de la tienda, pasa por caja, se marca como
  personal): se envía por `changed_at`. Solo se leen filas con más de SETTLE_S segundos para no
  saltarse una escritura que todavía está en la cola del escritor.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import sqlite3
import threading
import time
import urllib.error
import urllib.request
import uuid

log = logging.getLogger("traffiqui.cloud")

AGENT_VERSION = "1.2"
INTERVAL_S = 30.0
LIVE_INTERVAL_S = 3.0      # estado en vivo (personas ahora, plano, cámaras, alertas), si la sede principal no dice otro
LIVE_MIN_S, LIVE_MAX_S = 1.0, 300.0   # la sede principal decide el ritmo (next_s) dentro de estos límites
LIVE_BACKOFF_S = 30.0      # si la sede principal no responde, se reintenta con calma
BATCH_ROWS = 2000
MAX_ROUNDS = 20      # lotes seguidos por ciclo al ponerse al día
SETTLE_S = 5.0
TIMEOUT_S = 20.0

APPEND_TABLES = ("store_door_events", "area_visits", "area_transitions", "occupancy_samples",
                 "plan_heatmap_snapshots")


class CloudError(Exception):
    """Error con un mensaje para mostrar en la pantalla de Configuración."""

    def __init__(self, message: str, blocked: bool = False):
        super().__init__(message)
        self.blocked = blocked   # la sede está suspendida, pendiente o la clave no vale


def _post(url: str, key: str, path: str, payload: dict) -> dict:
    req = urllib.request.Request(url.rstrip("/") + path, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read()).get("detail")
        except (ValueError, AttributeError):
            detail = None
        raise CloudError(detail or f"El servidor respondió con el error {e.code}.", blocked=e.code in (401, 403)) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise CloudError("No se pudo conectar con el servidor central. Se reintentará solo.") from e


class CloudSync(threading.Thread):
    def __init__(self, db, floorplan=lambda: None, interval: float = INTERVAL_S, post=_post, live=None):
        super().__init__(name="sincronización", daemon=True)
        self.db, self.floorplan, self.interval, self._post = db, floorplan, interval, post
        self.live = live   # función que devuelve el estado en vivo de la tienda (ver app/main.py)
        self._live_thread: threading.Thread | None = None
        self.live_interval = LIVE_INTERVAL_S   # lo ajusta la sede principal en cada respuesta
        self._stop_event = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.Lock()   # un solo envío a la vez
        self.state = {"state": "off", "message": "", "last_ok": None, "sent": 0}
        self._ensure_row()

    # ---- conexión guardada -------------------------------------------------------------
    def _conn(self) -> sqlite3.Connection:
        return self.db.connect()

    def _ensure_row(self) -> None:
        with self._conn() as c:
            c.execute("INSERT OR IGNORE INTO cloud_link (id, db_uid) VALUES (1, ?)", (str(uuid.uuid4()),))

    def link(self) -> dict:
        with self._conn() as c:
            return dict(c.execute("SELECT * FROM cloud_link WHERE id = 1").fetchone())

    def status(self) -> dict:
        lk = self.link()
        return {**self.state, "configured": bool(lk["url"] and lk["site_key"]), "url": lk["url"] or "",
                "site": lk["site_name"], "org": lk["org_name"],
                "key_hint": f"…{lk['site_key'][-4:]}" if lk["site_key"] else ""}

    def connect(self, url: str, key: str) -> dict:
        """Prueba la clave con el servidor y, si vale, la guarda. Empieza a enviar desde el principio."""
        url, key = url.strip().rstrip("/"), key.strip()
        if not url.startswith(("https://", "http://")):
            raise CloudError("La dirección del servidor debe empezar por https://")
        if not key.startswith("tqs_"):
            raise CloudError("La clave de sede empieza por «tqs_». Cópiala completa.")
        info = self._post(url, key, "/api/agent/hello", {})
        lk = self.link()
        same = lk["url"] == url and lk["site_key"] == key
        with self._conn() as c:
            c.execute("UPDATE cloud_link SET url = ?, site_key = ?, site_name = ?, org_name = ?"
                      + ("" if same else ", cursors = '{}'") + " WHERE id = 1",
                      (url, key, info.get("site"), info.get("org")))
        self.state.update(state="pending", message="Conectado. Enviando los datos…")
        self._wake.set()
        return self.status()

    def disconnect(self) -> None:
        with self._conn() as c:
            c.execute("UPDATE cloud_link SET url = NULL, site_key = NULL, site_name = NULL, org_name = NULL, "
                      "cursors = '{}' WHERE id = 1")
        self.state.update(state="off", message="", last_ok=None)

    def sync_now(self) -> None:
        self._wake.set()

    # ---- envío -------------------------------------------------------------------------
    def _rows(self, c: sqlite3.Connection, table: str, cur: dict) -> list[dict]:
        if table == "global_tracks":
            ts, gid = cur.get("global_tracks", [0.0, 0])
            rows = c.execute("SELECT * FROM global_tracks WHERE (changed_at > ? OR (changed_at = ? AND id > ?)) "
                             "AND changed_at < ? ORDER BY changed_at, id LIMIT ?",
                             (ts, ts, gid, time.time() - SETTLE_S, BATCH_ROWS)).fetchall()
        else:
            rows = c.execute(f"SELECT * FROM {table} WHERE id > ? ORDER BY id LIMIT ?",
                             (cur.get(table, 0), BATCH_ROWS)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d.pop("color", None)
            if "grid" in d:
                d["grid"] = base64.b64encode(d["grid"]).decode()
            out.append(d)
        return out

    def sync_once(self) -> int:
        """Envía lo pendiente. Devuelve cuántas filas se enviaron."""
        with self._lock:
            lk = self.link()
            if not (lk["url"] and lk["site_key"]):
                self.state.update(state="off", message="")
                return 0
            cur = json.loads(lk["cursors"] or "{}")
            self.db.flush(timeout=5)
            sent = 0
            try:
                for _ in range(MAX_ROUNDS):
                    with self._conn() as c:
                        tables = {t: self._rows(c, t, cur) for t in ("global_tracks", *APPEND_TABLES)}
                    payload = {"db_uid": lk["db_uid"], "agent_version": AGENT_VERSION,
                               "tables": {t: rows for t, rows in tables.items() if rows}}
                    plan = self.floorplan()
                    if plan:   # la imagen de fondo del croquis puede pesar MB y no hace falta en la sede principal
                        plan = {k: v for k, v in plan.items() if k != "background"}
                    plan_hash = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest() if plan else None
                    if plan_hash and plan_hash != cur.get("floorplan"):
                        payload["floorplan"] = plan
                    if not payload["tables"] and "floorplan" not in payload and sent:
                        break
                    self._post(lk["url"], lk["site_key"], "/api/agent/sync", payload)
                    for t, rows in tables.items():
                        if rows:
                            last = rows[-1]
                            cur[t] = [last["changed_at"], last["id"]] if t == "global_tracks" else last["id"]
                    if plan_hash:
                        cur["floorplan"] = plan_hash
                    with self._conn() as c:
                        c.execute("UPDATE cloud_link SET cursors = ? WHERE id = 1", (json.dumps(cur),))
                    n = sum(len(r) for r in tables.values())
                    sent += n
                    if all(len(r) < BATCH_ROWS for r in tables.values()):
                        break
            except CloudError as e:
                self.state.update(state="blocked" if e.blocked else "error", message=str(e))
                log.warning("Sincronización: %s", e)
                return sent
            self.state.update(state="ok", message="", last_ok=time.time(), sent=self.state["sent"] + sent)
            return sent

    def push_live(self) -> bool:
        """Envía el estado en vivo. Devuelve si llegó."""
        lk = self.link()
        if not (self.live and lk["url"] and lk["site_key"]) or self.state.get("state") == "blocked":
            return False
        try:
            r = self._post(lk["url"], lk["site_key"], "/api/agent/live", {"db_uid": lk["db_uid"], **self.live()})
            try:
                self.live_interval = min(LIVE_MAX_S, max(LIVE_MIN_S, float(r.get("next_s", LIVE_INTERVAL_S))))
            except (TypeError, ValueError, AttributeError):
                self.live_interval = LIVE_INTERVAL_S
            return True
        except CloudError as e:
            if e.blocked:
                self.state.update(state="blocked", message=str(e))
            return False
        except Exception:  # noqa: BLE001
            log.exception("Error preparando el estado en vivo")
            return False

    def _live_loop(self) -> None:
        while not self._stop_event.is_set():
            ok = self.push_live()
            self._stop_event.wait(self.live_interval if ok else LIVE_BACKOFF_S)

    def run(self) -> None:
        if self.live and self._live_thread is None:
            self._live_thread = threading.Thread(target=self._live_loop, name="en-vivo", daemon=True)
            self._live_thread.start()
        while not self._stop_event.is_set():
            try:
                self.sync_once()
            except Exception:  # noqa: BLE001 — el hilo nunca debe morir
                log.exception("Error inesperado en la sincronización")
                self.state.update(state="error", message="Error inesperado al sincronizar; se reintentará.")
            self._wake.wait(self.interval)
            self._wake.clear()

    def stop(self) -> None:
        self._stop_event.set()
        self._wake.set()
        self.join(timeout=TIMEOUT_S + 5)
