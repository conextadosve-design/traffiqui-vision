"""Gestión desde el panel de la sede principal: primer uso, sedes, usuarios, licencia y dirección de conexión.

Pensado para el PC de la sede principal (instalado con Traffiqui.exe): no hace falta la terminal.
- El primer uso (crear la empresa y el primer usuario) solo se acepta desde el propio PC.
- Las sedes se crean activas mientras la licencia lo permita (ver cloud/licencia.py).
- La clave de una sede se muestra una sola vez, al crearla o al generar una nueva.
"""
from __future__ import annotations

import ipaddress
import socket
import subprocess
import time

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Engine

from cloud import config, licencia
from cloud.db import organizations, sites, users
from cloud.cuentas import _norm_code, new_recovery_code
from cloud.security import hash_password, new_site_key, sha256

TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


def license_state(org: dict) -> dict:
    allowed = licencia.allowed_sites(org.get("license_code"), org["name"])
    out = {"sites_allowed": allowed, "free_sites": licencia.FREE_SITES, "code": bool(org.get("license_code")),
           "contact": config.CONTACT}
    if org.get("license_code"):
        try:
            data = licencia.verify(org["license_code"], org["name"])
            out.update(issued=data.get("emitida"), expires=data.get("vence"))
        except licencia.LicenseError as e:
            out["error"] = str(e)
    return out


def licensed_site_ids(conn, org: dict) -> list[int]:
    """Sedes activas que entran en la licencia: las primeras en activarse."""
    allowed = licencia.allowed_sites(org.get("license_code"), org["name"])
    rows = conn.execute(select(sites.c.id).where(sites.c.org_id == org["id"], sites.c.status == "active")
                        .order_by(sites.c.activated_at, sites.c.id)).scalars().all()
    return list(rows[:allowed])


def addresses(port: int) -> list[dict]:
    """Direcciones de este PC que pueden usar las tiendas; primero las de Tailscale."""
    ips: set[str] = set()
    try:
        out = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=3)
        ips.update(line.strip() for line in out.stdout.splitlines() if line.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    found = []
    for ip in sorted(ips):
        addr = ipaddress.ip_address(ip)
        if addr.is_loopback:
            continue
        kind = "tailscale" if addr in TAILSCALE_NET else "local"
        found.append({"url": f"http://{ip}:{port}", "kind": kind})
    found.sort(key=lambda a: a["kind"] != "tailscale")
    return found


def register(app: FastAPI, engine: Engine, current_user, set_session) -> None:
    def org_of(conn, user: dict) -> dict:
        org = conn.execute(select(organizations).where(organizations.c.id == user["org_id"])).mappings().first()
        if org is None:
            raise HTTPException(404, "Empresa no encontrada.")
        return dict(org)

    def manager(user: dict = Depends(current_user)) -> dict:
        if user["role"] != "hq":
            raise HTTPException(403, "Solo los usuarios de la sede principal pueden hacer esto.")
        return user

    def site_of(conn, user: dict, sid: int) -> dict:
        row = conn.execute(select(sites).where(sites.c.id == sid, sites.c.org_id == user["org_id"])).mappings().first()
        if row is None:
            raise HTTPException(404, "Sede no encontrada.")
        return dict(row)

    def limit_error(org: dict) -> HTTPException:
        n = licencia.allowed_sites(org.get("license_code"), org["name"])
        return HTTPException(403, f"Tu licencia permite {n} sede{'s' if n != 1 else ''} activa{'s' if n != 1 else ''}. "
                                  f"Para agregar otra, contacta con {config.CONTACT} y pega aquí el código de licencia nuevo.")

    # ---- primer uso --------------------------------------------------------------------
    @app.get("/api/setup")
    def setup_needed():
        with engine.connect() as conn:
            return {"needed": conn.execute(select(func.count()).select_from(users)).scalar_one() == 0}

    @app.post("/api/setup")
    async def setup(request: Request, response: Response):
        if (request.client.host if request.client else "") not in LOCAL_HOSTS:
            raise HTTPException(403, "La configuración inicial solo se puede hacer desde el PC de la sede principal.")
        body = await request.json()
        empresa, nombre = str(body.get("empresa", "")).strip(), str(body.get("nombre", "")).strip()
        email, password = str(body.get("email", "")).strip().lower(), str(body.get("password", ""))
        if not empresa or not nombre or "@" not in email:
            raise HTTPException(400, "Completa el nombre de la empresa, tu nombre y tu correo.")
        if len(password) < 8:
            raise HTTPException(400, "La contraseña debe tener al menos 8 caracteres.")
        with engine.begin() as conn:
            if conn.execute(select(func.count()).select_from(users)).scalar_one():
                raise HTTPException(409, "La configuración inicial ya se hizo. Inicia sesión.")
            recovery = new_recovery_code()
            oid = conn.execute(insert(organizations).values(name=empresa, recovery_hash=sha256(_norm_code(recovery)))
                               ).inserted_primary_key[0]
            uid = conn.execute(insert(users).values(org_id=oid, email=email, name=nombre, role="hq",
                                                    password_hash=hash_password(password))).inserted_primary_key[0]
            set_session(conn, response, uid)
        return {"ok": True, "recovery_code": recovery}

    # ---- vista general -------------------------------------------------------------------
    @app.get("/api/manage")
    def overview(request: Request, user: dict = Depends(manager)):
        with engine.connect() as conn:
            org = org_of(conn, user)
            licensed = set(licensed_site_ids(conn, org))
            site_rows = [dict(r) for r in conn.execute(
                select(sites.c.id, sites.c.name, sites.c.status, sites.c.key_hint, sites.c.last_sync_at,
                       sites.c.agent_version, sites.c.activated_at)
                .where(sites.c.org_id == org["id"]).order_by(sites.c.id)).mappings()]
            user_rows = [dict(r) for r in conn.execute(
                select(users.c.id, users.c.name, users.c.email, users.c.role, users.c.site_id, users.c.active)
                .where(users.c.org_id == org["id"]).order_by(users.c.id)).mappings()]
        now = time.time()
        for s in site_rows:
            s["online"] = bool(s["last_sync_at"] and now - s["last_sync_at"] < config.ONLINE_SECONDS)
            s["over_license"] = s["status"] == "active" and s["id"] not in licensed
        port = request.url.port or 9000
        return {"org": {"name": org["name"], "license": license_state(org)}, "sites": site_rows,
                "users": user_rows, "me": user["id"], "addresses": addresses(port)}

    # ---- sedes ---------------------------------------------------------------------------
    @app.post("/api/manage/sites")
    async def create_site(request: Request, user: dict = Depends(manager)):
        name = str((await request.json()).get("name", "")).strip()
        if not name:
            raise HTTPException(400, "Escribe el nombre de la sede.")
        with engine.begin() as conn:
            org = org_of(conn, user)
            if len(licensed_site_ids(conn, org)) >= licencia.allowed_sites(org.get("license_code"), org["name"]):
                raise limit_error(org)
            key = new_site_key()
            sid = conn.execute(insert(sites).values(org_id=org["id"], name=name, status="active",
                                                    activated_at=time.time(), key_hash=sha256(key),
                                                    key_hint=key[-4:])).inserted_primary_key[0]
        return {"id": sid, "name": name, "key": key}

    @app.post("/api/manage/sites/{sid}/key")
    def regenerate_key(sid: int, user: dict = Depends(manager)):
        with engine.begin() as conn:
            site_of(conn, user, sid)
            key = new_site_key()
            conn.execute(update(sites).where(sites.c.id == sid).values(key_hash=sha256(key), key_hint=key[-4:]))
        return {"id": sid, "key": key}

    @app.post("/api/manage/sites/{sid}/suspend")
    def suspend_site(sid: int, user: dict = Depends(manager)):
        with engine.begin() as conn:
            site_of(conn, user, sid)
            conn.execute(update(sites).where(sites.c.id == sid).values(status="suspended"))
        return {"ok": True}

    @app.post("/api/manage/sites/{sid}/activate")
    def activate_site(sid: int, user: dict = Depends(manager)):
        with engine.begin() as conn:
            site = site_of(conn, user, sid)
            org = org_of(conn, user)
            if site["status"] != "active":
                if len(licensed_site_ids(conn, org)) >= licencia.allowed_sites(org.get("license_code"), org["name"]):
                    raise limit_error(org)
                conn.execute(update(sites).where(sites.c.id == sid).values(status="active", activated_at=time.time()))
        return {"ok": True}

    @app.post("/api/manage/license")
    async def set_license(request: Request, user: dict = Depends(manager)):
        code = str((await request.json()).get("code", "")).strip()
        with engine.begin() as conn:
            org = org_of(conn, user)
            try:
                data = licencia.verify(code, org["name"])
            except licencia.LicenseError as e:
                raise HTTPException(400, str(e)) from e
            conn.execute(update(organizations).where(organizations.c.id == org["id"]).values(license_code=code))
        return {"ok": True, "sites_allowed": data["sedes"]}

    # ---- copias de seguridad -------------------------------------------------------------
    def backup_manager():
        if app.state.backup is None:
            raise HTTPException(404, "Las copias de seguridad solo funcionan en el programa instalado.")
        return app.state.backup

    @app.get("/api/manage/backup")
    def backup_status(user: dict = Depends(manager)):
        return backup_manager().status()

    @app.post("/api/manage/backup/now")
    def backup_now(user: dict = Depends(manager)):
        bm = backup_manager()
        try:
            bm.run_now()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(500, f"No se pudo hacer la copia: {e}") from e
        return bm.status()

    @app.put("/api/manage/backup")
    async def backup_config(request: Request, user: dict = Depends(manager)):
        try:
            return backup_manager().set_extra_dir(str((await request.json()).get("extra_dir", "")))
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    # ---- usuarios ------------------------------------------------------------------------
    @app.post("/api/manage/users")
    async def create_user(request: Request, user: dict = Depends(manager)):
        b = await request.json()
        name, email = str(b.get("name", "")).strip(), str(b.get("email", "")).strip().lower()
        password, role = str(b.get("password", "")), b.get("role")
        if not name or "@" not in email:
            raise HTTPException(400, "Escribe el nombre y el correo.")
        if len(password) < 8:
            raise HTTPException(400, "La contraseña debe tener al menos 8 caracteres.")
        if role not in ("hq", "site"):
            raise HTTPException(400, "Elige el tipo de usuario.")
        with engine.begin() as conn:
            site_id = None
            if role == "site":
                site_id = site_of(conn, user, int(b.get("site_id") or 0))["id"]
            if conn.execute(select(users.c.id).where(users.c.email == email)).first():
                raise HTTPException(409, "Ya existe un usuario con ese correo.")
            uid = conn.execute(insert(users).values(org_id=user["org_id"], site_id=site_id, email=email, name=name,
                                                    role=role, password_hash=hash_password(password))
                               ).inserted_primary_key[0]
        return {"id": uid}

    @app.post("/api/manage/users/{uid}/active")
    async def set_user_active(uid: int, request: Request, user: dict = Depends(manager)):
        active = bool((await request.json()).get("active"))
        if uid == user["id"] and not active:
            raise HTTPException(400, "No puedes desactivar tu propio usuario.")
        with engine.begin() as conn:
            res = conn.execute(update(users).where(users.c.id == uid, users.c.org_id == user["org_id"])
                               .values(active=int(active)))
            if res.rowcount == 0:
                raise HTTPException(404, "Usuario no encontrado.")
        return {"ok": True}
