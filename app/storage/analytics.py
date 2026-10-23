"""Consultas de analítica sobre SQLite: series por intervalo, zonas, mapa de calor y CSV."""
from __future__ import annotations

import csv
import io
import math
import time
from collections import defaultdict
from datetime import datetime

import cv2
import numpy as np

from app.storage.db import Database, unpack_grid
from app.vision.counting import ZoneStats, ZoneVisit, dwell_summary
from app.vision.heatmap import render

INK_BGR = (43, 32, 23)


# ---- rangos y buckets (en hora local) ---------------------------------------------------
def local_midnight(ts: float) -> float:
    d = datetime.fromtimestamp(ts)
    return d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


class RangeError(ValueError):
    """Rango inválido; el mensaje está en español para mostrarlo en la UI."""


def resolve_range(kind: str, start: str | None, end: str | None, now: float | None = None) -> tuple[float, float]:
    """'today' | 'hour' | 'week' (últimos 7 días) | 'month' (últimos 30 días) | 'custom'
    (start/end ISO local, p. ej. 2026-10-18T09:00). Semana y mes empiezan a medianoche e incluyen hoy."""
    now = now or time.time()
    if kind == "hour":
        return now - 3600, now
    if kind in ("week", "month"):
        days = 7 if kind == "week" else 30
        return local_midnight(now - (days - 1) * 86400), now
    if kind == "custom":
        if not start or not end:
            raise RangeError("Para un rango personalizado indica inicio y fin.")
        try:
            t0, t1 = datetime.fromisoformat(start).timestamp(), datetime.fromisoformat(end).timestamp()
        except ValueError:
            raise RangeError("Fecha inválida en el rango. Usa el formato AAAA-MM-DD HH:MM.") from None
        if t1 <= t0:
            raise RangeError("El fin del rango debe ser posterior al inicio.")
        return t0, t1
    return local_midnight(now), now


def bucket_start(ts: float, size_s: int) -> float:
    """Inicio del intervalo de `size_s` s que contiene `ts`, alineado al reloj local."""
    lt = time.localtime(ts)
    sec_of_day = lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec
    return math.floor(ts) - (sec_of_day % size_s)


def bucket_keys(t0: float, t1: float, size_s: int) -> list[float]:
    keys, k = [], bucket_start(t0, size_s)
    while k < t1 and len(keys) < 5000:
        keys.append(k)
        k += size_s
    return keys


# ---- consulta principal ------------------------------------------------------------------
def query(db: Database, t0: float, t1: float, bucket_minutes: int = 15, stop_seconds: float = 10.0) -> dict:
    size = int(bucket_minutes) * 60
    keys = bucket_keys(t0, t1, size)
    hour_keys = bucket_keys(t0, t1, 3600)
    with db.connect() as conn:
        occ = conn.execute("SELECT ts, people_max, people_avg FROM occupancy_samples "
                           "WHERE ts >= ? AND ts < ? ORDER BY ts", (t0, t1)).fetchall()
        # personas = IDs globales (sin duplicar re-entradas ni cámaras superpuestas); los datos
        # anteriores a la fusión solo tienen tracks por cámara
        tracks = conn.execute("SELECT first_seen, duration FROM global_tracks WHERE first_seen >= ? AND first_seen < ? "
                              "AND is_staff = 0", (t0, t1)).fetchall()
        if not tracks:
            tracks = conn.execute("SELECT first_seen, duration FROM tracks WHERE first_seen >= ? AND first_seen < ?",
                                  (t0, t1)).fetchall()
        lines = conn.execute("SELECT ts, direction FROM line_events WHERE ts >= ? AND ts < ?",
                             (t0, t1)).fetchall()
        visits = conn.execute("SELECT session_id, track_id, zone_id, zone_name, enter_ts, exit_ts "
                              "FROM zone_visits WHERE enter_ts >= ? AND enter_ts < ? ORDER BY enter_ts",
                              (t0, t1)).fetchall()

    occ_sum, occ_n, occ_max = defaultdict(float), defaultdict(int), defaultdict(int)
    peak, peak_at = 0, None
    for r in occ:
        k = bucket_start(r["ts"], size)
        occ_sum[k] += r["people_avg"]
        occ_n[k] += 1
        occ_max[k] = max(occ_max[k], r["people_max"])
        if r["people_max"] > peak:
            peak, peak_at = r["people_max"], r["ts"]

    unique = defaultdict(int)
    durations = []
    for r in tracks:
        unique[bucket_start(r["first_seen"], size)] += 1
        if r["duration"] is not None:
            durations.append(r["duration"])

    ins, outs = defaultdict(int), defaultdict(int)
    for r in lines:
        (ins if r["direction"] == "in" else outs)[bucket_start(r["ts"], 3600)] += 1

    # los track_id se repiten entre sesiones: la clave es (sesión, track)
    zstats: dict[str, ZoneStats] = defaultdict(ZoneStats)
    znames: dict[str, str] = {}
    for r in visits:
        znames[r["zone_id"]] = r["zone_name"]
        zstats[r["zone_id"]].add(ZoneVisit((r["session_id"], r["track_id"]), r["zone_id"],
                                           r["enter_ts"], r["exit_ts"]))

    return {
        "range": {"start": t0, "end": t1, "bucket_minutes": bucket_minutes},
        "totals": {
            "unique": len(tracks),
            "entries": len([r for r in lines if r["direction"] == "in"]),
            "exits": len([r for r in lines if r["direction"] == "out"]),
            "peak": peak,
            "peak_at": peak_at,
        },
        "occupancy": [{"t": k, "avg": round(occ_sum[k] / occ_n[k], 2) if occ_n[k] else None,
                       "max": occ_max[k] if occ_n[k] else None} for k in keys],
        "unique": [{"t": k, "count": unique[k]} for k in keys],
        "dwell": dwell_summary(durations),
        "line_by_hour": [{"t": k, "in": ins[k], "out": outs[k]} for k in hour_keys],
        "zones": [{"id": zid, "name": znames[zid], **zstats[zid].summary(stop_seconds)}
                  for zid in sorted(zstats, key=lambda z: znames[z].lower())],
    }


# ---- mapa de calor acumulado --------------------------------------------------------------
def heatmap_grid(db: Database, t0: float, t1: float, shape: tuple[int, int],
                 extra: np.ndarray | None = None) -> np.ndarray:
    """Suma las fotos de 5 min que terminan dentro del rango. `extra` = lo aún no guardado."""
    total = np.zeros(shape, np.float32)
    with db.connect() as conn:
        rows = conn.execute("SELECT grid FROM heatmap_snapshots WHERE ts_end > ? AND ts_start < ?",
                            (t0, t1)).fetchall()
    for r in rows:
        g = unpack_grid(r["grid"])
        if g.shape != shape:  # la resolución cambió: reescalar conservando el total
            s = g.sum()
            g = cv2.resize(g, (shape[1], shape[0]), interpolation=cv2.INTER_AREA)
            g = g * (s / g.sum()) if g.sum() > 0 else g
        total += g
    if extra is not None and extra.shape == shape:
        total += extra
    return total


def heatmap_png(db: Database, grid: np.ndarray, size: tuple[int, int]) -> bytes:
    ref = db.get_reference()
    w, h = size
    if ref is not None:
        base = cv2.imdecode(np.frombuffer(ref["jpeg"], np.uint8), cv2.IMREAD_COLOR)
        base = cv2.resize(base, (w, h))
        base = cv2.addWeighted(base, 0.75, np.zeros_like(base), 0.25, 0)  # atenuar para que resalte el calor
    else:
        base = np.full((h, w, 3), INK_BGR, np.uint8)
    out = render(base, grid, alpha=0.7)
    ok, buf = cv2.imencode(".png", out)
    return buf.tobytes()


# ---- CSV -----------------------------------------------------------------------------
def to_csv(data: dict, store: dict | None = None, buyers: dict | None = None, hourly: dict | None = None) -> str:
    """CSV con ';' (Excel en español) en dos secciones: intervalos y zonas."""
    out = io.StringIO()
    w = csv.writer(out, delimiter=";", lineterminator="\r\n")
    fmt = lambda ts: datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    num = lambda v: "" if v is None else str(v).replace(".", ",")
    w.writerow(["Traffiqui Vision", f"Desde {fmt(data['range']['start'])}", f"Hasta {fmt(data['range']['end'])}"])
    w.writerow([])
    w.writerow(["Inicio del intervalo", "Ocupación promedio", "Ocupación máxima", "Personas únicas nuevas"])
    for o, u in zip(data["occupancy"], data["unique"]):
        w.writerow([fmt(o["t"]), num(o["avg"]), num(o["max"]), u["count"]])
    w.writerow([])
    w.writerow(["Hora", "Entradas", "Salidas"])
    for r in data["line_by_hour"]:
        w.writerow([fmt(r["t"]), r["in"], r["out"]])
    w.writerow([])
    w.writerow(["Zona", "Pasaron", "Se detuvieron", "Tasa de detención", "Permanencia promedio (s)"])
    for z in data["zones"]:
        w.writerow([z["name"], z["passed"], z["stopped"], num(z["stop_rate"]), num(z["avg_dwell"])])
    w.writerow([])
    d = data["dwell"]
    w.writerow(["Permanencia promedio (s)", num(d["avg"]), "Mediana (s)", num(d["median"])])
    for label, n in d["buckets"].items():
        w.writerow([label, n])
    if store:
        w.writerow([])
        w.writerow(["Área del plano", "Tipo", "Pasaron", "Penetración", "Se detuvieron", "Tasa de detención",
                    "Permanencia promedio (s)"])
        for a in store["areas"]:
            w.writerow([a["name"], a["kind"], a["passed"], num(a["penetration"]), a["stopped"],
                        num(a["stop_rate"]), num(a["avg_dwell"])])
        w.writerow([])
        w.writerow(["Desde", "Hacia", "Personas"])
        for tr in store["transitions"]:
            w.writerow([tr["from"], tr["to"], tr["count"]])
        w.writerow([])
        w.writerow(["Recorrido frecuente", "Personas"])
        for p in store["paths"]:
            w.writerow([p["path"], p["count"]])
        hours = store["area_by_hour"]["hours"]
        if hours:
            w.writerow([])
            w.writerow(["Personas por área y hora"] + [fmt(h)[-5:] for h in hours])
            for row in store["area_by_hour"]["rows"]:
                w.writerow([row["name"]] + row["counts"])
    if buyers:
        g = buyers["groups"]
        w.writerow([])
        w.writerow([f"Pasaron por caja (>= {buyers['buyer_seconds']:g} s en cajas)", "Pasaron por caja", "No pasaron", "Total"])
        rows = [("Personas", "count"), ("% del total", "share"), ("Permanencia promedio (s)", "avg_dwell"),
                ("Permanencia mediana (s)", "median_dwell"), ("Áreas visitadas (promedio)", "avg_areas"),
                ("Se detuvieron en alguna área", "stop_rate"), ("Segundos en cajas (promedio)", "avg_checkout"),
                ("Todavía en la tienda", "in_progress")]
        for label, k in rows:
            w.writerow([label] + [num(g[x][k]) for x in ("buyers", "non_buyers", "total")])
        w.writerow(["% que pasó por caja", num(buyers["conversion"])])
        w.writerow([])
        w.writerow(["Área", "Pasaron por caja: visitaron el área", "% de los que pasaron por caja", "No pasaron: visitaron el área", "% de los que no pasaron"])
        for a in buyers["areas"]:
            w.writerow([a["name"], a["buyers"], num(a["buyers_pct"]), a["non_buyers"], num(a["non_buyers_pct"])])
        if buyers["doors"]:
            w.writerow([])
            w.writerow(["Puerta", "Entradas", "Salidas"])
            for d in buyers["doors"]:
                w.writerow([d["name"], d["in"], d["out"]])
        w.writerow([])
        w.writerow(["Hora", "Pasaron por caja", "No pasaron", "Entradas (puertas)", "Salidas (puertas)"])
        for r in buyers["by_hour"]:
            w.writerow([fmt(r["t"]), r["buyers"], r["non_buyers"], r["entries"], r["exits"]])
    if hourly:
        hrs = [f"{h:02d}h" for h in range(24)]
        w.writerow([])
        w.writerow([f"Personas que llegaron a la tienda por día y hora ({hourly['n_days']} días)"] + hrs + ["Total"])
        for d in hourly["days"]:
            w.writerow([d["label"]] + d["counts"] + [sum(d["counts"])])
        w.writerow([])
        w.writerow(["Promedio por día · hora pico por área", "Hora pico", "Promedio en la hora pico"] + hrs)
        st = hourly["store"]
        peak = lambda h: "" if h is None else f"{h:02d}:00–{h + 1:02d}:00"
        w.writerow(["Toda la tienda", peak(st["peak_hour"]), num(st["peak_avg"])] + [num(v) for v in st["avg_by_hour"]])
        for a in hourly["areas"]:
            w.writerow([a["name"], peak(a["peak_hour"]), num(a["peak_avg"])] + [num(v) for v in a["avg_by_hour"]])
    return out.getvalue()
