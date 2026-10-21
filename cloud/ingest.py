"""Recepción de los lotes que envía el agente de cada sede."""
from __future__ import annotations

import base64
import json
import time

from sqlalchemy import update
from sqlalchemy.engine import Connection

from cloud import config
from cloud.db import SYNCED, sites


class IngestError(ValueError):
    pass


def _insert(conn: Connection, table):
    if conn.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return insert(table)


def _row(table, raw: dict, site_id: int, db_uid: str) -> dict:
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), int):
        raise IngestError("Cada fila necesita su id local.")
    allowed = {c.name for c in table.columns} - {"id", "site_id", "db_uid", "local_id"}
    row = {k: v for k, v in raw.items() if k in allowed}
    if "grid" in row:  # los blobs viajan en base64 dentro del JSON
        try:
            row["grid"] = base64.b64decode(row["grid"])
        except (ValueError, TypeError) as e:
            raise IngestError("Grilla del mapa de calor inválida.") from e
    return {**row, "site_id": site_id, "db_uid": db_uid, "local_id": raw["id"]}


def ingest(conn: Connection, site_id: int, payload: dict) -> dict:
    """Inserta o actualiza las filas recibidas. Devuelve cuántas se aplicaron por tabla."""
    db_uid = payload.get("db_uid")
    if not isinstance(db_uid, str) or not 8 <= len(db_uid) <= 36:
        raise IngestError("Falta el identificador de la base local (db_uid).")
    tables = payload.get("tables") or {}
    if not isinstance(tables, dict):
        raise IngestError("«tables» debe ser un objeto.")
    unknown = [t for t in tables if t not in SYNCED]
    if unknown:
        raise IngestError(f"Tablas desconocidas: {', '.join(unknown)}.")

    applied = {}
    for name, raw_rows in tables.items():
        if not isinstance(raw_rows, list):
            raise IngestError(f"«{name}» debe ser una lista.")
        if len(raw_rows) > config.MAX_ROWS_PER_TABLE:
            raise IngestError(f"Demasiadas filas en «{name}» (máximo {config.MAX_ROWS_PER_TABLE} por envío).")
        if not raw_rows:
            continue
        table = SYNCED[name]
        rows = [_row(table, r, site_id, db_uid) for r in raw_rows]
        # global_tracks se completa con el tiempo (sale, pasa por caja, se marca como personal):
        # las filas repetidas se actualizan; en el resto basta con ignorar las ya recibidas
        groups: dict[tuple, list[dict]] = {}   # una sentencia por cada juego de columnas, en lote
        for row in rows:
            groups.setdefault(tuple(sorted(row)), []).append(row)
        for keys, group in groups.items():
            stmt = _insert(conn, table)
            stmt = stmt.on_conflict_do_update(
                index_elements=["site_id", "db_uid", "local_id"],
                set_={k: stmt.excluded[k] for k in keys if k not in ("site_id", "db_uid", "local_id")})
            conn.execute(stmt, group)
        applied[name] = len(rows)

    values = {"last_sync_at": time.time()}
    if isinstance(payload.get("agent_version"), str):
        values["agent_version"] = payload["agent_version"][:32]
    if isinstance(payload.get("floorplan"), dict):
        values["floorplan_json"] = json.dumps(payload["floorplan"], ensure_ascii=False)
    conn.execute(update(sites).where(sites.c.id == site_id).values(**values))
    return applied
