"""Copias de seguridad automáticas de C:\\ProgramData\\Traffiqui (tienda y sede principal).

Una vez al día se copia cada base SQLite con la API de copia en caliente de SQLite (segura aunque la
app esté escribiendo) y se guarda todo en un .zip:

    <datos>\\copias\\traffiqui-2026-10-23.zip

Se guardan las 7 últimas copias diarias y una por semana de las 4 semanas anteriores. Si se elige una
carpeta extra (un disco externo, una carpeta de OneDrive o Google Drive), cada copia se duplica allí con
la misma rotación: así sobrevive aunque se dañe el disco del PC.
"""
from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import tempfile
import threading
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

log = logging.getLogger("traffiqui.backup")

KEEP_DAILY = 7
KEEP_WEEKLY = 4
CHECK_EVERY_S = 3600
PREFIX = "traffiqui-"


class BackupManager:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.dir = self.data_dir / "copias"
        self.state_file = self.data_dir / "copias.json"
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- estado y configuración --------------------------------------------------------
    def _state(self) -> dict:
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_state(self, **changes) -> None:
        st = {**self._state(), **changes}
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")

    def status(self) -> dict:
        st = self._state()
        copies = sorted(self.dir.glob(f"{PREFIX}*.zip"), reverse=True) if self.dir.exists() else []
        return {"dir": str(self.dir), "extra_dir": st.get("extra_dir") or "", "last_ok": st.get("last_ok"),
                "last_error": st.get("last_error"), "last_file": st.get("last_file"),
                "copies": [{"name": p.name, "size": p.stat().st_size, "date": p.stem.removeprefix(PREFIX)}
                           for p in copies]}

    def set_extra_dir(self, path: str) -> dict:
        path = path.strip()
        if path:
            p = Path(path)
            try:
                p.mkdir(parents=True, exist_ok=True)
                probe = p / ".traffiqui-prueba"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink()
            except OSError as e:
                raise ValueError(f"No se puede escribir en «{path}»: {e.strerror or e}.") from e
        self._save_state(extra_dir=path)
        return self.status()

    # ---- copia -------------------------------------------------------------------------
    def run_now(self, today: date | None = None) -> Path:
        with self._lock:
            today = today or date.today()
            self.dir.mkdir(parents=True, exist_ok=True)
            dest = self.dir / f"{PREFIX}{today.isoformat()}.zip"
            try:
                with tempfile.TemporaryDirectory() as tmp:
                    tmp_zip = Path(tmp) / dest.name
                    with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                        for db in sorted(self.data_dir.glob("*.db")):
                            copy = Path(tmp) / db.name
                            src = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30)
                            dst = sqlite3.connect(copy)
                            try:
                                src.backup(dst)
                            finally:
                                dst.close()
                                src.close()
                            zf.write(copy, db.name)
                        for extra in ("modo.json",):
                            if (self.data_dir / extra).exists():
                                zf.write(self.data_dir / extra, extra)
                        zf.writestr("LEEME.txt", "Copia de Traffiqui. Para restaurar: cierra Traffiqui (icono de la "
                                    "bandeja > Salir), copia los archivos .db de este .zip a C:\\ProgramData\\Traffiqui "
                                    "reemplazando los actuales y vuelve a abrir Traffiqui.\n")
                    shutil.move(str(tmp_zip), dest)
                rotate(self.dir, today)
                extra = self._state().get("extra_dir")
                if extra:
                    Path(extra).mkdir(parents=True, exist_ok=True)
                    shutil.copy2(dest, Path(extra) / dest.name)
                    rotate(Path(extra), today)
            except Exception as e:  # noqa: BLE001 — se informa en el panel; se reintenta en la próxima hora
                self._save_state(last_error=f"{datetime.now():%d/%m %H:%M}: {e}")
                log.exception("Falló la copia de seguridad")
                raise
            self._save_state(last_ok=time.time(), last_error=None, last_file=dest.name)
            log.info("Copia de seguridad: %s", dest)
            return dest

    def due(self, today: date | None = None) -> bool:
        today = today or date.today()
        return not (self.dir / f"{PREFIX}{today.isoformat()}.zip").exists()

    # ---- hilo diario -------------------------------------------------------------------
    def start(self, first_delay: float = 120.0) -> None:
        def loop():
            if self._stop.wait(first_delay):   # deja arrancar la app antes de la primera copia
                return
            while not self._stop.is_set():
                if self.due():
                    try:
                        self.run_now()
                    except Exception:  # noqa: BLE001
                        pass
                self._stop.wait(CHECK_EVERY_S)
        self._thread = threading.Thread(target=loop, name="copias", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()


def rotate(folder: Path, today: date) -> list[Path]:
    """Deja las KEEP_DAILY copias más recientes y, de las anteriores, la última de cada semana
    (hasta KEEP_WEEKLY semanas). Devuelve las borradas."""
    dated = []
    for p in folder.glob(f"{PREFIX}*.zip"):
        try:
            dated.append((date.fromisoformat(p.stem.removeprefix(PREFIX)), p))
        except ValueError:
            continue
    dated.sort(reverse=True)
    keep = {p for _, p in dated[:KEEP_DAILY]}
    weeks: dict[tuple[int, int], Path] = {}
    for d, p in dated[KEEP_DAILY:]:
        wk = d.isocalendar()[:2]
        if wk not in weeks and d >= today - timedelta(weeks=KEEP_WEEKLY + 1):
            weeks[wk] = p
    keep |= set(list(weeks.values())[:KEEP_WEEKLY])
    removed = [p for _, p in dated if p not in keep]
    for p in removed:
        p.unlink(missing_ok=True)
    return removed
