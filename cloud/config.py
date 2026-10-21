"""Parámetros del servidor central, leídos de variables de entorno."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# SQLite para desarrollo y pruebas; en producción, PostgreSQL:
#   TRAFFIQUI_CLOUD_DB=postgresql+psycopg://usuario:clave@host/traffiqui
DATABASE_URL = os.environ.get("TRAFFIQUI_CLOUD_DB", f"sqlite:///{ROOT / 'data' / 'cloud.db'}")

# la cookie de sesión solo viaja por HTTPS (desactivar únicamente en desarrollo local)
COOKIE_SECURE = os.environ.get("TRAFFIQUI_COOKIE_SECURE", "1") != "0"
SESSION_DAYS = 30
DEFAULT_TIMEZONE = "America/Caracas"

ONLINE_SECONDS = 120        # una sede está "en línea" si sincronizó hace menos de esto
MAX_ROWS_PER_TABLE = 5000   # por envío del agente
