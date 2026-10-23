"""Esquema del servidor central (SQLAlchemy Core: SQLite en desarrollo, PostgreSQL en producción).

  organizations   una empresa cliente; su "sede principal" son sus usuarios de gerencia y marketing
  sites           cada tienda: pendiente de pago → activa → (suspendida); clave del agente (hash)
  users           admin (Andrés), hq (sede principal: ve todas las sedes de su empresa), site (una sede)
  user_sessions   sesiones del panel web (se guarda el hash del token, nunca el token)

Datos que envía el agente de cada sede, copia de las tablas locales del mismo nombre. Cada fila se
identifica por (sede, base local, id local), así que reenviar un lote no duplica nada:

  global_tracks, door_events, area_visits, area_transitions, occupancy_samples, plan_heatmaps

Nunca se recibe video ni imágenes: solo números y posiciones en el plano.
"""
from __future__ import annotations

import time

from sqlalchemy import (Column, Float, ForeignKey, Index, Integer, LargeBinary, MetaData, String, Table, Text,
                        UniqueConstraint, create_engine, event, inspect, text)
from sqlalchemy.engine import Engine

from cloud import config

metadata = MetaData()

organizations = Table(
    "organizations", metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(200), nullable=False),
    Column("timezone", String(64), nullable=False, default=config.DEFAULT_TIMEZONE),
    Column("license_code", Text),   # código firmado por Traffiqui: cuántas sedes puede tener activas
    Column("recovery_hash", String(64)),   # código de recuperación de la sede principal (hash)
    Column("settings_json", Text),         # correo saliente (SMTP) y umbrales de alertas
    Column("created_at", Float, nullable=False, default=time.time),
)

SITE_STATUSES = ("pending", "active", "suspended")
sites = Table(
    "sites", metadata,
    Column("id", Integer, primary_key=True),
    Column("org_id", Integer, ForeignKey("organizations.id"), nullable=False, index=True),
    Column("name", String(200), nullable=False),
    Column("status", String(16), nullable=False, default="pending"),
    Column("key_hash", String(64), unique=True),   # sha256 de la clave del agente
    Column("key_hint", String(16)),                 # últimos caracteres, para reconocerla
    Column("payment_note", Text),                   # cómo y cuándo pagó (lo anota el administrador)
    Column("created_at", Float, nullable=False, default=time.time),
    Column("activated_at", Float),
    Column("last_sync_at", Float),
    Column("agent_version", String(32)),
    Column("floorplan_json", Text),
)

ROLES = ("admin", "hq", "site")
users = Table(
    "users", metadata,
    Column("id", Integer, primary_key=True),
    Column("org_id", Integer, ForeignKey("organizations.id")),   # NULL solo para admin
    Column("site_id", Integer, ForeignKey("sites.id")),          # solo para el rol "site"
    Column("email", String(254), nullable=False, unique=True),
    Column("name", String(200), nullable=False),
    Column("role", String(16), nullable=False),
    Column("password_hash", String(256), nullable=False),
    Column("active", Integer, nullable=False, default=1),
    Column("created_at", Float, nullable=False, default=time.time),
)

user_sessions = Table(
    "user_sessions", metadata,
    Column("token_hash", String(64), primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False, index=True),
    Column("created_at", Float, nullable=False),
    Column("expires_at", Float, nullable=False),
)

# intentos fallidos de inicio de sesión, por correo y por IP (clave "email:…" / "ip:…")
login_attempts = Table(
    "login_attempts", metadata,
    Column("key", String(300), primary_key=True),
    Column("failures", Integer, nullable=False, default=0),
    Column("window_start", Float, nullable=False),
    Column("locked_until", Float),
)

# enlaces de "olvidé mi contraseña" enviados por correo (hash del token, caducan en 1 h)
password_resets = Table(
    "password_resets", metadata,
    Column("token_hash", String(64), primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("expires_at", Float, nullable=False),
    Column("used", Integer, nullable=False, default=0),
)

# alertas de las sedes: abiertas (ended_at NULL) e historial
ALERT_KINDS = ("aforo", "fila", "camara", "sin_datos")
alerts = Table(
    "alerts", metadata,
    Column("id", Integer, primary_key=True),
    Column("site_id", Integer, ForeignKey("sites.id"), nullable=False, index=True),
    Column("kind", String(16), nullable=False),
    Column("ref", String(100), nullable=False, default=""),   # qué cámara o qué caja, si aplica
    Column("message", Text, nullable=False),
    Column("started_at", Float, nullable=False),
    Column("ended_at", Float),
    Column("ack_by", String(200)),
    Column("ack_at", Float),
)


def _synced(name: str, *cols: Column, ts: str) -> Table:
    """Tabla copiada de una sede: clave (site_id, db_uid, local_id) + índice por sede y tiempo."""
    return Table(
        name, metadata,
        Column("id", Integer, primary_key=True),
        Column("site_id", Integer, ForeignKey("sites.id"), nullable=False),
        Column("db_uid", String(36), nullable=False),
        Column("local_id", Integer, nullable=False),
        Column("session_id", Integer),
        *cols,
        UniqueConstraint("site_id", "db_uid", "local_id", name=f"uq_{name}_origin"),
        Index(f"ix_{name}_site_{ts}", "site_id", ts),
    )


global_tracks = _synced(
    "global_tracks",
    Column("global_id", Integer, nullable=False),
    Column("first_seen", Float, nullable=False),
    Column("last_seen", Float),
    Column("duration", Float),
    Column("cameras_json", Text),
    Column("areas_json", Text),
    Column("is_buyer", Integer, nullable=False, default=0),   # pasó por caja
    Column("checkout_seconds", Float, nullable=False, default=0),
    Column("stopped_any", Integer, nullable=False, default=0),
    Column("is_staff", Integer, nullable=False, default=0),
    Column("staff_reason", Text),
    Column("checkout_area_id", Text),
    Column("checkout_area", Text),
    ts="first_seen",
)
door_events = _synced(
    "door_events",
    Column("global_id", Integer, nullable=False),
    Column("door_id", Text, nullable=False),
    Column("door_name", Text, nullable=False),
    Column("direction", String(3), nullable=False),
    Column("ts", Float, nullable=False),
    ts="ts",
)
area_visits = _synced(
    "area_visits",
    Column("global_id", Integer, nullable=False),
    Column("area_id", Text, nullable=False),
    Column("area_name", Text, nullable=False),
    Column("enter_ts", Float, nullable=False),
    Column("exit_ts", Float, nullable=False),
    Column("duration", Float, nullable=False),
    ts="enter_ts",
)
area_transitions = _synced(
    "area_transitions",
    Column("global_id", Integer, nullable=False),
    Column("from_id", Text, nullable=False),
    Column("from_name", Text, nullable=False),
    Column("to_id", Text, nullable=False),
    Column("to_name", Text, nullable=False),
    Column("ts", Float, nullable=False),
    ts="ts",
)
occupancy_samples = _synced(
    "occupancy_samples",
    Column("ts", Float, nullable=False),
    Column("people", Integer, nullable=False),
    Column("people_max", Integer, nullable=False),
    Column("people_avg", Float, nullable=False),
    ts="ts",
)
plan_heatmaps = _synced(
    "plan_heatmaps",
    Column("ts_start", Float, nullable=False),
    Column("ts_end", Float, nullable=False),
    Column("rows", Integer, nullable=False),
    Column("cols", Integer, nullable=False),
    Column("cell_m", Float, nullable=False),
    Column("grid", LargeBinary, nullable=False),   # numpy comprimido, igual que en la sede
    ts="ts_end",
)

# nombre en el agente → tabla del servidor
SYNCED = {
    "global_tracks": global_tracks,
    "store_door_events": door_events,
    "area_visits": area_visits,
    "area_transitions": area_transitions,
    "occupancy_samples": occupancy_samples,
    "plan_heatmap_snapshots": plan_heatmaps,
}


def make_engine(url: str | None = None) -> Engine:
    url = url or config.DATABASE_URL
    if url.startswith("sqlite:///"):
        from pathlib import Path
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, future=True)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def _pragmas(conn, _):
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA foreign_keys = ON")
    metadata.create_all(engine)
    _add_missing_columns(engine)
    return engine


def _add_missing_columns(engine: Engine) -> None:
    """Columnas nuevas en tablas que ya existían (bases creadas por una versión anterior)."""
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in metadata.sorted_tables:
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in have and col.nullable:
                    conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} '
                                      f'{col.type.compile(engine.dialect)}'))
