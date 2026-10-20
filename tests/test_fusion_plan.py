import numpy as np
import pytest

from app.vision.fusion import (GlobalTracker, Observation, PlanHeatmap, StoreFusion,
                               appearance_descriptor, appearance_similarity)
from app.vision.plan import (compute_homography, default_floorplan, footprint, plan_to_image,
                             project_point, validate_floorplan)

RED = np.zeros(128, np.float32); RED[0] = 1.0; RED[64] = 1.0
BLUE = np.zeros(128, np.float32); BLUE[40] = 1.0; BLUE[100] = 1.0


def obs(cam, tid, pos, app=RED, img=(0.5, 0.9)):
    return Observation(cam, tid, pos, img, app)


# ---- homografía -------------------------------------------------------------------------
def test_homografia_exacta_con_4_puntos():
    img = [[0, 1], [1, 1], [1, 0.5], [0, 0.5]]
    plan = [[2, 8], [6, 8], [6, 2], [2, 2]]
    H, err = compute_homography(img, plan)
    assert err < 1e-6
    assert project_point(H, 0.5, 0.75) == pytest.approx((4, 5), abs=1e-6)
    back = plan_to_image(H, [[4, 5]])[0]
    assert back == pytest.approx([0.5, 0.75], abs=1e-6)


def test_homografia_rechaza_puntos_en_linea():
    with pytest.raises(ValueError):
        compute_homography([[0, 0], [0.5, 0.5], [1, 1], [0.25, 0.25]], [[0, 0], [1, 1], [2, 2], [3, 3]])


def test_huella_de_camara_dentro_del_local():
    H, _ = compute_homography([[0, 1], [1, 1], [1, 0.5], [0, 0.5]], [[2, 8], [6, 8], [6, 2], [2, 2]])
    fp = footprint(H, 20, 12)
    assert len(fp) >= 3 and all(0 <= x <= 20 and 0 <= y <= 12 for x, y in fp)


def test_validacion_del_plano():
    assert validate_floorplan(default_floorplan()) is None
    bad = default_floorplan()
    bad["elements"].append({"id": "a", "type": "area", "name": "", "points": [[0, 0], [1, 0], [1, 1]]})
    assert "nombre" in validate_floorplan(bad)
    bad["elements"][-1] = {"id": "g", "type": "gondola", "x": 1, "y": 1, "w": 0, "d": 4}
    assert "medidas" in validate_floorplan(bad)


# ---- ID global ------------------------------------------------------------------------------
def test_superposicion_misma_persona_en_dos_camaras():
    gt = GlobalTracker()
    g1, r1 = gt.observe(obs("A", 1, (5, 5)), 10.0)
    g2, r2 = gt.observe(obs("B", 7, (5.4, 5.2)), 10.1)
    assert g1 == g2 and r1 == "nueva" and r2 == "superposición"


def test_superposicion_lejos_son_dos_personas():
    gt = GlobalTracker()
    g1, _ = gt.observe(obs("A", 1, (5, 5)), 10.0)
    g2, _ = gt.observe(obs("B", 7, (8, 5)), 10.1)
    assert g1 != g2


def test_traspaso_entre_camaras_sin_superposicion():
    gt = GlobalTracker()
    g1, _ = gt.observe(obs("A", 1, (5, 5)), 10.0)
    gt.observe(obs("A", 1, (6, 5)), 11.0)            # última vez vista en A a las 11 s
    g2, r = gt.observe(obs("B", 3, (9, 5)), 13.0)     # 3 m en 2 s: alcanzable
    assert g1 == g2 and r == "traspaso"


def test_traspaso_imposible_por_distancia():
    gt = GlobalTracker(max_speed=2.0, slack_m=1.0)
    g1, _ = gt.observe(obs("A", 1, (1, 1)), 10.0)
    g2, _ = gt.observe(obs("B", 3, (15, 10)), 12.0)   # 16 m en 2 s: imposible
    assert g1 != g2


def test_traspaso_rechaza_ropa_distinta():
    gt = GlobalTracker()
    g1, _ = gt.observe(obs("A", 1, (5, 5), RED), 10.0)
    g2, _ = gt.observe(obs("B", 3, (6, 5), BLUE), 12.0)
    assert g1 != g2


def test_reentrada_en_la_misma_camara_sin_calibrar():
    gt = GlobalTracker()
    g1, _ = gt.observe(obs("A", 1, None, RED, (0.9, 0.9)), 10.0)
    g2, r = gt.observe(obs("A", 2, None, RED, (0.85, 0.9)), 18.0)   # volvió a los 8 s por el mismo lado
    assert g1 == g2 and r == "re-entrada"


def test_reentrada_vencida_es_persona_nueva():
    gt = GlobalTracker(reentry_s=20)
    g1, _ = gt.observe(obs("A", 1, None, RED), 10.0)
    g2, _ = gt.observe(obs("A", 2, None, RED), 40.0)
    assert g1 != g2


def test_dos_tracks_simultaneos_en_la_misma_camara_no_se_unen():
    gt = GlobalTracker()
    g1, _ = gt.observe(obs("A", 1, (5, 5)), 10.0)
    g2, _ = gt.observe(obs("A", 2, (5.1, 5)), 10.0)
    assert g1 != g2


def test_empate_ambiguo_no_une():
    gt = GlobalTracker()
    ga, _ = gt.observe(obs("A", 1, (5, 5), RED), 10.0)
    gb, _ = gt.observe(obs("A", 2, (5, 6), RED), 10.0)
    g, _ = gt.observe(obs("B", 9, (5, 5.5), RED), 12.0)   # equidistante de dos personas con la misma ropa
    assert g not in (ga, gb)


def test_globales_expiran():
    gt = GlobalTracker(handoff_s=8, reentry_s=20)
    gt.observe(obs("A", 1, (5, 5)), 10.0)
    assert gt.expire(25.0) == []
    ended = gt.expire(31.5)
    assert len(ended) == 1 and not gt.globals


# ---- apariencia -------------------------------------------------------------------------------
def test_descriptor_de_apariencia_distingue_ropa():
    frame = np.zeros((300, 300, 3), np.uint8)
    frame[:, :100] = (0, 0, 220)        # persona con ropa roja
    frame[:, 100:200] = (220, 60, 0)    # persona con ropa azul
    frame[:, 200:] = (0, 0, 200)        # otra roja
    a = appearance_descriptor(frame, (0, 0, 100, 300))
    b = appearance_descriptor(frame, (100, 0, 200, 300))
    c = appearance_descriptor(frame, (200, 0, 300, 300))
    assert appearance_similarity(a, c) > 0.9
    assert appearance_similarity(a, b) < 0.3
    assert appearance_descriptor(frame, (0, 0, 10, 10)) is None


# ---- áreas, recorridos y calor en el plano -----------------------------------------------------
def plan_with_aisles():
    p = default_floorplan()
    p["elements"] += [
        {"id": "p1", "type": "area", "name": "Pasillo 1", "kind": "pasillo", "points": [[0, 0], [4, 0], [4, 12], [0, 12]]},
        {"id": "p2", "type": "area", "name": "Pasillo 2", "kind": "pasillo", "points": [[4, 0], [8, 0], [8, 12], [4, 12]]},
        {"id": "c1", "type": "area", "name": "Caja", "kind": "caja", "cameras": ["B"], "points": [[8, 0], [12, 0], [12, 12], [8, 12]]},
    ]
    return p


def test_areas_recorridos_y_calor():
    events = []
    f = StoreFusion(plan=plan_with_aisles())
    f.listeners.append(lambda k, d: events.append((k, d)))
    t = 100.0
    for x in np.arange(1, 7, 0.5):           # camina del pasillo 1 al 2 en 6 s
        f.observe_frame("A", [obs("A", 1, (float(x), 6))], t)
        t += 0.5
    snap = f.snapshot(t)
    p1, p2, caja = (next(a for a in snap["areas"] if a["id"] == i) for i in ("p1", "p2", "c1"))
    assert p1["passed"] == 1 and p2["inside"] == 1
    assert snap["transitions"] == [{"from": "Pasillo 1", "to": "Pasillo 2", "count": 1}]
    # la caja solo cuenta con la cámara B: la cámara A no la mide
    f.observe_frame("A", [obs("A", 1, (10, 6))], t)
    f.observe_frame("A", [obs("A", 1, (10, 6))], t + 3)
    assert next(a for a in f.snapshot(t + 3)["areas"] if a["id"] == "c1")["inside"] == 0
    assert f.heatmap.accum.sum() > 0
    f.finish_all(t + 4)
    kinds = [k for k, _ in events]
    assert "global_start" in kinds and "global_end" in kinds and "area_visit" in kinds and "area_transition" in kinds
    end = next(d for k, d in events if k == "global_end")
    assert end["areas"] == ["Pasillo 1", "Pasillo 2"]


def test_calor_del_plano_en_metros():
    hm = PlanHeatmap(20, 12, cell_m=0.25)
    assert (hm.rows, hm.cols) == (48, 80)
    assert hm.cell_for(0.1, 0.1) == (0, 0) and hm.cell_for(19.99, 11.99) == (47, 79)
    assert hm.cell_for(25, 5) is None


# ---- puertas (entrada / salida) y compradores --------------------------------------------------
def plan_with_doors_and_checkout(role_exit="exit"):
    p = default_floorplan()  # local 20 × 12, entrada en la pared inferior (y = 12) de x 8 a 12
    p["elements"] = [e for e in p["elements"] if e["type"] != "door"]
    p["elements"] += [
        {"id": "in1", "type": "door", "points": [[8, 12], [12, 12]], "label": "Entrada", "role": "entry"},
        {"id": "out1", "type": "door", "points": [[0, 4], [0, 8]], "label": "Salida lateral", "role": role_exit},
        {"id": "cj", "type": "area", "name": "Cajas", "kind": "caja", "points": [[14, 1], [19, 1], [19, 4], [14, 4]]},
        {"id": "p1", "type": "area", "name": "Pasillo 1", "kind": "pasillo", "points": [[2, 2], [6, 2], [6, 10], [2, 10]]},
    ]
    return p


def walk_path(f, cam, tid, points, t0, dt=0.5):
    t = t0
    for p in points:
        f.observe_frame(cam, [obs(cam, tid, p)], t)
        t += dt
    return t


def test_puertas_entrada_y_salida_en_lugares_distintos():
    events = []
    f = StoreFusion(plan=plan_with_doors_and_checkout())
    f.listeners.append(lambda k, d: events.append((k, d)))
    # entra por abajo (y 12.5 → 10), camina y sale por la pared izquierda (x 0.5 → -0.5)
    t = walk_path(f, "A", 1, [(10, 12.5), (10, 12.4), (10, 11.5), (10, 10), (6, 6), (1, 6), (0.5, 6), (-0.5, 6)], 100.0)
    snap = f.snapshot(t)
    doors = {d["id"]: d for d in snap["doors"]}
    assert doors["in1"]["in"] == 1 and doors["in1"]["out"] == 0
    assert doors["out1"]["out"] == 1 and doors["out1"]["in"] == 0
    assert snap["entries"] == 1 and snap["exits"] == 1
    assert [d["direction"] for k, d in events if k == "door_event"] == ["in", "out"]


def test_puerta_solo_entrada_ignora_salidas():
    f = StoreFusion(plan=plan_with_doors_and_checkout())
    t = walk_path(f, "A", 1, [(10, 10), (10, 10.5), (10, 11.5), (10, 12.5)], 100.0)   # sale por la entrada
    assert {d["id"]: d for d in f.snapshot(t)["doors"]}["in1"]["out"] == 0


def test_cruce_de_puerta_espera_a_que_la_persona_se_confirme():
    f = StoreFusion(GlobalTracker(min_confirm_s=1.0), plan=plan_with_doors_and_checkout())
    f.observe_frame("A", [obs("A", 1, (10, 12.5))], 100.0)
    f.observe_frame("A", [obs("A", 1, (10, 11.0))], 100.2)        # cruza antes de 1 s: queda pendiente
    assert f.snapshot(100.2)["entries"] == 0
    f.observe_frame("A", [obs("A", 1, (10, 10.0))], 101.3)        # se confirma: se cuenta
    assert f.snapshot(101.3)["entries"] == 1


def test_comprador_exitoso_por_tiempo_acumulado_en_cajas():
    events = []
    f = StoreFusion(plan=plan_with_doors_and_checkout())
    f.buyer_seconds = 20
    f.listeners.append(lambda k, d: events.append((k, d)))
    t = walk_path(f, "A", 1, [(16, 2)] * 25, 100.0)                # 12 s en cajas
    t = walk_path(f, "A", 1, [(4, 6)] * 6, t)                      # vuelve al pasillo
    assert not f.snapshot(t)["people"][0]["buyer"]
    t = walk_path(f, "A", 1, [(16, 2)] * 20, t)                    # otros ~10 s: acumula > 20 s
    snap = f.snapshot(t)
    assert snap["people"][0]["buyer"] and snap["buyers_session"] == 1
    assert sum(1 for k, _ in events if k == "global_buyer") == 1
    f.finish_all(t)
    end = next(d for k, d in events if k == "global_end")
    assert end["buyer"] is True and end["checkout_seconds"] >= 20


def test_quien_solo_transita_no_es_comprador():
    events = []
    f = StoreFusion(plan=plan_with_doors_and_checkout())
    f.listeners.append(lambda k, d: events.append((k, d)))
    t = walk_path(f, "A", 1, [(16, 2)] * 10 + [(4, 6)] * 10, 100.0)  # 5 s en cajas y se va
    f.finish_all(t)
    end = next(d for k, d in events if k == "global_end")
    assert end["buyer"] is False and 0 < end["checkout_seconds"] < 20


def test_analitica_compradores_vs_no_compradores(tmp_path):
    from app.storage.db import Database
    from app.storage.store_analytics import buyers_query
    db = Database(tmp_path / "b.db")
    db.start_session(0, {})
    t0 = 1_800_000_000.0
    people = [(1, True, 300, ["Pasillo 1", "Cajas"]), (2, True, 200, ["Cajas"]), (3, False, 40, ["Pasillo 1"]),
              (4, False, 15, []), (5, False, 60, ["Pasillo 1"])]
    for gid, buyer, dur, areas in people:
        db.on_event("global_start", {"global_id": gid, "first_seen": t0 + gid, "color": "#fff"})
        db.on_event("global_end", {"global_id": gid, "first_seen": t0 + gid, "last_seen": t0 + gid + dur, "duration": dur,
                                   "cameras": ["A"], "areas": areas, "buyer": buyer, "checkout_seconds": 30 if buyer else 0,
                                   "stopped": dur > 30})
        for a in areas:
            aid = "cj" if a == "Cajas" else "p1"
            db.on_event("area_visit", {"global_id": gid, "area_id": aid, "area": a, "enter": t0 + gid, "exit": t0 + gid + 5, "duration": 5})
    db.on_event("door_event", {"global_id": 1, "door_id": "in1", "door": "Entrada", "direction": "in", "ts": t0 + 1})
    db.on_event("door_event", {"global_id": 1, "door_id": "out1", "door": "Salida", "direction": "out", "ts": t0 + 300})
    assert db.flush()
    areas = [{"id": "p1", "name": "Pasillo 1", "kind": "pasillo"}, {"id": "cj", "name": "Cajas", "kind": "caja"}]
    r = buyers_query(db, t0, t0 + 3600, areas, 20)
    g = r["groups"]
    assert (g["buyers"]["count"], g["non_buyers"]["count"], g["total"]["count"]) == (2, 3, 5)
    assert r["conversion"] == 0.4 and g["buyers"]["avg_dwell"] == 250.0
    p1 = next(a for a in r["areas"] if a["id"] == "p1")
    assert p1["buyers"] == 1 and p1["buyers_pct"] == 0.5 and p1["non_buyers"] == 2 and p1["non_buyers_pct"] == round(2 / 3, 3)
    assert r["entries"] == 1 and r["exits"] == 1 and r["has_checkout"]
    db.close()


# ---- personal (más de N horas o zona de personal) y cajas por separado --------------------------
def plan_two_checkouts():
    p = plan_with_doors_and_checkout()
    p["elements"] = [e for e in p["elements"] if e["id"] != "cj"]
    p["elements"] += [
        {"id": "c1", "type": "area", "name": "Caja 1 · cliente", "kind": "caja", "checkout_id": "k1", "zone_role": "customer",
         "points": [[14, 2], [16, 2], [16, 3], [14, 3]]},
        {"id": "c2", "type": "area", "name": "Caja 2 · cliente", "kind": "caja", "checkout_id": "k2", "zone_role": "customer",
         "points": [[17, 2], [19, 2], [19, 3], [17, 3]]},
        {"id": "s1", "type": "area", "name": "Caja 1 · cajero", "kind": "personal", "checkout_id": "k1", "zone_role": "cashier",
         "points": [[14, 0.5], [16, 0.5], [16, 1.5], [14, 1.5]]},
    ]
    return p


def test_mas_de_4_horas_es_personal_y_no_cuenta():
    events = []
    f = StoreFusion(plan=plan_two_checkouts())
    f.staff_hours = 4
    f.listeners.append(lambda k, d: events.append((k, d)))
    t = walk_path(f, "A", 1, [(15, 2.5)] * 50, 100.0)          # 25 s en caja 1: comprador
    assert f.snapshot(t)["buyers_session"] == 1 and f.snapshot(t)["unique_session"] == 1
    t = walk_path(f, "A", 1, [(4, 6)], t + 4 * 3600)            # sigue en la tienda 4 h después
    snap = f.snapshot(t)
    assert snap["people"][0]["staff"] and snap["staff_session"] == 1
    assert snap["buyers_session"] == 0 and snap["unique_session"] == 0 and snap["people_now"] == 0
    assert any(k == "global_staff" and "4 h" in d["reason"] for k, d in events)


def test_zona_de_personal_marca_al_cajero_aunque_pase_por_caja():
    f = StoreFusion(plan=plan_two_checkouts())
    f.staff_zone_seconds = 15
    t = walk_path(f, "A", 1, [(15, 1.0)] * 40, 100.0)           # 20 s detrás de la caja 1
    t = walk_path(f, "A", 1, [(15, 2.5)] * 60, t)               # y 30 s del lado del cliente
    snap = f.snapshot(t)
    assert snap["people"][0]["staff"] and not snap["people"][0]["buyer"] and snap["buyers_session"] == 0
    caja1 = next(a for a in snap["areas"] if a["id"] == "c1")
    assert caja1["inside"] == 0                                   # el personal no cuenta como cliente en la caja


def test_compra_se_atribuye_a_la_caja_donde_mas_estuvo():
    events = []
    f = StoreFusion(plan=plan_two_checkouts())
    f.listeners.append(lambda k, d: events.append((k, d)))
    t = walk_path(f, "A", 1, [(15, 2.5)] * 10, 100.0)           # 5 s en caja 1
    t = walk_path(f, "A", 1, [(18, 2.5)] * 40, t)               # 20 s en caja 2
    f.finish_all(t)
    end = next(d for k, d in events if k == "global_end")
    assert end["buyer"] and end["checkout_area_id"] == "c2" and end["checkout_area"] == "Caja 2 · cliente"


def test_analitica_excluye_personal_y_separa_cajas(tmp_path):
    from app.storage.db import Database
    from app.storage.store_analytics import buyers_query, store_query
    db = Database(tmp_path / "s.db")
    db.start_session(0, {})
    t0 = 1_800_000_000.0
    rows = [(1, True, False, "c1"), (2, True, False, "c2"), (3, True, False, "c2"), (4, False, False, None), (9, False, True, None)]
    for gid, buyer, staff, caja in rows:
        db.on_event("global_start", {"global_id": gid, "first_seen": t0 + gid})
        db.on_event("global_end", {"global_id": gid, "first_seen": t0 + gid, "last_seen": t0 + gid + 60, "duration": 60,
                                   "cameras": ["A"], "areas": ["Pasillo 1"], "buyer": buyer, "checkout_seconds": 25 if buyer else 0,
                                   "stopped": False, "staff": staff, "staff_reason": "más de 4 h en la tienda" if staff else None,
                                   "checkout_area_id": caja, "checkout_area": caja})
        db.on_event("area_visit", {"global_id": gid, "area_id": "p1", "area": "Pasillo 1", "enter": t0 + gid, "exit": t0 + gid + 5, "duration": 5})
        if caja:
            db.on_event("area_visit", {"global_id": gid, "area_id": caja, "area": caja, "enter": t0 + gid + 10, "exit": t0 + gid + 35, "duration": 25})
    db.on_event("door_event", {"global_id": 9, "door_id": "in1", "door": "Entrada", "direction": "in", "ts": t0 + 9})
    assert db.flush()
    areas = [{"id": "p1", "name": "Pasillo 1", "kind": "pasillo"}, {"id": "c1", "name": "Caja 1", "kind": "caja"},
             {"id": "c2", "name": "Caja 2", "kind": "caja"}]
    b = buyers_query(db, t0, t0 + 3600, areas, 20)
    assert b["groups"]["total"]["count"] == 4 and b["staff"]["count"] == 1 and b["entries"] == 0
    cajas = {c["id"]: c for c in b["checkouts"]}
    assert cajas["c2"]["buyers"] == 2 and cajas["c1"]["buyers"] == 1 and cajas["c2"]["avg_seconds"] == 25
    s = store_query(db, t0, t0 + 3600, areas)
    assert s["totals"]["unique"] == 4 and next(a for a in s["areas"] if a["id"] == "p1")["passed"] == 4
    assert db.count_globals_since(t0) == 4
    db.close()


def test_zonas_de_caja_superpuestas_no_duplican_el_tiempo():
    p = plan_two_checkouts()
    p["elements"].append({"id": "big", "type": "area", "name": "Cajas (vieja)", "kind": "caja",
                          "points": [[13, 1], [20, 1], [20, 4], [13, 4]]})   # se superpone con la caja 1
    f = StoreFusion(plan=p)
    f.buyer_seconds = 20
    t = walk_path(f, "A", 1, [(15, 2.5)] * 25, 100.0)   # 12 s reales dentro de dos zonas a la vez
    snap = f.snapshot(t)
    assert not snap["people"][0]["buyer"]
    assert 11 <= snap["people"][0]["checkout_s"] <= 13
