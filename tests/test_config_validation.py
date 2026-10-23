import pytest

from app.config import Settings
from app.main import validate_config


@pytest.mark.parametrize("changes", [
    {"trail_seconds": 3},
    {"trail_seconds": 10, "confidence": 0.5, "imgsz": 320},
    {"track_point": "bottom", "heatmap_mode": "accum"},
    {"line": {"a": [0.1, 0.1], "b": [0.9, 0.9], "inverted": False}},
    {"line": None},
    {"zones": [{"id": "z1", "name": "Caja", "points": [[0, 0], [1, 0], [1, 1]]}]},
    {"width": 1280, "height": 720},
    {"privacy_blur": True},
])
def test_cambios_validos(changes):
    assert validate_config(changes) is None


@pytest.mark.parametrize("changes,fragment", [
    ({"trail_seconds": 0.5}, "rastro"),
    ({"trail_seconds": 11}, "rastro"),
    ({"confidence": "alta"}, "confianza"),
    ({"imgsz": 500}, "imgsz"),
    ({"track_point": "cabeza"}, "track_point"),
    ({"zones": [{"id": "z", "name": "Caja", "points": [[0, 0], [1, 1]]}]}, "3 puntos"),
    ({"zones": [{"id": "z", "name": " ", "points": [[0, 0], [1, 0], [1, 1]]}]}, "nombre"),
    ({"line": {"a": [0.1, 0.1], "b": [2, 0.5]}}, "línea"),
    ({"width": 1000, "height": 700}, "Resolución"),
    ({"privacy_blur": "si"}, "verdadero"),
    ({"no_existe": 1}, "desconocidos"),
])
def test_cambios_invalidos_explican_el_error(changes, fragment):
    err = validate_config(changes)
    assert err and fragment.lower() in err.lower()


def test_settings_ignora_claves_desconocidas_y_versiona():
    s = Settings({"trail_seconds": 5})
    v = s.version
    s.update({"trail_seconds": 7, "otra": 1})
    assert s.get("trail_seconds") == 7 and "otra" not in s.snapshot() and s.version == v + 1


def test_memoria_de_reentrada_ajustable_hasta_30_min():
    assert Settings().get("reid_reentry_s") == 300
    for v in (0, 20, 300, 1800):
        assert validate_config({"reid_reentry_s": v}) is None
    assert "memoria" in validate_config({"reid_reentry_s": 1801}).lower()
