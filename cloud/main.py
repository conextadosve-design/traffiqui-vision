"""Traffiqui Cloud: panel de la sede principal y recepción de datos de las sedes.

Arranque en desarrollo:
    TRAFFIQUI_COOKIE_SECURE=0 python -m cloud.main --port 9000
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, insert, select
from sqlalchemy.engine import Engine

from cloud import config, cuentas, live, manage
from cloud.db import make_engine, organizations, sites, user_sessions, users
from cloud.ingest import IngestError, ingest
from cloud.reports import RANGES, org_report, resolve_range
from cloud.site_reports import site_report
from cloud.security import new_session_token, sha256, verify_password

STATIC_DIR = Path(__file__).parent / "static"
CHART_JS = config.ROOT / "app" / "static" / "chart.umd.min.js"
APP_CSS = config.ROOT / "app" / "static" / "styles.css"   # misma identidad visual que la app de la tienda
COOKIE = "tq_session"

STATUS_MSG = {
    "pending": f"Esta sede está pendiente de activación. Contacta con {config.CONTACT}.",
    "suspended": "Esta sede está suspendida. La sede principal puede reactivarla desde su panel.",
}


def create_app(engine: Engine | None = None, backup=None) -> FastAPI:
    engine = engine or make_engine()
    app = FastAPI(title="Traffiqui Cloud")
    app.state.engine = engine
    app.state.backup = backup   # app.backup.BackupManager en el PC de la sede principal
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # ---- usuarios y sesiones ---------------------------------------------------------
    def current_user(request: Request) -> dict:
        token = request.cookies.get(COOKIE)
        if not token:
            raise HTTPException(401, "Inicia sesión.")
        with engine.connect() as conn:
            row = conn.execute(
                select(users).join(user_sessions, user_sessions.c.user_id == users.c.id)
                .where(user_sessions.c.token_hash == sha256(token), user_sessions.c.expires_at > time.time(),
                       users.c.active == 1)).mappings().first()
        if row is None:
            raise HTTPException(401, "La sesión caducó. Vuelve a iniciar sesión.")
        return dict(row)

    def visible_sites(user: dict, org_id: int | None = None) -> tuple[dict, list[dict]]:
        """(empresa, sedes) que el usuario puede ver. El admin elige empresa; los demás, la suya."""
        if user["role"] == "admin":
            if org_id is None:
                raise HTTPException(400, "Elige una empresa.")
        else:
            org_id = user["org_id"]
        with engine.connect() as conn:
            org = conn.execute(select(organizations).where(organizations.c.id == org_id)).mappings().first()
            if org is None:
                raise HTTPException(404, "Empresa no encontrada.")
            q = select(sites).where(sites.c.org_id == org_id).order_by(sites.c.name)
            if user["role"] == "site":
                q = q.where(sites.c.id == user["site_id"])
            rows = [dict(r) for r in conn.execute(q).mappings()]
        return dict(org), rows

    def set_session(conn, response: Response, user_id: int) -> None:
        token = new_session_token()
        now = time.time()
        conn.execute(insert(user_sessions).values(token_hash=sha256(token), user_id=user_id, created_at=now,
                                                  expires_at=now + config.SESSION_DAYS * 86400))
        conn.execute(delete(user_sessions).where(user_sessions.c.expires_at < now))
        response.set_cookie(COOKIE, token, max_age=config.SESSION_DAYS * 86400, httponly=True, samesite="lax",
                            secure=config.COOKIE_SECURE)

    @app.post("/api/auth/login")
    async def login(request: Request, response: Response):
        body = await request.json()
        email = str(body.get("email", "")).strip().lower()
        password = str(body.get("password", ""))
        ip = request.client.host if request.client else ""
        with engine.begin() as conn:
            cuentas.check_locked(conn, email, ip)
            user = conn.execute(select(users).where(users.c.email == email, users.c.active == 1)).mappings().first()
            ok = user is not None and verify_password(password, user["password_hash"])
            if not ok:
                cuentas.record_failure(conn, email, ip)
            else:
                cuentas.clear_failures(conn, email)
                set_session(conn, response, user["id"])
        if not ok:   # fuera de la transacción: el intento fallido queda guardado
            raise HTTPException(401, "Correo o contraseña incorrectos.")
        return {"ok": True}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response):
        token = request.cookies.get(COOKIE)
        if token:
            with engine.begin() as conn:
                conn.execute(delete(user_sessions).where(user_sessions.c.token_hash == sha256(token)))
        response.delete_cookie(COOKIE)
        return {"ok": True}

    @app.get("/api/me")
    def me(user: dict = Depends(current_user)):
        out = {k: user[k] for k in ("id", "name", "email", "role", "org_id", "site_id")}
        with engine.connect() as conn:
            if user["role"] == "admin":
                out["orgs"] = [dict(r) for r in conn.execute(
                    select(organizations.c.id, organizations.c.name).order_by(organizations.c.name)).mappings()]
            else:
                org = conn.execute(select(organizations.c.name).where(organizations.c.id == user["org_id"])).first()
                out["org_name"] = org.name if org else ""
        return out

    # ---- reporte consolidado ---------------------------------------------------------
    @app.get("/api/report")
    def report(range: str = "today", start: str | None = None, end: str | None = None,
               org_id: int | None = None, user: dict = Depends(current_user)):
        if range not in RANGES:
            raise HTTPException(400, "Rango no válido.")
        org, rows = visible_sites(user, org_id)
        try:
            t0, t1 = resolve_range(range, org["timezone"], start, end)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        with engine.connect() as conn:
            rep = org_report(conn, rows, org["timezone"], t0, t1)
        rep["org"] = {"id": org["id"], "name": org["name"]}
        return rep

    @app.get("/api/sites/{sid}/report")
    def one_site_report(sid: int, range: str = "today", start: str | None = None, end: str | None = None,
                        user: dict = Depends(current_user)):
        if range not in RANGES:
            raise HTTPException(400, "Rango no válido.")
        with engine.connect() as conn:
            org_id = conn.execute(select(sites.c.org_id).where(sites.c.id == sid)).scalar()
        org, rows = visible_sites(user, org_id if user["role"] == "admin" else None)
        site = next((s for s in rows if s["id"] == sid), None)
        if site is None:
            raise HTTPException(404, "Sede no encontrada.")
        try:
            t0, t1 = resolve_range(range, org["timezone"], start, end)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        with engine.connect() as conn:
            rep = site_report(conn, site, org["timezone"], t0, t1)
        rep["site"] = {"id": site["id"], "name": site["name"], "status": site["status"]}
        return rep

    # ---- agente de cada sede ---------------------------------------------------------
    def agent_site(request: Request) -> dict:
        auth = request.headers.get("authorization", "")
        key = auth.removeprefix("Bearer ").strip()
        if not key.startswith("tqs_"):
            raise HTTPException(401, "Falta la clave de sede.")
        with engine.connect() as conn:
            row = conn.execute(
                select(sites, organizations.c.name.label("org_name"), organizations.c.timezone,
                       organizations.c.license_code)
                .join(organizations, organizations.c.id == sites.c.org_id)
                .where(sites.c.key_hash == sha256(key))).mappings().first()
            if row is None:
                raise HTTPException(401, "Clave de sede no válida.")
            if row["status"] != "active":
                raise HTTPException(403, STATUS_MSG[row["status"]])
            org = {"id": row["org_id"], "name": row["org_name"], "license_code": row["license_code"]}
            if row["id"] not in manage.licensed_site_ids(conn, org):
                raise HTTPException(403, f"Esta sede no entra en la licencia de la empresa. Contacta con {config.CONTACT}.")
        return dict(row)

    live.register(app, engine, current_user, agent_site, visible_sites)

    @app.post("/api/agent/hello")
    def agent_hello(site: dict = Depends(agent_site)):
        return {"site": site["name"], "org": site["org_name"], "timezone": site["timezone"],
                "server_time": time.time()}

    @app.post("/api/agent/sync")
    async def agent_sync(request: Request, site: dict = Depends(agent_site)):
        try:
            payload = await request.json()
        except ValueError as e:
            raise HTTPException(400, "El envío no es JSON válido.") from e
        if not isinstance(payload, dict):
            raise HTTPException(400, "El envío debe ser un objeto JSON.")
        try:
            with engine.begin() as conn:
                applied = ingest(conn, site["id"], payload)
        except IngestError as e:
            raise HTTPException(400, str(e)) from e
        return {"ok": True, "applied": applied}

    # ---- páginas ---------------------------------------------------------------------
    manage.register(app, engine, current_user, set_session)
    cuentas.register(app, engine, current_user, set_session)

    def page(name: str) -> FileResponse:
        return FileResponse(STATIC_DIR / name, headers={"Cache-Control": "no-cache"})

    def needs_setup() -> bool:
        with engine.connect() as conn:
            return conn.execute(select(users.c.id).limit(1)).first() is None

    @app.get("/")
    def index(request: Request):
        if needs_setup():
            return RedirectResponse("/setup")
        if not request.cookies.get(COOKIE):
            return RedirectResponse("/login")
        return page("index.html")

    @app.get("/sede/{sid}")
    def site_page(sid: int, request: Request):
        if not request.cookies.get(COOKIE):
            return RedirectResponse("/login")
        return page("sede.html")

    @app.get("/sedes")
    def sites_page(request: Request):
        if not request.cookies.get(COOKIE):
            return RedirectResponse("/login")
        return page("sedes.html")

    @app.get("/login")
    def login_page():
        return RedirectResponse("/setup") if needs_setup() else page("login.html")

    @app.get("/recuperar")
    def recover_page():
        return page("recuperar.html")

    @app.get("/restablecer")
    def reset_page():
        return page("recuperar.html")

    @app.get("/setup")
    def setup_page():
        return page("setup.html") if needs_setup() else RedirectResponse("/login")

    @app.get("/vendor/chart.umd.min.js")
    def chart_js():
        return FileResponse(CHART_JS, media_type="text/javascript")

    @app.get("/vendor/styles.css")
    def app_css():
        return FileResponse(APP_CSS, media_type="text/css", headers={"Cache-Control": "no-cache"})

    return app


def main() -> None:
    import uvicorn
    ap = argparse.ArgumentParser(description="Traffiqui Cloud")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9000)
    args = ap.parse_args()
    uvicorn.run(create_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
