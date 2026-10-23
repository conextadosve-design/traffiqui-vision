"""Cuentas: límite de intentos, recuperación de contraseña y correo saliente (SMTP).

- **Límite de intentos**: 5 fallos seguidos con un correo, o 20 desde una misma IP, en 15 minutos
  bloquean ese correo o esa IP durante 15 minutos.
- **Código de recuperación**: se muestra una sola vez al terminar el primer uso. Con él, un usuario de la
  sede principal pone una contraseña nueva aunque no haya correo configurado. Al usarlo se genera otro.
- **Correo** (opcional): si la sede principal configura su SMTP, "¿Olvidaste tu contraseña?" envía un
  enlace que vale 1 hora.
- La sede principal también puede poner una contraseña nueva a cualquier usuario de su empresa.
"""
from __future__ import annotations

import json
import secrets
import smtplib
import ssl
import time
from email.message import EmailMessage

from fastapi import Depends, FastAPI, HTTPException, Request
from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Engine

from cloud.db import login_attempts, organizations, password_resets, user_sessions, users
from cloud.security import hash_password, new_session_token, sha256

MAX_EMAIL_FAILURES = 5
MAX_IP_FAILURES = 20
WINDOW_S = 15 * 60
LOCK_S = 15 * 60
RESET_TTL_S = 3600
MIN_PASSWORD = 8


def new_recovery_code() -> str:
    raw = secrets.token_hex(8).upper()
    return "TQR-" + "-".join(raw[i:i + 4] for i in range(0, 16, 4))


def _norm_code(code: str) -> str:
    return code.strip().upper().replace(" ", "")


# ---- límite de intentos -------------------------------------------------------------------
def check_locked(conn, email: str, ip: str, now: float | None = None) -> None:
    now = now or time.time()
    for key in (f"email:{email}", f"ip:{ip}"):
        row = conn.execute(select(login_attempts).where(login_attempts.c.key == key)).mappings().first()
        if row and row["locked_until"] and row["locked_until"] > now:
            mins = max(1, round((row["locked_until"] - now) / 60))
            raise HTTPException(429, f"Demasiados intentos fallidos. Espera {mins} min y vuelve a intentarlo.")


def record_failure(conn, email: str, ip: str, now: float | None = None) -> None:
    now = now or time.time()
    for key, limit in ((f"email:{email}", MAX_EMAIL_FAILURES), (f"ip:{ip}", MAX_IP_FAILURES)):
        row = conn.execute(select(login_attempts).where(login_attempts.c.key == key)).mappings().first()
        if row is None or now - row["window_start"] > WINDOW_S:
            conn.execute(delete(login_attempts).where(login_attempts.c.key == key))
            conn.execute(insert(login_attempts).values(key=key, failures=1, window_start=now, locked_until=None))
            continue
        failures = row["failures"] + 1
        conn.execute(update(login_attempts).where(login_attempts.c.key == key).values(
            failures=failures, locked_until=now + LOCK_S if failures >= limit else row["locked_until"]))


def clear_failures(conn, email: str) -> None:
    conn.execute(delete(login_attempts).where(login_attempts.c.key == f"email:{email}"))


# ---- correo ------------------------------------------------------------------------------
def org_settings(conn, org_id: int) -> dict:
    raw = conn.execute(select(organizations.c.settings_json).where(organizations.c.id == org_id)).scalar()
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return {}


def save_org_settings(conn, org_id: int, **changes) -> dict:
    st = {**org_settings(conn, org_id), **changes}
    conn.execute(update(organizations).where(organizations.c.id == org_id).values(settings_json=json.dumps(st)))
    return st


def send_mail(smtp: dict, to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = smtp.get("from") or smtp["user"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    port = int(smtp.get("port") or 587)
    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(smtp["host"], port, context=ctx, timeout=20) as s:
            s.login(smtp["user"], smtp["password"])
            s.send_message(msg)
    else:
        with smtplib.SMTP(smtp["host"], port, timeout=20) as s:
            s.starttls(context=ctx)
            s.login(smtp["user"], smtp["password"])
            s.send_message(msg)


def _set_password(conn, user_id: int, password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise HTTPException(400, f"La contraseña debe tener al menos {MIN_PASSWORD} caracteres.")
    conn.execute(update(users).where(users.c.id == user_id).values(password_hash=hash_password(password)))
    conn.execute(delete(user_sessions).where(user_sessions.c.user_id == user_id))  # cierra sus otras sesiones


def register(app: FastAPI, engine: Engine, current_user, set_session) -> None:
    def mailer(*args):   # se resuelve al llamar: las pruebas pueden sustituir send_mail
        return send_mail(*args)

    def manager(user: dict = Depends(current_user)) -> dict:
        if user["role"] != "hq":
            raise HTTPException(403, "Solo los usuarios de la sede principal pueden hacer esto.")
        return user

    # ---- recuperar con el código de la sede principal ----------------------------------
    @app.post("/api/auth/recover")
    async def recover(request: Request):
        b = await request.json()
        email, code = str(b.get("email", "")).strip().lower(), _norm_code(str(b.get("code", "")))
        ip = request.client.host if request.client else ""
        with engine.begin() as conn:
            check_locked(conn, email, ip)
            user = conn.execute(select(users).where(users.c.email == email, users.c.active == 1,
                                                    users.c.role == "hq")).mappings().first()
            org = conn.execute(select(organizations).where(organizations.c.id == user["org_id"])).mappings().first() \
                if user else None
            if not org or not org["recovery_hash"] or sha256(code) != org["recovery_hash"]:
                record_failure(conn, email, ip)
                raise HTTPException(400, "El correo o el código de recuperación no son correctos.")
            _set_password(conn, user["id"], str(b.get("password", "")))
            new_code = new_recovery_code()   # el código usado deja de valer
            conn.execute(update(organizations).where(organizations.c.id == org["id"])
                         .values(recovery_hash=sha256(_norm_code(new_code))))
            clear_failures(conn, email)
        return {"ok": True, "recovery_code": new_code}

    # ---- olvidé mi contraseña (por correo) ---------------------------------------------
    @app.post("/api/auth/forgot")
    async def forgot(request: Request):
        email = str((await request.json()).get("email", "")).strip().lower()
        sent = False
        with engine.begin() as conn:
            user = conn.execute(select(users).where(users.c.email == email, users.c.active == 1)).mappings().first()
            smtp = org_settings(conn, user["org_id"]).get("smtp") if user and user["org_id"] else None
            if user and smtp:
                token = new_session_token()
                conn.execute(insert(password_resets).values(token_hash=sha256(token), user_id=user["id"],
                                                            expires_at=time.time() + RESET_TTL_S, used=0))
                link = f"{str(request.base_url).rstrip('/')}/restablecer#{token}"
                try:
                    mailer(smtp, email, "Traffiqui: restablecer tu contraseña",
                           f"Hola {user['name']}:\n\nPara poner una contraseña nueva abre este enlace "
                           f"(vale 1 hora):\n\n{link}\n\nSi no lo pediste, ignora este correo.\n")
                    sent = True
                except Exception:  # noqa: BLE001
                    pass
        # misma respuesta exista o no el correo: no revela quién tiene cuenta
        return {"ok": True, "email_configured": sent or None}

    @app.post("/api/auth/reset")
    async def reset(request: Request):
        b = await request.json()
        token = str(b.get("token", ""))
        with engine.begin() as conn:
            row = conn.execute(select(password_resets).where(password_resets.c.token_hash == sha256(token))
                               ).mappings().first()
            if not row or row["used"] or row["expires_at"] < time.time():
                raise HTTPException(400, "El enlace no es válido o ya caducó. Pide otro.")
            _set_password(conn, row["user_id"], str(b.get("password", "")))
            conn.execute(update(password_resets).where(password_resets.c.token_hash == row["token_hash"]).values(used=1))
        return {"ok": True}

    # ---- desde dentro del panel --------------------------------------------------------
    @app.post("/api/me/password")
    async def change_own(request: Request, user: dict = Depends(current_user)):
        from cloud.security import verify_password
        b = await request.json()
        if not verify_password(str(b.get("current", "")), user["password_hash"]):
            raise HTTPException(400, "La contraseña actual no es correcta.")
        with engine.begin() as conn:
            _set_password(conn, user["id"], str(b.get("password", "")))
        return {"ok": True}

    @app.post("/api/manage/users/{uid}/password")
    async def set_user_password(uid: int, request: Request, user: dict = Depends(manager)):
        password = str((await request.json()).get("password", ""))
        with engine.begin() as conn:
            target = conn.execute(select(users.c.id).where(users.c.id == uid, users.c.org_id == user["org_id"])).first()
            if not target:
                raise HTTPException(404, "Usuario no encontrado.")
            _set_password(conn, uid, password)
        return {"ok": True}

    @app.post("/api/manage/recovery-code")
    def regenerate_recovery(user: dict = Depends(manager)):
        code = new_recovery_code()
        with engine.begin() as conn:
            conn.execute(update(organizations).where(organizations.c.id == user["org_id"])
                         .values(recovery_hash=sha256(_norm_code(code))))
        return {"recovery_code": code}

    @app.get("/api/manage/smtp")
    def get_smtp(user: dict = Depends(manager)):
        with engine.connect() as conn:
            smtp = org_settings(conn, user["org_id"]).get("smtp") or {}
        return {k: smtp.get(k, "") for k in ("host", "port", "user", "from")} | {"configured": bool(smtp)}

    @app.put("/api/manage/smtp")
    async def set_smtp(request: Request, user: dict = Depends(manager)):
        b = await request.json()
        if not b.get("host"):
            with engine.begin() as conn:
                save_org_settings(conn, user["org_id"], smtp=None)
            return {"configured": False}
        with engine.connect() as conn:
            old = org_settings(conn, user["org_id"]).get("smtp") or {}
        smtp = {"host": str(b["host"]).strip(), "port": int(b.get("port") or 587), "user": str(b.get("user", "")).strip(),
                "password": str(b.get("password") or old.get("password", "")), "from": str(b.get("from", "")).strip()}
        try:
            mailer(smtp, user["email"], "Traffiqui: prueba de correo",
                   "Si recibes este correo, Traffiqui ya puede enviar avisos y enlaces para recuperar contraseñas.\n")
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"No se pudo enviar el correo de prueba: {e}") from e
        with engine.begin() as conn:
            save_org_settings(conn, user["org_id"], smtp=smtp)
        return {"configured": True}
