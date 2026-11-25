"""Gestión de cuentas y sedes.

Quién puede crear y administrar qué cuentas:

| Actor         | Puede crear / editar / desactivar                     |
|---------------|-------------------------------------------------------|
| superadmin    | dueños, administradores y cajeros de cualquier sede   |
| dueno         | cajeros de cualquier sede                             |
| administrador | cajeros de su propia sede                             |
| cajero        | nadie                                                 |

Nadie puede crear ni editar cuentas de super admin desde la app: esas se
manejan solo con `python -m app.scripts.crear_superadmin`. Las sedes solo
las crea y edita el super admin.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password, require_rol
from app.db.session import get_db
from app.models.sede import Sede
from app.models.usuario import (
    ROL_ADMINISTRADOR,
    ROL_CAJERO,
    ROL_DUENO,
    ROL_SUPERADMIN,
    ROLES_GLOBALES,
    Usuario,
)
from app.schemas.auth import (
    RestablecerPasswordRequest,
    SedeCreate,
    SedeResumen,
    SedeUpdate,
    UsuarioCreate,
    UsuarioOut,
    UsuarioUpdate,
)
from app.services.sedes import crear_sede

router = APIRouter(tags=["usuarios"])

_gestores = require_rol(ROL_SUPERADMIN, ROL_DUENO, ROL_ADMINISTRADOR)
_superadmin = require_rol(ROL_SUPERADMIN)
_ve_sedes = require_rol(ROL_SUPERADMIN, ROL_DUENO)

_SIN_PERMISO = "No tienes permiso para administrar esa cuenta."


def _roles_que_puede_crear(actor: Usuario) -> tuple[str, ...]:
    if actor.rol == ROL_SUPERADMIN:
        return (ROL_DUENO, ROL_ADMINISTRADOR, ROL_CAJERO)
    if actor.rol in (ROL_DUENO, ROL_ADMINISTRADOR):
        return (ROL_CAJERO,)
    return ()


def _puede_gestionar(actor: Usuario, objetivo: Usuario) -> bool:
    if objetivo.rol == ROL_SUPERADMIN or objetivo.id == actor.id:
        return False
    if actor.rol == ROL_SUPERADMIN:
        return True
    if objetivo.rol != ROL_CAJERO:
        return False
    if actor.rol == ROL_DUENO:
        return True
    return actor.rol == ROL_ADMINISTRADOR and objetivo.sede_id == actor.sede_id


def _validar_rol_y_sede(db: Session, actor: Usuario, rol: str, sede_id: int | None) -> int | None:
    """Comprueba que `actor` pueda asignar `rol` en `sede_id`; devuelve la sede final."""
    if rol not in _roles_que_puede_crear(actor):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Solo el super admin puede crear o asignar cuentas de dueño o administrador.",
        )
    if rol in ROLES_GLOBALES:
        return None  # El dueño no pertenece a una sede.
    if actor.rol == ROL_ADMINISTRADOR:
        if sede_id is not None and sede_id != actor.sede_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Solo puedes crear cajeros de tu sede.")
        sede_id = actor.sede_id
    if sede_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Elige la sede de la cuenta.")
    if db.get(Sede, sede_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Sede no encontrada")
    return sede_id


def _puede_ver(actor: Usuario, objetivo: Usuario) -> bool:
    if actor.rol == ROL_SUPERADMIN:
        return True
    if actor.rol == ROL_DUENO:
        return objetivo.rol != ROL_SUPERADMIN
    return actor.rol == ROL_ADMINISTRADOR and objetivo.sede_id == actor.sede_id


def _usuario_gestionable(db: Session, actor: Usuario, usuario_id: int) -> Usuario:
    usuario = db.get(Usuario, usuario_id)
    # Una cuenta que el actor no puede ver responde igual que si no existiera.
    if usuario is None or not _puede_ver(actor, usuario):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    if not _puede_gestionar(actor, usuario):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=_SIN_PERMISO)
    return usuario


# ---------- Usuarios


@router.get("/usuarios", response_model=list[UsuarioOut])
def listar_usuarios(
    sede_id: int | None = None,
    actor: Usuario = Depends(_gestores),
    db: Session = Depends(get_db),
) -> list[Usuario]:
    query = db.query(Usuario)
    if actor.rol == ROL_DUENO:
        query = query.filter(Usuario.rol != ROL_SUPERADMIN)
    elif actor.rol == ROL_ADMINISTRADOR:
        query = query.filter(Usuario.sede_id == actor.sede_id)
    if sede_id is not None:
        query = query.filter(Usuario.sede_id == sede_id)
    return query.order_by(Usuario.rol, Usuario.nombre).all()


@router.post("/usuarios", response_model=UsuarioOut, status_code=status.HTTP_201_CREATED)
def crear_usuario(
    payload: UsuarioCreate,
    actor: Usuario = Depends(_gestores),
    db: Session = Depends(get_db),
) -> Usuario:
    sede_id = _validar_rol_y_sede(db, actor, payload.rol, payload.sede_id)
    if db.query(Usuario.id).filter(Usuario.email == payload.email).first():
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Ya existe una cuenta con ese correo")
    usuario = Usuario(
        email=payload.email,
        password_hash=hash_password(payload.password),
        nombre=payload.nombre,
        rol=payload.rol,
        sede_id=sede_id,
    )
    db.add(usuario)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Ya existe una cuenta con ese correo")
    db.refresh(usuario)
    return usuario


@router.patch("/usuarios/{usuario_id}", response_model=UsuarioOut)
def actualizar_usuario(
    usuario_id: int,
    payload: UsuarioUpdate,
    actor: Usuario = Depends(_gestores),
    db: Session = Depends(get_db),
) -> Usuario:
    usuario = _usuario_gestionable(db, actor, usuario_id)
    nuevo_rol = payload.rol if payload.rol is not None else usuario.rol
    nueva_sede = payload.sede_id if payload.sede_id is not None else usuario.sede_id
    cambia_rol_o_sede = nuevo_rol != usuario.rol or nueva_sede != usuario.sede_id
    if cambia_rol_o_sede:
        nueva_sede = _validar_rol_y_sede(db, actor, nuevo_rol, nueva_sede)

    cambia_acceso = cambia_rol_o_sede
    if payload.nombre is not None:
        usuario.nombre = payload.nombre.strip()
    usuario.rol = nuevo_rol
    usuario.sede_id = nueva_sede
    if payload.activo is not None and payload.activo != usuario.activo:
        usuario.activo = payload.activo
        cambia_acceso = True
    if cambia_acceso:
        # Cierra la sesión abierta del usuario para que tome los permisos nuevos.
        usuario.token_version += 1
    db.commit()
    db.refresh(usuario)
    return usuario


@router.post("/usuarios/{usuario_id}/password", response_model=UsuarioOut)
def restablecer_password(
    usuario_id: int,
    payload: RestablecerPasswordRequest,
    actor: Usuario = Depends(_gestores),
    db: Session = Depends(get_db),
) -> Usuario:
    usuario = _usuario_gestionable(db, actor, usuario_id)
    usuario.password_hash = hash_password(payload.password)
    usuario.token_version += 1
    db.commit()
    db.refresh(usuario)
    return usuario


@router.delete("/usuarios/{usuario_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def eliminar_usuario(
    usuario_id: int,
    actor: Usuario = Depends(_gestores),
    db: Session = Depends(get_db),
) -> None:
    usuario = _usuario_gestionable(db, actor, usuario_id)
    db.delete(usuario)
    db.commit()


# ---------- Sedes


@router.get("/sedes", response_model=list[SedeResumen])
def listar_sedes(_: Usuario = Depends(_ve_sedes), db: Session = Depends(get_db)) -> list[Sede]:
    return db.query(Sede).order_by(Sede.nombre).all()


@router.post("/sedes", response_model=SedeResumen, status_code=status.HTTP_201_CREATED)
def nueva_sede(
    payload: SedeCreate,
    _: Usuario = Depends(_superadmin),
    db: Session = Depends(get_db),
) -> Sede:
    if db.query(Sede.id).filter(Sede.nombre == payload.nombre).first():
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Ya existe una sede con ese nombre")
    sede = crear_sede(db, payload.nombre, payload.direccion)
    db.commit()
    db.refresh(sede)
    return sede


@router.patch("/sedes/{sede_id}", response_model=SedeResumen)
def actualizar_sede(
    sede_id: int,
    payload: SedeUpdate,
    _: Usuario = Depends(_superadmin),
    db: Session = Depends(get_db),
) -> Sede:
    sede = db.get(Sede, sede_id)
    if sede is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Sede no encontrada")
    if payload.nombre is not None:
        nombre = payload.nombre.strip()
        duplicada = db.query(Sede.id).filter(Sede.nombre == nombre, Sede.id != sede_id).first()
        if duplicada:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Ya existe una sede con ese nombre")
        sede.nombre = nombre
    if "direccion" in payload.model_fields_set:
        sede.direccion = payload.direccion
    if payload.activa is not None:
        sede.activa = payload.activa
    db.commit()
    db.refresh(sede)
    return sede
