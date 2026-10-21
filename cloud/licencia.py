"""Licencias de sedes: cuántas sedes puede tener activas cada empresa.

El servidor central vive en el PC del cliente, así que el cobro por sede no puede depender de un
interruptor en ese mismo PC. En su lugar, el administrador de Traffiqui (Andrés) emite un **código de
licencia firmado** con su clave privada; el servidor lo verifica con la clave pública incluida en el
programa. Nadie sin la clave privada puede fabricar un código ni cambiar el número de sedes.

    # una sola vez, en el PC del administrador (guarda la clave privada fuera del repositorio):
    python -m cloud.licencia crear-claves --privada C:\\TraffiquiLicencias\\clave-privada.txt
    # por cada venta o ampliación:
    python -m cloud.licencia emitir "Farmacias Sol" 3 --privada C:\\TraffiquiLicencias\\clave-privada.txt

Sin código válido, la empresa puede tener FREE_SITES sede(s).
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import secrets
import sys
from datetime import date
from pathlib import Path

PUBLIC_KEY_FILE = Path(__file__).with_name("licencia_publica.txt")
FREE_SITES = 1
PREFIX = "TQ1"


class LicenseError(ValueError):
    pass


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def normalize(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().casefold()


def public_key(path: Path = PUBLIC_KEY_FILE):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        raw = path.read_text(encoding="utf-8").split("#")[0].strip()
        return Ed25519PublicKey.from_public_bytes(_b64d(raw)) if raw else None
    except (OSError, ValueError):
        return None


def issue(org: str, sites: int, private_b64: str, expires: str | None = None) -> str:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    if sites < 1:
        raise LicenseError("El número de sedes debe ser al menos 1.")
    payload = {"empresa": org.strip(), "sedes": int(sites), "emitida": date.today().isoformat(),
               "id": secrets.token_hex(4)}
    if expires:
        date.fromisoformat(expires)
        payload["vence"] = expires
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    sig = Ed25519PrivateKey.from_private_bytes(_b64d(private_b64.strip())).sign(body)
    return f"{PREFIX}.{_b64e(body)}.{_b64e(sig)}"


def verify(code: str, org: str, key=None, today: date | None = None) -> dict:
    """Datos de la licencia si el código es válido para esta empresa; si no, LicenseError con el motivo."""
    from cryptography.exceptions import InvalidSignature
    key = key or public_key()
    if key is None:
        raise LicenseError("Este programa no tiene la clave pública de licencias. Contacta con Traffiqui.")
    try:
        prefix, body_b64, sig_b64 = code.strip().split(".")
        if prefix != PREFIX:
            raise ValueError
        body, sig = _b64d(body_b64), _b64d(sig_b64)
        key.verify(sig, body)
        data = json.loads(body)
    except (ValueError, InvalidSignature) as e:
        raise LicenseError("El código de licencia no es válido. Cópialo completo, tal como te lo enviaron.") from e
    if normalize(data.get("empresa", "")) != normalize(org):
        raise LicenseError(f"Este código es para la empresa «{data.get('empresa')}», no para «{org}».")
    if data.get("vence") and date.fromisoformat(data["vence"]) < (today or date.today()):
        raise LicenseError(f"La licencia venció el {data['vence']}. Contacta con Traffiqui para renovarla.")
    return data


def allowed_sites(code: str | None, org: str) -> int:
    if not code:
        return FREE_SITES
    try:
        return max(FREE_SITES, int(verify(code, org)["sedes"]))
    except LicenseError:
        return FREE_SITES


def main(argv=None) -> int:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    ap = argparse.ArgumentParser(prog="python -m cloud.licencia", description="Licencias de sedes de Traffiqui")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("crear-claves", help="genera el par de claves (una sola vez)")
    p.add_argument("--privada", required=True, help="archivo donde guardar la clave privada (fuera del repositorio)")
    p = sub.add_parser("emitir", help="genera un código de licencia")
    p.add_argument("empresa"); p.add_argument("sedes", type=int)
    p.add_argument("--privada", required=True); p.add_argument("--vence", help="AAAA-MM-DD (opcional)")
    a = ap.parse_args(argv)

    if a.cmd == "crear-claves":
        dest = Path(a.privada)
        if dest.exists():
            print(f"Ya existe {dest}. No se sobrescribe: los códigos emitidos con ella dejarían de valer.", file=sys.stderr)
            return 1
        priv = Ed25519PrivateKey.generate()
        raw = lambda k, enc, fmt: k.private_bytes(enc, fmt, serialization.NoEncryption())  # noqa: E731
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(_b64e(raw(priv, serialization.Encoding.Raw, serialization.PrivateFormat.Raw)) + "\n",
                        encoding="utf-8")
        pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        PUBLIC_KEY_FILE.write_text(_b64e(pub) + "  # clave pública de licencias de Traffiqui\n", encoding="utf-8")
        print(f"Clave privada guardada en {dest}. Haz una copia de seguridad y no la compartas.")
        print(f"Clave pública escrita en {PUBLIC_KEY_FILE}: súbela al repositorio para que entre en el instalador.")
    elif a.cmd == "emitir":
        code = issue(a.empresa, a.sedes, Path(a.privada).read_text(encoding="utf-8"), a.vence)
        print(f"Licencia para «{a.empresa}»: {a.sedes} sede(s)" + (f", vence {a.vence}" if a.vence else ""))
        print(code)
    return 0


if __name__ == "__main__":
    sys.exit(main())
