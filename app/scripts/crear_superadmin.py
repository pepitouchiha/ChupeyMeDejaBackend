"""Crea la cuenta de super admin (y, si se piden, las sedes iniciales).

No hay registro público en la app: esta es la única forma de crear un super
admin. Se corre una vez al instalar, con DATABASE_URL apuntando a la base
correcta (Supabase en producción). También sirve para recuperar el acceso si
olvidas tu contraseña: si el correo ya existe, le pone la nueva contraseña y
cierra sus sesiones abiertas.

Uso (desde backend/):
    python -m app.scripts.crear_superadmin tu@correo.com "TuClave123" --nombre "Tu nombre" \
        --sede "Asunción|Copacabana" --sede "Machado|Copacabana"

`--sede` es opcional y repetible ("Nombre|Dirección"); si la sede ya existe, no se duplica.
La contraseña se puede omitir: el script la pide sin mostrarla en pantalla.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from app.core.security import PASSWORD_MIN_LEN, hash_password
from app.db.base_all import Base
from app.db.session import SessionLocal, engine
from app.models.sede import Sede
from app.models.usuario import ROL_SUPERADMIN, Usuario
from app.services.sedes import crear_sede


def _password_valida(password: str) -> bool:
    return (
        len(password) >= PASSWORD_MIN_LEN
        and any(c.isalpha() for c in password)
        and any(c.isdigit() for c in password)
    )


def ejecutar(email: str, password: str, nombre: str, sedes: list[str]) -> int:
    email = email.strip().lower()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        for valor in sedes:
            nombre_sede, _, direccion = valor.partition("|")
            nombre_sede = nombre_sede.strip()
            if not nombre_sede:
                print(f"Sede inválida: '{valor}'", file=sys.stderr)
                return 1
            if db.query(Sede.id).filter(Sede.nombre == nombre_sede).first():
                print(f"Sede '{nombre_sede}' ya existe.")
                continue
            crear_sede(db, nombre_sede, direccion.strip() or None)
            print(f"Sede '{nombre_sede}' creada.")

        usuario = db.query(Usuario).filter(Usuario.email == email).first()
        if usuario is None:
            usuario = Usuario(
                email=email,
                password_hash=hash_password(password),
                nombre=nombre or "Super admin",
                rol=ROL_SUPERADMIN,
                sede_id=None,
            )
            db.add(usuario)
            accion = "creada"
        else:
            if usuario.rol != ROL_SUPERADMIN:
                print(
                    f"'{email}' ya existe con rol '{usuario.rol}'. Usa otro correo para el super admin.",
                    file=sys.stderr,
                )
                db.rollback()
                return 1
            usuario.password_hash = hash_password(password)
            usuario.activo = True
            usuario.token_version += 1
            if nombre:
                usuario.nombre = nombre
            accion = "actualizada (sesiones anteriores cerradas)"
        db.commit()
        print(f"Cuenta de super admin '{email}' {accion}.")
        return 0
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Crea o restablece la cuenta de super admin.")
    parser.add_argument("email")
    parser.add_argument("password", nargs="?", help="Si se omite, se pide sin mostrarla.")
    parser.add_argument("--nombre", default="")
    parser.add_argument("--sede", action="append", default=[], help='"Nombre|Dirección" (repetible)')
    args = parser.parse_args()

    password = args.password or getpass.getpass("Contraseña del super admin: ")
    if not _password_valida(password):
        print(
            f"La contraseña debe tener al menos {PASSWORD_MIN_LEN} caracteres, con letras y números.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    raise SystemExit(ejecutar(args.email, password, args.nombre.strip(), args.sede))


if __name__ == "__main__":
    main()
