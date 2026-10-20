"""Plano de la tienda en metros y calibración cámara → plano (homografía).

Convenciones:
  * El plano tiene origen en la esquina superior izquierda; x hacia la derecha,
    y hacia abajo (en el 3D, y del plano = z), en metros.
  * Los puntos de imagen de la calibración están NORMALIZADOS (0–1) para que la
    calibración sobreviva a cambios de resolución de la cámara.
  * Se proyectan los PIES de la persona (base del recuadro): la homografía solo
    es válida para puntos sobre el piso.
"""
from __future__ import annotations

import math
import uuid

import cv2
import numpy as np

ELEMENT_TYPES = {
    # tipo: (forma, alto por defecto en m)
    "wall": ("segment", 3.0),       # pared
    "divider": ("segment", 1.5),    # divisor / tabique bajo
    "door": ("segment", 0.0),       # puerta / entrada (solo marca)
    "gondola": ("box", 1.8),        # góndola / estante
    "furniture": ("box", 1.0),      # mueble / exhibidor / isla
    "checkout": ("box", 1.0),       # caja registradora
    "fridge": ("box", 2.0),         # nevera / refrigerador
    "counter": ("box", 1.1),        # mostrador (farmacia)
    "area": ("polygon", 0.0),       # área de análisis (pasillo, cabecera, caja…)
    "camera": ("point", 2.8),       # cámara (posición y orientación)
}
# caja = zona donde se para el CLIENTE para pagar (cuenta para "comprador");
# personal = zona solo de empleados (detrás del mostrador o de la caja): quien está ahí es personal
AREA_KINDS = ("pasillo", "cabecera", "caja", "entrada", "mostrador", "personal", "otro")
CUSTOMER_SIDES = ("front", "back", "left", "right")
MAX_BACKGROUND_CHARS = 4_000_000  # imagen de fondo para calcar (data URL), ~3 MB
# both = entrada y salida (cuenta según el sentido); entry = solo entradas; exit = solo salidas
DOOR_ROLES = ("both", "entry", "exit")


def default_floorplan() -> dict:
    """Local vacío de 20 × 12 m con paredes perimetrales y una entrada."""
    w, d = 20.0, 12.0
    wall = lambda pts: {"id": _id(), "type": "wall", "points": pts, "thickness": 0.15, "height": 3.0}
    return {
        "name": "Mi tienda",
        "width": w, "depth": d, "grid": 0.5,
        "elements": [
            wall([[0, 0], [w, 0], [w, d], [12, d]]),
            wall([[8, d], [0, d], [0, 0]]),
            {"id": _id(), "type": "door", "points": [[8, d], [12, d]], "label": "Entrada", "role": "both"},
        ],
    }


def _id() -> str:
    return uuid.uuid4().hex[:8]


# ---- validación del plano ------------------------------------------------------------
def _num(v, lo=-1e6, hi=1e6) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and lo <= v <= hi


def _pt(p) -> bool:
    return isinstance(p, (list, tuple)) and len(p) == 2 and _num(p[0], -1000, 1000) and _num(p[1], -1000, 1000)


def validate_floorplan(plan: dict) -> str | None:
    """Mensaje de error en español o None."""
    if not isinstance(plan, dict):
        return "El plano debe ser un objeto."
    if not (_num(plan.get("width"), 2, 500) and _num(plan.get("depth"), 2, 500)):
        return "El ancho y el fondo del local deben estar entre 2 y 500 m."
    els = plan.get("elements")
    if not isinstance(els, list) or len(els) > 3000:
        return "La lista de elementos no es válida (máximo 3000)."
    bg = plan.get("background")
    if bg is not None:
        if not isinstance(bg, dict) or not str(bg.get("data", "")).startswith("data:image/"):
            return "La imagen de fondo no es válida."
        if len(bg["data"]) > MAX_BACKGROUND_CHARS:
            return "La imagen de fondo es muy pesada (máximo ~3 MB). Achícala o guárdala como JPG."
        if not (_num(bg.get("w"), 0.5, 1000) and _num(bg.get("x", 0), -500, 500) and _num(bg.get("y", 0), -500, 500)
                and _num(bg.get("opacity", 0.5), 0, 1)):
            return "La posición, el ancho o la opacidad de la imagen de fondo no son válidos."
    ids = set()
    for e in els:
        if not isinstance(e, dict) or e.get("type") not in ELEMENT_TYPES or not e.get("id"):
            return "Hay un elemento con tipo desconocido o sin id."
        if e["id"] in ids:
            return f"Hay dos elementos con el mismo id ({e['id']})."
        ids.add(e["id"])
        shape = ELEMENT_TYPES[e["type"]][0]
        if shape == "segment":
            pts = e.get("points")
            if not isinstance(pts, list) or len(pts) < 2 or not all(_pt(p) for p in pts):
                return "Cada pared, divisor o puerta necesita al menos 2 puntos."
            if e["type"] == "door":
                if e.get("role", "both") not in DOOR_ROLES:
                    return f"Función de puerta no válida: {e.get('role')}."
                if not isinstance(e.get("flip", False), bool):
                    return "«Invertir lado interior» debe ser verdadero o falso."
        elif shape == "polygon":
            pts = e.get("points")
            if not isinstance(pts, list) or len(pts) < 3 or not all(_pt(p) for p in pts):
                return f"El área «{e.get('name', '')}» necesita al menos 3 puntos."
            if not str(e.get("name", "")).strip():
                return "Cada área necesita un nombre."
            if e.get("kind", "pasillo") not in AREA_KINDS:
                return f"Tipo de área no válido: {e.get('kind')}."
            if not isinstance(e.get("cameras", []), list):
                return "Las cámaras de un área deben ser una lista."
            if e.get("zone_role") not in (None, "customer", "cashier"):
                return "El rol de una zona de caja debe ser cliente o cajero."
        elif shape == "box":
            if not (_pt([e.get("x"), e.get("y")]) and _num(e.get("w"), 0.05, 200) and _num(e.get("d"), 0.05, 200)):
                return f"El elemento «{e.get('label') or e['type']}» necesita posición y medidas válidas."
            if e["type"] == "checkout":
                if e.get("customer_side", "front") not in CUSTOMER_SIDES:
                    return "El lado del cliente de una caja debe ser frente, atrás, izquierda o derecha."
                if "zone_depth" in e and not _num(e["zone_depth"], 0.3, 10):
                    return "La profundidad de la zona del cliente debe estar entre 0.3 y 10 m."
        elif shape == "point":
            if not _pt([e.get("x"), e.get("y")]):
                return "Cada cámara del plano necesita posición."
        if "height" in e and not _num(e["height"], 0, 20):
            return "La altura debe estar entre 0 y 20 m."
    return None


def plan_areas(plan: dict) -> list[dict]:
    """Áreas de análisis del plano (pasillos, cabeceras, cajas…)."""
    return [e for e in plan.get("elements", []) if e.get("type") == "area"]


# ---- homografía ----------------------------------------------------------------------
def compute_homography(image_pts: list, plan_pts: list) -> tuple[np.ndarray, float]:
    """H (3×3) de imagen normalizada → plano en metros y error medio en metros.

    Con 4 puntos la solución es exacta (error ~0); con más se usa RANSAC y el
    error indica qué tan consistente es la calibración.
    """
    if len(image_pts) != len(plan_pts) or len(image_pts) < 4:
        raise ValueError("Se necesitan al menos 4 pares de puntos (imagen ↔ plano).")
    src = np.asarray(image_pts, np.float64)
    dst = np.asarray(plan_pts, np.float64)
    if len(src) == 4:
        H = cv2.getPerspectiveTransform(src.astype(np.float32), dst.astype(np.float32))
    else:
        H, _ = cv2.findHomography(src, dst, cv2.RANSAC, 0.5)
    if H is None or not np.isfinite(H).all() or abs(np.linalg.det(H)) < 1e-12:
        raise ValueError("Los puntos no forman una calibración válida: evita que 3 queden en línea recta "
                         "y usa puntos del PISO bien separados (idealmente en las 4 esquinas de la imagen).")
    err = float(np.mean(np.linalg.norm(project(H, src) - dst, axis=1)))
    return H, err


def project(H: np.ndarray, pts) -> np.ndarray:
    """Proyecta puntos (N×2) con H. Los que caen detrás del horizonte quedan en NaN."""
    p = np.asarray(pts, np.float64).reshape(-1, 2)
    hom = np.hstack([p, np.ones((len(p), 1))]) @ np.asarray(H, np.float64).T
    w = hom[:, 2:3]
    out = hom[:, :2] / np.where(np.abs(w) < 1e-12, np.nan, w)
    out[(w[:, 0] <= 0)] = np.nan
    return out


def project_point(H, u: float, v: float) -> tuple[float, float] | None:
    x, y = project(H, [[u, v]])[0]
    if not (math.isfinite(x) and math.isfinite(y)):
        return None
    return float(x), float(y)


def footprint(H, plan_w: float, plan_d: float, steps: int = 12) -> list[list[float]]:
    """Polígono aproximado del piso que ve la cámara, recortado al local (para dibujarlo en el plano)."""
    border = ([(i / steps, 1.0) for i in range(steps + 1)] + [(1.0, 1 - i / steps) for i in range(1, steps + 1)]
              + [(1 - i / steps, 0.0) for i in range(1, steps + 1)] + [(0.0, i / steps) for i in range(1, steps)])
    pts = project(H, border)
    pts = pts[np.isfinite(pts).all(axis=1)]
    if len(pts) < 3:
        return []
    margin = max(plan_w, plan_d)  # descarta puntos cerca del horizonte (se van al infinito)
    pts = pts[(pts[:, 0] > -margin) & (pts[:, 0] < plan_w + margin) & (pts[:, 1] > -margin) & (pts[:, 1] < plan_d + margin)]
    if len(pts) < 3:
        return []
    hull = cv2.convexHull(pts.astype(np.float32)).reshape(-1, 2)
    hull[:, 0] = hull[:, 0].clip(0, plan_w)
    hull[:, 1] = hull[:, 1].clip(0, plan_d)
    return [[round(float(x), 3), round(float(y), 3)] for x, y in hull]


def plan_to_image(H, pts) -> np.ndarray:
    """Plano (m) → imagen normalizada, para dibujar las áreas del plano sobre el video."""
    H = np.asarray(H, np.float64)
    Hinv = np.linalg.inv(H)
    # la escala de la inversa es arbitraria: se orienta para que un punto visible (borde inferior
    # central de la imagen, siempre sobre el piso) tenga w > 0
    ref = project(H, [[0.5, 1.0]])[0]
    if np.isfinite(ref).all() and (Hinv @ np.array([ref[0], ref[1], 1.0]))[2] < 0:
        Hinv = -Hinv
    return project(Hinv, pts)
