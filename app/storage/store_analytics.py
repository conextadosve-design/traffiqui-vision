"""Analítica de la tienda completa (todas las cámaras, IDs globales, plano en metros)."""
from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta

import cv2
import numpy as np

from app.storage.analytics import bucket_keys, bucket_start
from app.storage.db import Database, unpack_grid
from app.vision.counting import ZoneStats, ZoneVisit, dwell_summary


# excluye al personal en tablas con (session_id, global_id); `x` es el alias de la tabla
NOT_STAFF = ("NOT EXISTS (SELECT 1 FROM global_tracks s WHERE s.session_id = x.session_id "
             "AND s.global_id = x.global_id AND s.is_staff = 1)")


def _area_hours(hour_keys: list[float], by_hour: dict, ranking: list[dict], span: float) -> dict:
    """Hasta 36 h: una columna por hora del rango. Más largo: 24 columnas por hora del día (suma de los días)."""
    if span <= 36 * 3600:
        return {"mode": "hours", "hours": hour_keys,
                "rows": [{"id": a["id"], "name": a["name"], "counts": [by_hour[a["id"]][h] for h in hour_keys]} for a in ranking]}
    rows = []
    for a in ranking:
        counts = [0] * 24
        for hk, n in by_hour[a["id"]].items():
            counts[time.localtime(hk).tm_hour] += n
        rows.append({"id": a["id"], "name": a["name"], "counts": counts})
    return {"mode": "hour_of_day", "hours": list(range(24)), "rows": rows}


def store_query(db: Database, t0: float, t1: float, areas: list[dict], stop_seconds: float = 10.0) -> dict:
    """`areas` = áreas del plano actual (para listar también las que no tuvieron visitas). Sin personal."""
    with db.connect() as conn:
        globals_ = conn.execute("SELECT session_id, global_id, first_seen, duration, areas_json FROM global_tracks "
                                "WHERE first_seen >= ? AND first_seen < ? AND is_staff = 0", (t0, t1)).fetchall()
        visits = conn.execute("SELECT session_id, global_id, area_id, area_name, enter_ts, exit_ts FROM area_visits x "
                              f"WHERE enter_ts >= ? AND enter_ts < ? AND {NOT_STAFF} ORDER BY enter_ts", (t0, t1)).fetchall()
        trans = conn.execute(f"SELECT from_name, to_name FROM area_transitions x WHERE ts >= ? AND ts < ? AND {NOT_STAFF}",
                             (t0, t1)).fetchall()
        links = conn.execute("SELECT reason, COUNT(*) AS n FROM track_links WHERE ts >= ? AND ts < ? GROUP BY reason",
                             (t0, t1)).fetchall()

    unique = len(globals_)
    durations = [r["duration"] for r in globals_ if r["duration"] is not None]

    stats: dict[str, ZoneStats] = defaultdict(ZoneStats)
    names = {a["id"]: a["name"] for a in areas}
    kinds = {a["id"]: a.get("kind", "pasillo") for a in areas}
    hour_keys = bucket_keys(t0, t1, 3600)
    by_hour: dict[str, Counter] = defaultdict(Counter)
    seen_hour: set = set()
    for r in visits:
        names.setdefault(r["area_id"], r["area_name"])
        key = (r["session_id"], r["global_id"])
        stats[r["area_id"]].add(ZoneVisit(key, r["area_id"], r["enter_ts"], r["exit_ts"]))
        hk = bucket_start(r["enter_ts"], 3600)
        if (key, r["area_id"], hk) not in seen_hour:  # personas distintas por hora, no visitas
            seen_hour.add((key, r["area_id"], hk))
            by_hour[r["area_id"]][hk] += 1

    ranking = []
    for aid in set(names) | set(stats):
        s = stats[aid].summary(stop_seconds)
        ranking.append({"id": aid, "name": names.get(aid, aid), "kind": kinds.get(aid, "pasillo"), **s,
                        "penetration": round(s["passed"] / unique, 3) if unique else 0.0})
    ranking.sort(key=lambda a: (-a["passed"], a["name"].lower()))

    transitions = Counter((r["from_name"], r["to_name"]) for r in trans)
    paths = Counter()
    for r in globals_:
        seq = json.loads(r["areas_json"] or "[]")
        if len(seq) >= 2:
            paths[" → ".join(seq[:6])] += 1

    reasons = {r["reason"]: r["n"] for r in links}
    relinked = sum(n for k, n in reasons.items() if k != "nueva")
    return {
        "range": {"start": t0, "end": t1},
        "totals": {"unique": unique, "avg_dwell": dwell_summary(durations)["avg"],
                   "median_dwell": dwell_summary(durations)["median"]},
        "dwell": dwell_summary(durations),
        "areas": ranking,
        "transitions": [{"from": a, "to": b, "count": n} for (a, b), n in transitions.most_common(15)],
        "paths": [{"path": p, "count": n} for p, n in paths.most_common(10)],
        "area_by_hour": _area_hours(hour_keys, by_hour, ranking, t1 - t0),
        "reid": {"by_reason": reasons, "relinked": relinked,
                 "local_tracks": sum(reasons.values()),
                 "note": "Tracks locales unidos a una persona ya conocida (traspaso entre cámaras, "
                         "superposición o re-entrada) en vez de contarse como personas nuevas."},
    }


def plan_heatmap_grid(db: Database, t0: float, t1: float, shape: tuple[int, int],
                      extra: np.ndarray | None = None) -> np.ndarray:
    total = np.zeros(shape, np.float32)
    with db.connect() as conn:
        rows = conn.execute("SELECT rows, cols, grid FROM plan_heatmap_snapshots WHERE ts_end > ? AND ts_start < ?",
                            (t0, t1)).fetchall()
    for r in rows:
        g = unpack_grid(r["grid"])
        if g.shape == shape:  # si el local cambió de tamaño, las fotos viejas no encajan en la grilla
            total += g
    if extra is not None and extra.shape == shape:
        total += extra
    return total


def grid_payload(grid: np.ndarray, cell_m: float, width: float, depth: float, sigma: float = 1.0) -> dict:
    """Grilla suavizada y normalizada (0–1) para pintarla como textura en el navegador."""
    g = grid.astype(np.float32)
    if g.max() > 0:
        g = cv2.GaussianBlur(g, (0, 0), sigma)
        g = g / g.max()
    return {"rows": int(g.shape[0]), "cols": int(g.shape[1]), "cell": cell_m, "width": width, "depth": depth,
            "total": float(grid.sum()), "values": [round(float(v), 3) for v in g.flatten()]}


# ---- pasaron por caja vs. no pasaron ---------------------------------------------------------
def _group(rows: list, total: int) -> dict:
    ended = [r for r in rows if r["duration"] is not None]
    durations = [r["duration"] for r in ended]
    n = len(rows)
    d = dwell_summary(durations)
    # áreas DISTINTAS: el recorrido puede repetir un área si la persona va y vuelve
    areas_per = [len(set(json.loads(r["areas_json"] or "[]"))) for r in ended]
    return {
        "count": n,
        "share": round(n / total, 3) if total else 0.0,
        "in_progress": n - len(ended),  # todavía en la tienda (sin permanencia final)
        "avg_dwell": d["avg"], "median_dwell": d["median"], "dwell_buckets": d["buckets"],
        "avg_areas": round(sum(areas_per) / len(areas_per), 1) if areas_per else 0.0,
        "stop_rate": round(sum(1 for r in rows if r["stopped_any"]) / n, 3) if n else 0.0,
        "avg_checkout": round(sum(r["checkout_seconds"] or 0 for r in rows) / n, 1) if n else 0.0,
    }


def _by_day(people: list, t0: float, t1: float) -> list[dict]:
    days = day_list(t0, t1)
    idx = {d["date"]: i for i, d in enumerate(days)}
    out = [{"date": d["date"], "label": d["label"], "buyers": 0, "non_buyers": 0} for d in days]
    for r in people:
        day, _ = _day_hour(r["first_seen"])
        if day in idx:
            out[idx[day]]["buyers" if r["is_buyer"] else "non_buyers"] += 1
    return out


def buyers_query(db: Database, t0: float, t1: float, areas: list[dict], buyer_seconds: float = 20.0) -> dict:
    with db.connect() as conn:
        people = conn.execute("SELECT session_id, global_id, first_seen, duration, areas_json, is_buyer, "
                              "checkout_seconds, stopped_any, checkout_area_id FROM global_tracks "
                              "WHERE first_seen >= ? AND first_seen < ? AND is_staff = 0", (t0, t1)).fetchall()
        staff = conn.execute("SELECT staff_reason, COUNT(*) AS n FROM global_tracks WHERE first_seen >= ? AND first_seen < ? "
                             "AND is_staff = 1 GROUP BY staff_reason", (t0, t1)).fetchall()
        visits = conn.execute("SELECT DISTINCT session_id, global_id, area_id, area_name FROM area_visits x "
                              f"WHERE enter_ts >= ? AND enter_ts < ? AND {NOT_STAFF}", (t0, t1)).fetchall()
        caja_ids = [a["id"] for a in areas if a.get("kind") == "caja"]
        caja_visits = conn.execute(
            "SELECT session_id, global_id, area_id, area_name, SUM(duration) AS secs FROM area_visits x "
            f"WHERE enter_ts >= ? AND enter_ts < ? AND {NOT_STAFF} AND area_id IN ({','.join('?' * len(caja_ids)) or 'NULL'}) "
            "GROUP BY session_id, global_id, area_id", (t0, t1, *caja_ids)).fetchall()
        doors = conn.execute("SELECT door_id, door_name, direction, ts FROM store_door_events x "
                             f"WHERE ts >= ? AND ts < ? AND {NOT_STAFF}", (t0, t1)).fetchall()

    total = len(people)
    buyers = [r for r in people if r["is_buyer"]]
    others = [r for r in people if not r["is_buyer"]]
    is_buyer = {(r["session_id"], r["global_id"]): bool(r["is_buyer"]) for r in people}

    # pasillos que visita cada grupo (penetración dentro del grupo)
    names = {a["id"]: a["name"] for a in areas}
    kinds = {a["id"]: a.get("kind", "pasillo") for a in areas}
    seen = defaultdict(lambda: [0, 0])  # area -> [pasaron por caja, no pasaron]
    for v in visits:
        key = (v["session_id"], v["global_id"])
        if key not in is_buyer:
            continue
        names.setdefault(v["area_id"], v["area_name"])
        seen[v["area_id"]][0 if is_buyer[key] else 1] += 1
    nb, nn = len(buyers), len(others)
    compare = []
    for aid in names:
        b, o = seen[aid]
        compare.append({"id": aid, "name": names[aid], "kind": kinds.get(aid, "pasillo"), "buyers": b, "non_buyers": o,
                        "buyers_pct": round(b / nb, 3) if nb else 0.0, "non_buyers_pct": round(o / nn, 3) if nn else 0.0})
    compare.sort(key=lambda a: (-(a["buyers"] + a["non_buyers"]), a["name"].lower()))

    hours = bucket_keys(t0, t1, 3600)
    hb, ho = Counter(), Counter()
    for r in people:
        (hb if r["is_buyer"] else ho)[bucket_start(r["first_seen"], 3600)] += 1

    door_rows = defaultdict(lambda: {"in": 0, "out": 0})
    door_names = {}
    din, dout = Counter(), Counter()
    for r in doors:
        door_rows[r["door_id"]][r["direction"]] += 1
        door_names[r["door_id"]] = r["door_name"]
        (din if r["direction"] == "in" else dout)[bucket_start(r["ts"], 3600)] += 1

    # cada caja por separado: su zona de cliente, quién pasó, cuánto esperó y cuántas personas se le asignan
    attributed = Counter(r["checkout_area_id"] for r in buyers if r["checkout_area_id"])
    per_caja: dict[str, dict] = {aid: {"people": 0, "secs": [], "name": names.get(aid, aid)} for aid in caja_ids}
    for v in caja_visits:
        c = per_caja.setdefault(v["area_id"], {"people": 0, "secs": [], "name": v["area_name"]})
        c["people"] += 1
        c["secs"].append(v["secs"] or 0)
    checkouts = []
    for aid, c in per_caja.items():
        s = c["secs"]
        checkouts.append({"id": aid, "name": c["name"], "people": c["people"], "buyers": attributed.get(aid, 0),
                          "avg_seconds": round(sum(s) / len(s), 1) if s else 0.0,
                          "share": round(attributed.get(aid, 0) / nb, 3) if nb else 0.0})
    checkouts.sort(key=lambda c: (-c["buyers"], c["name"].lower()))

    return {
        "range": {"start": t0, "end": t1},
        "buyer_seconds": buyer_seconds,
        "has_checkout": any(a.get("kind") == "caja" for a in areas),
        "checkouts": checkouts,
        "staff": {"count": sum(r["n"] for r in staff), "by_reason": {r["staff_reason"] or "personal": r["n"] for r in staff}},
        "conversion": round(nb / total, 3) if total else 0.0,
        "groups": {"buyers": _group(buyers, total), "non_buyers": _group(others, total), "total": _group(people, total)},
        "by_hour": [{"t": h, "buyers": hb[h], "non_buyers": ho[h], "entries": din[h], "exits": dout[h]} for h in hours],
        # para semana / mes: por día y por hora del día (suma de todos los días del rango)
        "by_day": _by_day(people, t0, t1),
        "by_hour_of_day": [{"hour": h, "buyers": sum(n for k, n in hb.items() if time.localtime(k).tm_hour == h),
                            "non_buyers": sum(n for k, n in ho.items() if time.localtime(k).tm_hour == h)} for h in range(24)],
        "areas": compare,
        "doors": [{"id": k, "name": door_names[k], **v} for k, v in door_rows.items()],
        "entries": sum(v["in"] for v in door_rows.values()),
        "exits": sum(v["out"] for v in door_rows.values()),
    }


# ---- tráfico por hora de cada día ---------------------------------------------------------------
WEEKDAYS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
MAX_DAYS = 62


def _day_hour(ts: float) -> tuple[str, int]:
    lt = time.localtime(ts)
    return f"{lt.tm_year:04d}-{lt.tm_mon:02d}-{lt.tm_mday:02d}", lt.tm_hour


def day_list(t0: float, t1: float) -> list[dict]:
    """Días locales del rango (como máximo los últimos 62)."""
    days, d = [], datetime.fromtimestamp(t0).replace(hour=0, minute=0, second=0, microsecond=0)
    end = datetime.fromtimestamp(max(t0, t1 - 1))
    while d.date() <= end.date():
        days.append({"date": d.strftime("%Y-%m-%d"), "weekday": d.weekday(),
                     "label": f"{WEEKDAYS[d.weekday()]} {d.day:02d}/{d.month:02d}"})
        d += timedelta(days=1)
    return days[-MAX_DAYS:]


def _peak(counts: list[float]) -> tuple[int | None, float]:
    best = max(range(24), key=lambda h: counts[h]) if any(counts) else None
    return best, (counts[best] if best is not None else 0)


def hourly_query(db: Database, t0: float, t1: float, areas: list[dict], area_id: str = "store",
                 metric: str = "people") -> dict:
    """Personas por día y hora (0–23) para la tienda o un área, y la hora pico de cada área.

    people = personas distintas que entraron (a la tienda o al área) en esa hora;
    buyers = solo las que terminaron pasando por caja. El personal nunca cuenta.
    """
    days = day_list(t0, t1)
    t0 = datetime.strptime(days[0]["date"], "%Y-%m-%d").timestamp() if days else t0
    only_buyers = metric == "buyers"
    with db.connect() as conn:
        people = conn.execute("SELECT session_id, global_id, first_seen, is_buyer FROM global_tracks "
                              "WHERE first_seen >= ? AND first_seen < ? AND is_staff = 0", (t0, t1)).fetchall()
        visits = conn.execute("SELECT x.session_id, x.global_id, x.area_id, x.area_name, x.enter_ts FROM area_visits x "
                              f"WHERE x.enter_ts >= ? AND x.enter_ts < ? AND {NOT_STAFF}", (t0, t1)).fetchall()
    buyer = {(r["session_id"], r["global_id"]): bool(r["is_buyer"]) for r in people}
    day_idx = {d["date"]: i for i, d in enumerate(days)}

    # toda la tienda: por hora de llegada
    store = [[0] * 24 for _ in days]
    for r in people:
        if only_buyers and not r["is_buyer"]:
            continue
        day, h = _day_hour(r["first_seen"])
        if day in day_idx:
            store[day_idx[day]][h] += 1

    # cada área: personas distintas que entraron en esa hora (una persona que va y vuelve cuenta una vez por hora)
    names = {a["id"]: a["name"] for a in areas}
    kinds = {a["id"]: a.get("kind", "pasillo") for a in areas}
    per_area: dict[str, list[list[int]]] = {aid: [[0] * 24 for _ in days] for aid in names}
    seen = set()
    for v in visits:
        key = (v["session_id"], v["global_id"])
        if only_buyers and not buyer.get(key):
            continue
        day, h = _day_hour(v["enter_ts"])
        if day not in day_idx or (key, v["area_id"], day, h) in seen:
            continue
        seen.add((key, v["area_id"], day, h))
        names.setdefault(v["area_id"], v["area_name"])
        per_area.setdefault(v["area_id"], [[0] * 24 for _ in days])[day_idx[day]][h] += 1

    n_days = max(1, len(days))
    wd_count = Counter(d["weekday"] for d in days)

    def summarize(matrix):
        by_hour = [sum(row[h] for row in matrix) for h in range(24)]
        avg = [round(v / n_days, 2) for v in by_hour]
        wk = [[0.0] * 24 for _ in range(7)]
        for d, row in zip(days, matrix):
            for h in range(24):
                wk[d["weekday"]][h] += row[h]
        wk = [[round(wk[w][h] / wd_count[w], 2) if wd_count[w] else None for h in range(24)] for w in range(7)]
        peak_h, _ = _peak(by_hour)
        return {"by_hour": by_hour, "avg_by_hour": avg, "weekday_avg": wk, "total": sum(by_hour),
                "peak_hour": peak_h, "peak_avg": avg[peak_h] if peak_h is not None else 0,
                "top_hours": sorted([h for h in range(24) if by_hour[h]], key=lambda h: -by_hour[h])[:3]}

    selected = store if area_id == "store" else per_area.get(area_id, [[0] * 24 for _ in days])
    profiles = []
    for aid, m in per_area.items():
        s = summarize(m)
        profiles.append({"id": aid, "name": names.get(aid, aid), "kind": kinds.get(aid, "pasillo"),
                         "by_hour": s["by_hour"], "avg_by_hour": s["avg_by_hour"], "total": s["total"],
                         "peak_hour": s["peak_hour"], "peak_avg": s["peak_avg"], "top_hours": s["top_hours"]})
    profiles.sort(key=lambda p: (-p["total"], p["name"].lower()))
    return {
        "range": {"start": t0, "end": t1},
        "area_id": area_id,
        "area_name": "Toda la tienda" if area_id == "store" else names.get(area_id, area_id),
        "metric": metric,
        "days": [{**d, "counts": row} for d, row in zip(days, selected)],
        "selected": summarize(selected),
        "store": summarize(store),
        "areas": profiles,
        "n_days": len(days),
        "weekdays": WEEKDAYS,
    }
