"""Alertas de la tienda: aforo superado, fila larga en caja (opcional) y cámaras con problemas.

Se muestran arriba del panel de la tienda y viajan a la sede principal con el estado en vivo, que
guarda su historial y añade la alerta "sede sin enviar datos". Una condición tiene que durar un rato
(HOLD_S) para abrir la alerta: alguien que se para un segundo en la caja no dispara nada.
"""
from __future__ import annotations

import time

HOLD_S = {"aforo": 30.0, "fila": 60.0, "camara": 0.0}
CAMERA_LABEL = {"sin_senal": "sin señal", "tapada": "tapada o a oscuras", "movida": "se movió"}


class AlertTracker:
    def __init__(self):
        self._first_seen: dict[tuple[str, str], float] = {}

    def update(self, cfg: dict, people_now: int, areas: list[dict], cameras: list[dict],
               now: float | None = None) -> list[dict]:
        now = now or time.time()
        cond: dict[tuple[str, str], tuple[str, str]] = {}
        cap = int(cfg.get("alert_capacity") or 0)
        if cap and people_now > cap:
            cond[("aforo", "")] = (f"Aforo superado: {people_now} personas", f"El máximo configurado es {cap}.")
        queue = int(cfg.get("alert_queue_people") or 0)
        if queue:
            for a in areas:
                if a.get("kind") == "caja" and a.get("inside", 0) >= queue:
                    cond[("fila", a["id"])] = (f"Fila larga en {a['name']}: {a['inside']} personas",
                                               f"Avisa a partir de {queue} personas esperando más de 1 minuto.")
        for c in cameras:
            if not c.get("enabled", True):
                continue
            state = "sin_senal" if not c.get("connected") else (c.get("health") or {}).get("state")
            if state in CAMERA_LABEL:
                cond[("camara", c["id"])] = (f"Cámara «{c['name']}»: {CAMERA_LABEL[state]}",
                                             (c.get("health") or {}).get("message") or c.get("error") or "")
        for key in [k for k in self._first_seen if k not in cond]:
            del self._first_seen[key]
        out = []
        for (kind, ref), (title, message) in cond.items():
            since = self._first_seen.setdefault((kind, ref), now)
            if now - since >= HOLD_S[kind]:
                out.append({"kind": kind, "ref": ref, "title": title, "message": message, "since": since})
        return out
