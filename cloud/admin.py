"""Herramienta del administrador (hasta que exista su panel web, fase 4).

    python -m cloud.admin crear-empresa "Farmacias Sol"
    python -m cloud.admin crear-sede 1 "Sede Chacao"
    python -m cloud.admin activar-sede 1 --pago "Pago móvil 21/10, ref 1234"   → muestra la clave de la sede
    python -m cloud.admin crear-usuario gerente@sol.com "Ana Pérez" hq --empresa 1
    python -m cloud.admin listar
"""
from __future__ import annotations

import argparse
import getpass
import sys
import time

from sqlalchemy import insert, select, update

from cloud.db import ROLES, make_engine, organizations, sites, users
from cloud.security import hash_password, new_site_key, sha256


def _new_key(conn, site_id: int) -> str:
    key = new_site_key()
    conn.execute(update(sites).where(sites.c.id == site_id).values(key_hash=sha256(key), key_hint=key[-4:]))
    return key


def main(argv: list[str] | None = None, engine=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m cloud.admin", description="Administración de Traffiqui Cloud")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("crear-empresa"); p.add_argument("nombre"); p.add_argument("--zona", default=None)
    p = sub.add_parser("crear-sede"); p.add_argument("empresa", type=int); p.add_argument("nombre")
    p = sub.add_parser("activar-sede"); p.add_argument("sede", type=int); p.add_argument("--pago", default=None)
    p = sub.add_parser("suspender-sede"); p.add_argument("sede", type=int)
    p = sub.add_parser("nueva-clave"); p.add_argument("sede", type=int)
    p = sub.add_parser("crear-usuario")
    p.add_argument("correo"); p.add_argument("nombre"); p.add_argument("rol", choices=ROLES)
    p.add_argument("--empresa", type=int); p.add_argument("--sede", type=int)
    p.add_argument("--clave", help="contraseña (si no se da, se pide)")
    sub.add_parser("listar")
    a = ap.parse_args(argv)
    engine = engine or make_engine()

    with engine.begin() as conn:
        if a.cmd == "crear-empresa":
            values = {"name": a.nombre}
            if a.zona:
                values["timezone"] = a.zona
            oid = conn.execute(insert(organizations).values(**values)).inserted_primary_key[0]
            print(f"Empresa {oid} creada: {a.nombre}")
        elif a.cmd == "crear-sede":
            if conn.execute(select(organizations.c.id).where(organizations.c.id == a.empresa)).first() is None:
                print("Esa empresa no existe.", file=sys.stderr); return 1
            sid = conn.execute(insert(sites).values(org_id=a.empresa, name=a.nombre, status="pending")
                               ).inserted_primary_key[0]
            print(f"Sede {sid} creada: {a.nombre} (pendiente de pago)")
        elif a.cmd == "activar-sede":
            site = conn.execute(select(sites).where(sites.c.id == a.sede)).mappings().first()
            if site is None:
                print("Esa sede no existe.", file=sys.stderr); return 1
            values = {"status": "active", "activated_at": site["activated_at"] or time.time()}
            if a.pago:
                values["payment_note"] = a.pago
            conn.execute(update(sites).where(sites.c.id == a.sede).values(**values))
            if site["key_hash"]:
                print(f"Sede {a.sede} activada. Sigue usando su clave actual (…{site['key_hint']}).")
            else:
                key = _new_key(conn, a.sede)
                print(f"Sede {a.sede} activada. Clave para la app de la tienda (se muestra una sola vez):\n{key}")
        elif a.cmd == "suspender-sede":
            conn.execute(update(sites).where(sites.c.id == a.sede).values(status="suspended"))
            print(f"Sede {a.sede} suspendida: deja de recibir datos.")
        elif a.cmd == "nueva-clave":
            key = _new_key(conn, a.sede)
            print(f"Nueva clave de la sede {a.sede} (la anterior deja de funcionar):\n{key}")
        elif a.cmd == "crear-usuario":
            if a.rol != "admin" and not a.empresa:
                print("Los roles hq y site necesitan --empresa.", file=sys.stderr); return 1
            if a.rol == "site" and not a.sede:
                print("El rol site necesita --sede.", file=sys.stderr); return 1
            password = a.clave or getpass.getpass("Contraseña: ")
            if len(password) < 8:
                print("La contraseña debe tener al menos 8 caracteres.", file=sys.stderr); return 1
            uid = conn.execute(insert(users).values(
                email=a.correo.strip().lower(), name=a.nombre, role=a.rol, org_id=a.empresa,
                site_id=a.sede if a.rol == "site" else None, password_hash=hash_password(password))
            ).inserted_primary_key[0]
            print(f"Usuario {uid} creado: {a.correo} ({a.rol})")
        elif a.cmd == "listar":
            for org in conn.execute(select(organizations).order_by(organizations.c.id)).mappings():
                print(f"[{org['id']}] {org['name']} ({org['timezone']})")
                for s in conn.execute(select(sites).where(sites.c.org_id == org["id"]).order_by(sites.c.id)).mappings():
                    key = f"clave …{s['key_hint']}" if s["key_hint"] else "sin clave"
                    print(f"    sede {s['id']}: {s['name']} · {s['status']} · {key}")
                for u in conn.execute(select(users).where(users.c.org_id == org["id"])).mappings():
                    print(f"    usuario {u['id']}: {u['email']} · {u['role']}")
            for u in conn.execute(select(users).where(users.c.role == "admin")).mappings():
                print(f"[admin] {u['email']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
