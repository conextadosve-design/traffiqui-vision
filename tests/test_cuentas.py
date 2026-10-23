"""Límite de intentos, código de recuperación, enlace por correo y cambio de contraseña."""
import pytest

pytest.importorskip("sqlalchemy")
from fastapi.testclient import TestClient  # noqa: E402

from cloud import config, cuentas  # noqa: E402
from cloud.db import make_engine  # noqa: E402
from cloud.main import create_app  # noqa: E402

SETUP = {"empresa": "Farmacias Sol", "nombre": "Ana", "email": "ana@sol.com", "password": "gerencia123"}


@pytest.fixture
def sent():
    return []


@pytest.fixture
def client(tmp_path, monkeypatch, sent):
    monkeypatch.setattr(config, "COOKIE_SECURE", False)
    monkeypatch.setattr(cuentas, "send_mail", lambda smtp, to, subject, body: sent.append((to, subject, body)))
    c = TestClient(create_app(make_engine(f"sqlite:///{tmp_path / 'c.db'}")))
    c.recovery = c.post("/api/setup", json=SETUP).json()["recovery_code"]
    return c


def login(c, email="ana@sol.com", password="gerencia123"):
    return c.post("/api/auth/login", json={"email": email, "password": password})


def test_bloqueo_tras_intentos_fallidos(client, monkeypatch):
    client.post("/api/auth/logout")
    for _ in range(cuentas.MAX_EMAIL_FAILURES):
        assert login(client, password="mal").status_code == 401
    r = login(client)   # ni con la contraseña buena mientras dure el bloqueo
    assert r.status_code == 429 and "Espera" in r.json()["detail"]
    # pasado el bloqueo, entra y se limpian los fallos
    real = cuentas.time.time
    monkeypatch.setattr(cuentas.time, "time", lambda: real() + cuentas.LOCK_S + 1)
    assert login(client).status_code == 200


def test_codigo_de_recuperacion(client):
    assert client.recovery.startswith("TQR-")
    client.post("/api/auth/logout")
    bad = client.post("/api/auth/recover", json={"email": "ana@sol.com", "code": "TQR-0000", "password": "nueva12345"})
    assert bad.status_code == 400
    r = client.post("/api/auth/recover", json={"email": "ana@sol.com", "code": client.recovery.lower(), "password": "nueva12345"})
    assert r.status_code == 200 and r.json()["recovery_code"] != client.recovery
    assert login(client, password="gerencia123").status_code == 401
    assert login(client, password="nueva12345").status_code == 200
    # el código usado ya no vale
    again = client.post("/api/auth/recover", json={"email": "ana@sol.com", "code": client.recovery, "password": "otra123456"})
    assert again.status_code == 400


def test_enlace_por_correo(client, sent):
    # sin correo configurado no se envía nada, y la respuesta no revela si el usuario existe
    assert client.post("/api/auth/forgot", json={"email": "ana@sol.com"}).status_code == 200
    assert sent == []
    r = client.put("/api/manage/smtp", json={"host": "smtp.x.com", "port": 587, "user": "u", "password": "p"})
    assert r.json()["configured"] and sent[-1][1] == "Traffiqui: prueba de correo"
    assert client.get("/api/manage/smtp").json()["user"] == "u"   # la contraseña SMTP nunca vuelve
    assert "password" not in client.get("/api/manage/smtp").json()
    client.post("/api/auth/forgot", json={"email": "ana@sol.com"})
    token = sent[-1][2].split("/restablecer#")[1].split()[0]
    assert client.post("/api/auth/reset", json={"token": token, "password": "corta"}).status_code == 400
    assert client.post("/api/auth/reset", json={"token": token, "password": "porcorreo1"}).status_code == 200
    assert client.post("/api/auth/reset", json={"token": token, "password": "otravez123"}).status_code == 400
    assert login(client, password="porcorreo1").status_code == 200


def test_cambiar_contrasenas_desde_el_panel(client):
    uid = client.post("/api/manage/users", json={"name": "Luis", "email": "luis@sol.com", "password": "encargado1",
                                                 "role": "hq"}).json()["id"]
    assert client.post(f"/api/manage/users/{uid}/password", json={"password": "temporal123"}).status_code == 200
    assert client.post("/api/me/password", json={"current": "mal", "password": "nueva12345"}).status_code == 400
    assert client.post("/api/me/password", json={"current": "gerencia123", "password": "nueva12345"}).status_code == 200
    assert client.get("/api/me").status_code == 401   # cambiar la contraseña cierra las sesiones
    assert login(client, "luis@sol.com", "temporal123").status_code == 200
