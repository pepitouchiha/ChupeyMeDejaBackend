"""Inicio de sesión y cuenta propia.

No hay registro público: el super admin se crea por línea de comandos
(`python -m app.scripts.crear_superadmin`) y las demás cuentas se crean desde
la app (`app/routers/usuarios.py`).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.security import (
    clave_login,
    create_access_token,
    hash_password,
    limitador_login,
    require_auth,
    verify_password,
)
from app.db.session import get_db
from app.models.sede import Sede
from app.models.usuario import Usuario
from app.schemas.auth import CambiarPasswordRequest, LoginRequest, SedeResumen, SesionOut, UsuarioOut

router = APIRouter(prefix="/auth", tags=["auth"])

# Hash fijo para comparar cuando el email no existe: el login tarda lo mismo
# exista o no la cuenta, y no revela qué correos están registrados.
_HASH_FICTICIO = hash_password("no-es-una-contrasena-real-123")


def _sedes_visibles(db: Session, usuario: Usuario) -> list[Sede]:
    if usuario.es_global:
        return db.query(Sede).order_by(Sede.nombre).all()
    return [usuario.sede] if usuario.sede is not None else []


def _sesion(db: Session, usuario: Usuario) -> SesionOut:
    return SesionOut(
        access_token=create_access_token(usuario),
        usuario=UsuarioOut.model_validate(usuario),
        sedes=[SedeResumen.model_validate(s) for s in _sedes_visibles(db, usuario)],
    )


@router.post("/login", response_model=SesionOut)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> SesionOut:
    clave = clave_login(request, payload.email)
    limitador_login.verificar(clave)

    usuario = db.query(Usuario).filter(Usuario.email == payload.email).first()
    hash_a_comparar = usuario.password_hash if usuario is not None else _HASH_FICTICIO
    password_ok = verify_password(payload.password, hash_a_comparar)
    if usuario is None or not password_ok:
        limitador_login.registrar_fallo(clave)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Correo o contraseña incorrectos")
    if not usuario.activo:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="Tu cuenta está desactivada. Habla con el administrador."
        )
    if not usuario.es_global and (usuario.sede is None or not usuario.sede.activa):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Tu sede está desactivada.")

    limitador_login.limpiar(clave)
    return _sesion(db, usuario)


@router.get("/me", response_model=SesionOut)
def yo(usuario: Usuario = Depends(require_auth), db: Session = Depends(get_db)) -> SesionOut:
    """Datos del usuario y sus sedes; además renueva el token."""
    return _sesion(db, usuario)


@router.post("/cambiar-password", response_model=SesionOut)
def cambiar_password(
    payload: CambiarPasswordRequest,
    usuario: Usuario = Depends(require_auth),
    db: Session = Depends(get_db),
) -> SesionOut:
    if not verify_password(payload.password_actual, usuario.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="La contraseña actual no es correcta")
    usuario.password_hash = hash_password(payload.password_nueva)
    usuario.token_version += 1
    db.commit()
    db.refresh(usuario)
    return _sesion(db, usuario)
