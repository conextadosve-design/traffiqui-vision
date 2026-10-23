"""Reporte consolidado de la sede principal: todas las sedes de la empresa, comparadas.

Las personas son las de `global_tracks` sin el personal (is_staff = 0), igual que en la app de la
tienda. "Pasaron por caja" = is_buyer: acumularon el tiempo configurado en la zona de cajas. No es
una compra: el sistema no ve los tickets.
"""
from __future__ import annotations

import statistics
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.engine import Connection

from cloud import config
from cloud.db import door_events, global_tracks, occupancy_samples

RANGES = ("today", "week", "month", "custom")


def resolve_range(range_: str, tz: str, start: str | None = None, end: str | None = None,
                  now: float | None = None) -> tuple[float, float]:
    """(t0, t1) en epoch. Hoy = desde la medianoche local; semana / mes = últimos 7 / 30 días con hoy;
    personalizado = fechas AAAA-MM-DD, ambas incluidas."""
    zone = ZoneInfo(tz)
    now = time.time() if now is None else now
    today = datetime.fromtimestamp(now, zone).replace(hour=0, minute=0, second=0, microsecond=0)
    if range_ == "today":
        return today.timestamp(), now
    if range_ == "week":
        return (today - timedelta(days=6)).timestamp(), now
    if range_ == "month":
        return (today - timedelta(days=29)).timestamp(), now
    if range_ == "custom":
        try:
            d0 = datetime.strptime(start or "", "%Y-%m-%d").replace(tzinfo=zone)
            d1 = datetime.strptime(end or "", "%Y-%m-%d").replace(tzinfo=zone) + timedelta(days=1)
        except ValueError as e:
            raise ValueError("Las fechas deben tener el formato AAAA-MM-DD.") from e
        if d1 <= d0:
            raise ValueError("La fecha final debe ser igual o posterior a la inicial.")
        if (d1 - d0).days > 366:
            raise ValueError("El rango máximo es de un año.")
        return d0.timestamp(), min(d1.timestamp(), now)
    raise ValueError("Rango no válido.")


def _buckets(t0: float, t1: float, zone: ZoneInfo) -> tuple[str, list[datetime]]:
    """Por hora si el rango cabe en ~1,5 días; si no, por día."""
    start = datetime.fromtimestamp(t0, zone)
    if t1 - t0 <= 36 * 3600:
        b = start.replace(minute=0, second=0, microsecond=0)
        step, unit = timedelta(hours=1), "hour"
    else:
        b = start.replace(hour=0, minute=0, second=0, microsecond=0)
        step, unit = timedelta(days=1), "day"
    out = []
    while b.timestamp() < t1:
        out.append(b)
        b = b + step  # aritmética de reloj local: un día = misma hora del día siguiente
    return unit, out


def _label(b: datetime, unit: str) -> str:
    return b.strftime("%H:%M") if unit == "hour" else b.strftime("%d/%m")


def _key(ts: float, unit: str, zone: ZoneInfo) -> datetime:
    d = datetime.fromtimestamp(ts, zone)
    d = d.replace(minute=0, second=0, microsecond=0)
    return d if unit == "hour" else d.replace(hour=0)


def site_summary(conn: Connection, site: dict, t0: float, t1: float, zone: ZoneInfo, unit: str,
                 buckets: list[datetime]) -> dict:
    rows = conn.execute(
        select(global_tracks.c.first_seen, global_tracks.c.duration, global_tracks.c.last_seen,
               global_tracks.c.is_buyer)
        .where(global_tracks.c.site_id == site["id"], global_tracks.c.is_staff == 0,
               global_tracks.c.first_seen >= t0, global_tracks.c.first_seen < t1)).all()
    visits = len(rows)
    buyers = sum(1 for r in rows if r.is_buyer)
    dwell = [r.duration for r in rows if r.duration is not None and r.last_seen is not None]
    by_hour = Counter(datetime.fromtimestamp(r.first_seen, zone).hour for r in rows)
    peak = max(by_hour.items(), key=lambda kv: (kv[1], -kv[0]))[0] if by_hour else None
    series = Counter(_key(r.first_seen, unit, zone) for r in rows)

    entries = conn.execute(
        select(func.count()).select_from(door_events)
        .where(door_events.c.site_id == site["id"], door_events.c.direction == "in",
               door_events.c.ts >= t0, door_events.c.ts < t1)).scalar_one()
    occ_max = conn.execute(
        select(func.max(occupancy_samples.c.people_max))
        .where(occupancy_samples.c.site_id == site["id"], occupancy_samples.c.ts >= t0,
               occupancy_samples.c.ts < t1)).scalar_one()

    last = site.get("last_sync_at")
    return {
        "id": site["id"], "name": site["name"], "status": site["status"],
        "online": bool(last and time.time() - last < config.ONLINE_SECONDS),
        "last_sync_at": last,
        "visits": visits,
        "checkout": buyers,
        "checkout_rate": round(buyers / visits, 3) if visits else 0.0,
        "avg_dwell": round(statistics.fmean(dwell), 1) if dwell else None,
        "median_dwell": round(statistics.median(dwell), 1) if dwell else None,
        "peak_hour": peak,
        "peak_hour_visits": by_hour.get(peak, 0) if peak is not None else 0,
        "entries": entries,
        "max_occupancy": occ_max or 0,
        "series": [series.get(b, 0) for b in buckets],
        "by_hour_of_day": [by_hour.get(h, 0) for h in range(24)],
    }


def org_report(conn: Connection, site_rows: list[dict], tz: str, t0: float, t1: float) -> dict:
    zone = ZoneInfo(tz)
    unit, buckets = _buckets(t0, t1, zone)
    per_site = [site_summary(conn, s, t0, t1, zone, unit, buckets) for s in site_rows]
    per_site.sort(key=lambda s: s["visits"], reverse=True)

    visits = sum(s["visits"] for s in per_site)
    checkout = sum(s["checkout"] for s in per_site)
    hours = [sum(s["by_hour_of_day"][h] for s in per_site) for h in range(24)]
    peak = max(range(24), key=lambda h: (hours[h], -h)) if visits else None
    # permanencia promedio ponderada por las visitas con permanencia conocida de cada sede
    weighted = defaultdict(float)
    for s in per_site:
        if s["avg_dwell"] is not None:
            weighted["sum"] += s["avg_dwell"] * s["visits"]
            weighted["n"] += s["visits"]
    return {
        "range": {"start": t0, "end": t1, "unit": unit, "timezone": tz},
        "labels": [_label(b, unit) for b in buckets],
        "totals": {
            "visits": visits,
            "checkout": checkout,
            "checkout_rate": round(checkout / visits, 3) if visits else 0.0,
            "avg_dwell": round(weighted["sum"] / weighted["n"], 1) if weighted["n"] else None,
            "peak_hour": peak,
            "entries": sum(s["entries"] for s in per_site),
            "sites_active": sum(1 for s in per_site if s["status"] == "active"),
            "sites_online": sum(1 for s in per_site if s["online"] and s["status"] == "active"),
            "sites_pending": sum(1 for s in per_site if s["status"] == "pending"),
            "by_hour_of_day": hours,
        },
        "sites": per_site,
    }
