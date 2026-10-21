"""Contraseñas (scrypt), tokens de sesión y claves de sede. Solo biblioteca estándar."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

_N, _R, _P = 2 ** 14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, dk = stored.split("$")
        if algo != "scrypt":
            return False
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                             dklen=len(base64.b64decode(dk)))
        return hmac.compare_digest(got, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def new_site_key() -> str:
    """Clave que se pega en la app de la tienda. Se muestra una sola vez; se guarda su hash."""
    return "tqs_" + secrets.token_urlsafe(32)
