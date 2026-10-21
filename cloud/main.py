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

from cloud import config
from cloud.db import make_engine, organizations, sites, user_sessions, users
from cloud.ingest import IngestError, ingest
from cloud.reports import RANGES, org_report, resolve_range
from cloud.security import new_session_token, sha256, verify_password

STATIC_DIR = Path(__file__).parent / "static"
CHART_JS = config.ROOT / "app" / "static" / "chart.umd.min.js"
APP_CSS = config.ROOT / "app" / "static" / "styles.css"   # misma identidad visual que la app de la tienda
COOKIE = "tq_session"

STATUS_MSG = {
    "pending": "Esta sede está pendiente de pago. Contacta con Traffiqui para activarla.",
    "suspended": "Esta sede está suspendida. Contacta con Traffiqui.",
}


def create_app(engine: Engine | None = None) -> FastAPI:
    engine = engine or make_engine()
    app = FastAPI(title="Traffiqui Cloud")
    app.state.engine = engine
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

    @app.post("/api/auth/login")
    async def login(request: Request, response: Response):
        body = await request.json()
        email = str(body.get("email", "")).strip().lower()
        password = str(body.get("password", ""))
        with engine.begin() as conn:
            user = conn.execute(select(users).where(users.c.email == email, users.c.active == 1)).mappings().first()
            if user is None or not verify_password(password, user["password_hash"]):
                raise HTTPException(401, "Correo o contraseña incorrectos.")
            token = new_session_token()
            now = time.time()
            conn.execute(insert(user_sessions).values(token_hash=sha256(token), user_id=user["id"], created_at=now,
                                                      expires_at=now + config.SESSION_DAYS * 86400))
            conn.execute(delete(user_sessions).where(user_sessions.c.expires_at < now))
        response.set_cookie(COOKIE, token, max_age=config.SESSION_DAYS * 86400, httponly=True, samesite="lax",
                            secure=config.COOKIE_SECURE)
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

    # ---- agente de cada sede ---------------------------------------------------------
    def agent_site(request: Request) -> dict:
        auth = request.headers.get("authorization", "")
        key = auth.removeprefix("Bearer ").strip()
        if not key.startswith("tqs_"):
            raise HTTPException(401, "Falta la clave de sede.")
        with engine.connect() as conn:
            row = conn.execute(
                select(sites, organizations.c.name.label("org_name"), organizations.c.timezone)
                .join(organizations, organizations.c.id == sites.c.org_id)
                .where(sites.c.key_hash == sha256(key))).mappings().first()
        if row is None:
            raise HTTPException(401, "Clave de sede no válida.")
        if row["status"] != "active":
            raise HTTPException(403, STATUS_MSG[row["status"]])
        return dict(row)

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
    @app.get("/")
    def index(request: Request):
        if not request.cookies.get(COOKIE):
            return RedirectResponse("/login")
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/login")
    def login_page():
        return FileResponse(STATIC_DIR / "login.html", headers={"Cache-Control": "no-cache"})

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
