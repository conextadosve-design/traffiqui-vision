"""Informe completo de una sede para la sede principal: el mismo detalle que ve la tienda, desde lejos.

Sale de las tablas que sincroniza cada tienda: personas, áreas, recorridos, cajas, puertas y mapa de
calor del plano. El personal se excluye igual que en la tienda.
"""
from __future__ import annotations

import io
import statistics
from collections import Counter, defaultdict
from zoneinfo import ZoneInfo

import numpy as np
from sqlalchemy import select
from sqlalchemy.engine import Connection

from cloud.db import area_transitions, area_visits, door_events, global_tracks, plan_heatmaps
from cloud.reports import _buckets, _label, comparisons, site_summary

STOP_SECONDS = 10.0   # "se detuvo" en un área: igual que el valor por defecto de la tienda


def _staff(conn: Connection, site_id: int, t0: float, t1: float) -> set[tuple]:
    rows = conn.execute(select(global_tracks.c.db_uid, global_tracks.c.session_id, global_tracks.c.global_id)
                        .where(global_tracks.c.site_id == site_id, global_tracks.c.is_staff == 1,
                               global_tracks.c.last_seen >= t0 - 86400, global_tracks.c.first_seen < t1)).all()
    return {(r.db_uid, r.session_id, r.global_id) for r in rows}


def _heatmap(conn: Connection, site_id: int, t0: float, t1: float) -> dict | None:
    rows = conn.execute(select(plan_heatmaps.c.rows, plan_heatmaps.c.cols, plan_heatmaps.c.cell_m, plan_heatmaps.c.grid)
                        .where(plan_heatmaps.c.site_id == site_id, plan_heatmaps.c.ts_end > t0,
                               plan_heatmaps.c.ts_start < t1)).all()
    total, cell = None, None
    for r in rows:
        try:
            with np.load(io.BytesIO(r.grid)) as d:
                g = d["grid"].astype(np.float32)
        except (ValueError, OSError, KeyError):
            continue
        if total is None:
            total, cell = g, r.cell_m
        elif g.shape == total.shape:
            total += g
    if total is None or total.max() <= 0:
        return None
    norm = total / total.max()
    return {"rows": int(norm.shape[0]), "cols": int(norm.shape[1]), "cell_m": cell,
            "values": [round(float(v), 3) for v in norm.ravel()]}


def site_report(conn: Connection, site: dict, tz: str, t0: float, t1: float) -> dict:
    zone = ZoneInfo(tz)
    unit, buckets = _buckets(t0, t1, zone)
    sid = site["id"]
    summary = site_summary(conn, site, t0, t1, zone, unit, buckets)
    staff = _staff(conn, sid, t0, t1)

    # áreas: personas distintas, cuántas se detuvieron, permanencia
    per_area: dict[str, dict] = {}
    for r in conn.execute(select(area_visits).where(area_visits.c.site_id == sid, area_visits.c.enter_ts >= t0,
                                                    area_visits.c.enter_ts < t1)).mappings():
        who = (r["db_uid"], r["session_id"], r["global_id"])
        if who in staff:
            continue
        a = per_area.setdefault(r["area_name"], {"people": defaultdict(float)})
        a["people"][who] += r["duration"]
    areas = []
    for name, a in per_area.items():
        times = list(a["people"].values())
        stopped = sum(1 for t in times if t >= STOP_SECONDS)
        areas.append({"name": name, "people": len(times), "stopped": stopped,
                      "stop_rate": round(stopped / len(times), 3) if times else 0.0,
                      "avg_seconds": round(statistics.fmean(times), 1) if times else None})
    areas.sort(key=lambda a: a["people"], reverse=True)

    # recorridos A → B más frecuentes
    trans = Counter()
    for r in conn.execute(select(area_transitions).where(area_transitions.c.site_id == sid,
                                                         area_transitions.c.ts >= t0, area_transitions.c.ts < t1)).mappings():
        if (r["db_uid"], r["session_id"], r["global_id"]) not in staff:
            trans[(r["from_name"], r["to_name"])] += 1
    transitions = [{"from": a, "to": b, "count": n} for (a, b), n in trans.most_common(10)]

    # cajas: personas asignadas a cada caja y tiempo promedio en ella
    caja: dict[str, list[float]] = defaultdict(list)
    for r in conn.execute(select(global_tracks.c.checkout_area, global_tracks.c.checkout_seconds)
                          .where(global_tracks.c.site_id == sid, global_tracks.c.is_staff == 0,
                                 global_tracks.c.is_buyer == 1, global_tracks.c.first_seen >= t0,
                                 global_tracks.c.first_seen < t1)):
        caja[r.checkout_area or "Caja"].append(r.checkout_seconds or 0.0)
    total_caja = sum(len(v) for v in caja.values())
    checkouts = sorted(({"name": k, "people": len(v), "share": round(len(v) / total_caja, 3) if total_caja else 0,
                         "avg_seconds": round(statistics.fmean(v), 1)} for k, v in caja.items()),
                       key=lambda c: c["people"], reverse=True)

    # puertas
    doors: dict[str, dict] = defaultdict(lambda: {"in": 0, "out": 0})
    for r in conn.execute(select(door_events.c.door_name, door_events.c.direction)
                          .where(door_events.c.site_id == sid, door_events.c.ts >= t0, door_events.c.ts < t1)):
        doors[r.door_name][r.direction] += 1

    cmp = comparisons(conn, [sid], t0, t1, tz)
    return {
        "range": {"start": t0, "end": t1, "unit": unit, "timezone": tz},
        "labels": [_label(b, unit) for b in buckets],
        "summary": summary,
        "compare": cmp["sites"][sid],
        "areas": areas,
        "transitions": transitions,
        "checkouts": checkouts,
        "doors": [{"name": k, **v} for k, v in sorted(doors.items())],
        "heatmap": _heatmap(conn, sid, t0, t1),
    }
