"""Parámetros del servidor central, leídos de variables de entorno."""
from __future__ import annotations

import os
from pathlib import Path

from app.config import DATA_DIR

ROOT = Path(__file__).resolve().parent.parent

# Instalado en el PC de la sede principal: SQLite junto a los datos de la app.
# Si algún día va a un servidor propio, PostgreSQL:
#   TRAFFIQUI_CLOUD_DB=postgresql+psycopg://usuario:clave@host/traffiqui
DATABASE_URL = os.environ.get("TRAFFIQUI_CLOUD_DB", f"sqlite:///{DATA_DIR / 'sede-principal.db'}")

# La cookie de sesión solo por HTTPS. En el PC de la sede principal se entra por http: desde el mismo
# PC o por Tailscale, que ya cifra todo el tráfico; ahí el arranque la desactiva (TRAFFIQUI_COOKIE_SECURE=0).
COOKIE_SECURE = os.environ.get("TRAFFIQUI_COOKIE_SECURE", "1") != "0"
SESSION_DAYS = 30
DEFAULT_TIMEZONE = "America/Caracas"

CONTACT = "Andrés Sandoval (0412 755 9087)"   # a quién llamar para activar o ampliar sedes

ONLINE_SECONDS = 120        # una sede está "en línea" si sincronizó hace menos de esto
MAX_ROWS_PER_TABLE = 5000   # por envío del agente
