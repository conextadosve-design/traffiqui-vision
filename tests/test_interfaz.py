"""Interfaz: archivos comunes (/vendor), ventana propia de Windows y páginas de la sede principal."""
import re
import subprocess
from pathlib import Path

import pytest

from app import launcher, vendor

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
CLOUD_STATIC = Path(__file__).resolve().parents[1] / "cloud" / "static"


def test_archivos_comunes_existen_y_nada_mas_se_sirve():
    for name in vendor.FILES:
        assert (STATIC / name).is_file(), name
    with pytest.raises(Exception):
        vendor.vendor_file("../main.py")
    with pytest.raises(Exception):
        vendor.vendor_file("index.html")


def test_paginas_usan_iconos_del_sprite():
    """Cada <use href="#i-x"> de las páginas tiene su icono en ui.js."""
    sprite = set(re.findall(r"^\s{4}(\w+): '", (STATIC / "ui.js").read_text(encoding="utf-8"), re.M))
    pages = [STATIC / "index.html", *CLOUD_STATIC.glob("*.html")]
    used = {m for p in pages for m in re.findall(r'href="#i-(\w+)"', p.read_text(encoding="utf-8"))}
    assert used and used <= sprite, used - sprite


def test_ventana_propia_con_edge(monkeypatch, tmp_path):
    edge = tmp_path / "Microsoft" / "Edge" / "Application" / "msedge.exe"
    edge.parent.mkdir(parents=True)
    edge.write_text("")
    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setenv("PROGRAMFILES(X86)", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: calls.append(args))
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: calls.append(["navegador", url]))
    launcher.open_panel("http://localhost:8000")
    assert calls[0][0] == str(edge) and "--app=http://localhost:8000" in calls[0]
    assert any(a.startswith("--user-data-dir=") and "Traffiqui" in a for a in calls[0])
    launcher.open_panel("http://localhost:8000", browser=True)   # --navegador
    assert calls[1] == ["navegador", "http://localhost:8000"]


def test_sin_edge_usa_el_navegador(monkeypatch):
    monkeypatch.setattr(launcher.sys, "platform", "linux")
    opened = []
    monkeypatch.setattr(launcher.webbrowser, "open", opened.append)
    launcher.open_panel("http://localhost:9000")
    assert opened == ["http://localhost:9000"]


def test_sede_principal_sirve_archivos_comunes(tmp_path):
    pytest.importorskip("sqlalchemy")
    from fastapi.testclient import TestClient
    from cloud.db import make_engine
    from cloud.main import create_app
    c = TestClient(create_app(make_engine(f"sqlite:///{tmp_path / 'hq.db'}")))
    for path in ("/vendor/ui.js", "/vendor/backup.js", "/vendor/icono.svg", "/manifest.webmanifest", "/vendor/styles.css"):
        assert c.get(path).status_code == 200, path
    assert c.get("/vendor/nada.js").status_code == 404
