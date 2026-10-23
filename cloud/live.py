"""Tiempo real y alertas en la sede principal.

- Cada tienda envía su estado en vivo cada pocos segundos (`/api/agent/live`); se guarda en memoria, el
  último por sede: personas ahora, posiciones en el plano, cajas, cámaras y alertas activas.
- Las alertas de la tienda (aforo, fila, cámaras) se abren y cierran en la tabla `alerts` según lleguen o
  dejen de llegar, así queda el historial.
- "Sede sin enviar datos" la decide la sede principal: una sede activa que lleva más de N minutos sin
  sincronizar (10 por defecto, configurable).
"""
from __future__ import annotations

import time

from fastapi import Depends, FastAPI, HTTPException, Request
from sqlalchemy import insert, select, update
from sqlalchemy.engine import Engine

from cloud.cuentas import org_settings, save_org_settings
from cloud.db import alerts, sites

LIVE_STALE_S = 30           # un estado en vivo más viejo que esto ya no es "en vivo"
DEFAULT_OFFLINE_MIN = 10
STORE_KINDS = ("aforo", "fila", "camara")


def offline_minutes(conn, org_id: int) -> int:
    return int(org_settings(conn, org_id).get("alert_offline_min") or DEFAULT_OFFLINE_MIN)


def sync_store_alerts(conn, site_id: int, current: list[dict], now: float) -> None:
    """Abre las alertas nuevas que manda la tienda y cierra las que ya no manda."""
    want = {(a.get("kind"), str(a.get("ref") or "")): a for a in current if a.get("kind") in STORE_KINDS}
    open_rows = conn.execute(select(alerts).where(alerts.c.site_id == site_id, alerts.c.ended_at.is_(None),
                                                  alerts.c.kind.in_(STORE_KINDS))).mappings().all()
    have = {(r["kind"], r["ref"]): r for r in open_rows}
    for key, r in have.items():
        if key not in want:
            conn.execute(update(alerts).where(alerts.c.id == r["id"]).values(ended_at=now))
        elif r["message"] != want[key].get("title"):
            conn.execute(update(alerts).where(alerts.c.id == r["id"]).values(message=str(want[key].get("title"))[:500]))
    for key, a in want.items():
        if key not in have:
            conn.execute(insert(alerts).values(site_id=site_id, kind=key[0], ref=key[1],
                                               message=str(a.get("title", ""))[:500],
                                               started_at=float(a.get("since") or now)))


def refresh_offline(conn, org_id: int, now: float | None = None) -> None:
    now = now or time.time()
    limit = offline_minutes(conn, org_id) * 60
    rows = conn.execute(select(sites.c.id, sites.c.name, sites.c.status, sites.c.last_sync_at)
                        .where(sites.c.org_id == org_id)).mappings().all()
    for s in rows:
        stale = s["status"] == "active" and s["last_sync_at"] is not None and now - s["last_sync_at"] > limit
        open_row = conn.execute(select(alerts.c.id).where(alerts.c.site_id == s["id"], alerts.c.kind == "sin_datos",
                                                          alerts.c.ended_at.is_(None))).first()
        if stale and not open_row:
            conn.execute(insert(alerts).values(site_id=s["id"], kind="sin_datos", ref="",
                                               message=f"{s['name']} no envía datos desde hace más de {limit // 60} min",
                                               started_at=s["last_sync_at"]))
        elif not stale and open_row:
            conn.execute(update(alerts).where(alerts.c.id == open_row.id).values(ended_at=now))


def register(app: FastAPI, engine: Engine, current_user, agent_site, visible_sites) -> None:
    app.state.live = {}

    def site_for(user: dict, sid: int) -> dict:
        _, rows = visible_sites(user, None if user["role"] != "admin" else _org_of_site(sid))
        site = next((s for s in rows if s["id"] == sid), None)
        if site is None:
            raise HTTPException(404, "Sede no encontrada.")
        return site

    def _org_of_site(sid: int) -> int | None:
        with engine.connect() as conn:
            return conn.execute(select(sites.c.org_id).where(sites.c.id == sid)).scalar()

    @app.post("/api/agent/live")
    async def agent_live(request: Request, site: dict = Depends(agent_site)):
        try:
            payload = await request.json()
        except ValueError as e:
            raise HTTPException(400, "El envío no es JSON válido.") from e
        if not isinstance(payload, dict):
            raise HTTPException(400, "El envío debe ser un objeto JSON.")
        now = time.time()
        payload["received_at"] = now
        app.state.live[site["id"]] = payload
        with engine.begin() as conn:
            conn.execute(update(sites).where(sites.c.id == site["id"]).values(last_sync_at=now))
            sync_store_alerts(conn, site["id"], payload.get("alerts") or [], now)
        return {"ok": True}

    @app.get("/api/sites/{sid}/live")
    def site_live(sid: int, user: dict = Depends(current_user)):
        site = site_for(user, sid)
        live = app.state.live.get(sid)
        fresh = bool(live and time.time() - live["received_at"] < LIVE_STALE_S)
        floorplan = None
        if site.get("floorplan_json"):
            import json
            floorplan = json.loads(site["floorplan_json"])
        return {"site": {"id": site["id"], "name": site["name"], "status": site["status"],
                         "last_sync_at": site["last_sync_at"]},
                "live": live if fresh else None, "floorplan": floorplan}

    @app.get("/api/alerts")
    def list_alerts(state: str = "open", site_id: int | None = None, limit: int = 100,
                    user: dict = Depends(current_user)):
        org, rows = visible_sites(user, _org_of_site(site_id) if user["role"] == "admin" and site_id else None)
        ids = [s["id"] for s in rows if site_id in (None, s["id"])]
        names = {s["id"]: s["name"] for s in rows}
        with engine.begin() as conn:
            refresh_offline(conn, org["id"])
            q = select(alerts).where(alerts.c.site_id.in_(ids)).order_by(alerts.c.started_at.desc()).limit(min(limit, 500))
            if state == "open":
                q = q.where(alerts.c.ended_at.is_(None))
            out = [dict(r) | {"site": names.get(r["site_id"], "")} for r in conn.execute(q).mappings()]
        return {"alerts": out}

    @app.post("/api/alerts/{aid}/ack")
    def ack_alert(aid: int, user: dict = Depends(current_user)):
        with engine.connect() as conn:
            row = conn.execute(select(alerts.c.site_id).where(alerts.c.id == aid)).first()
        if row is None:
            raise HTTPException(404, "Alerta no encontrada.")
        site_for(user, row.site_id)   # 404 si no es de una sede que puede ver
        with engine.begin() as conn:
            conn.execute(update(alerts).where(alerts.c.id == aid).values(ack_by=user["name"], ack_at=time.time()))
        return {"ok": True}

    @app.get("/api/manage/alerts-config")
    def get_alert_config(user: dict = Depends(current_user)):
        with engine.connect() as conn:
            return {"offline_min": offline_minutes(conn, user["org_id"])}

    @app.put("/api/manage/alerts-config")
    async def set_alert_config(request: Request, user: dict = Depends(current_user)):
        if user["role"] != "hq":
            raise HTTPException(403, "Solo los usuarios de la sede principal pueden hacer esto.")
        try:
            minutes = int((await request.json()).get("offline_min"))
        except (TypeError, ValueError) as e:
            raise HTTPException(400, "Escribe los minutos como número.") from e
        if not 2 <= minutes <= 1440:
            raise HTTPException(400, "Los minutos deben estar entre 2 y 1440.")
        with engine.begin() as conn:
            save_org_settings(conn, user["org_id"], alert_offline_min=minutes)
        return {"offline_min": minutes}
