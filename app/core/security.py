"""Autenticación (JWT), roles y sede activa de cada petición.

- `require_auth`: exige un token válido y un usuario activo.
- `require_sede`: además fija la sede activa en la sesión de base de datos,
  lo que activa el filtro automático por sede (`app.db.tenancy`).
  - Administradores y cajeros: siempre su propia sede (no pueden elegir otra).
  - Super admin y dueño: eligen la sede con el encabezado `X-Sede-Id`.
- `require_rol(...)`: restringe un endpoint a ciertos roles.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from threading import Lock

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import (
    JWT_ALGORITHM,
    JWT_EXPIRE_MINUTES,
    JWT_SECRET_KEY,
    LOGIN_BLOQUEO_MINUTOS,
    LOGIN_MAX_INTENTOS,
)
from app.db.session import get_db
from app.db.tenancy import fijar_sede
from app.models.sede import Sede
from app.models.usuario import ROL_ADMINISTRADOR, ROL_DUENO, ROL_SUPERADMIN, Usuario

_bearer_scheme = HTTPBearer(auto_error=False)

PASSWORD_MIN_LEN = 8


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(usuario: Usuario) -> str:
    ahora = datetime.now(timezone.utc)
    payload = {
        "sub": str(usuario.id),
        "rol": usuario.rol,
        "sede_id": usuario.sede_id,
        "tv": usuario.token_version,
        "iat": ahora,
        "exp": ahora + timedelta(minutes=JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> Usuario:
    no_autenticado = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Tu sesión expiró o no es válida. Inicia sesión de nuevo.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise no_autenticado

    try:
        payload = jwt.decode(
            credentials.credentials,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "exp"]},
        )
        usuario_id = int(payload["sub"])
    except (jwt.PyJWTError, ValueError, KeyError):
        raise no_autenticado

    usuario = db.get(Usuario, usuario_id)
    if usuario is None or not usuario.activo:
        raise no_autenticado
    # Cambiar la contraseña o desactivar al usuario invalida los tokens anteriores.
    if payload.get("tv", 0) != usuario.token_version:
        raise no_autenticado
    if not usuario.es_global and (usuario.sede is None or not usuario.sede.activa):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Tu sede está desactivada.")
    return usuario


def require_sede(
    usuario: Usuario = Depends(require_auth),
    x_sede_id: int | None = Header(default=None, alias="X-Sede-Id"),
    db: Session = Depends(get_db),
) -> Usuario:
    if usuario.es_global:
        if x_sede_id is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, detail="Selecciona una sede para continuar."
            )
        sede = db.get(Sede, x_sede_id)
        if sede is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Sede no encontrada")
        sede_id = sede.id
    else:
        # Un empleado nunca puede operar sobre otra sede, aunque envíe el encabezado.
        assert usuario.sede_id is not None
        if x_sede_id is not None and x_sede_id != usuario.sede_id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, detail="No tienes acceso a esa sede."
            )
        sede_id = usuario.sede_id
    fijar_sede(db, sede_id)
    return usuario


def require_rol(*roles: str) -> Callable[..., Usuario]:
    def _dependencia(usuario: Usuario = Depends(require_auth)) -> Usuario:
        if usuario.rol not in roles:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, detail="No tienes permiso para esta acción."
            )
        return usuario

    return _dependencia


# Atajos para los routers.
solo_superadmin = Depends(require_rol(ROL_SUPERADMIN))
solo_admin = Depends(require_rol(ROL_SUPERADMIN, ROL_DUENO, ROL_ADMINISTRADOR))


# --- Límite de intentos de login (en memoria; Render corre una sola instancia).


class LimitadorLogin:
    def __init__(self, max_intentos: int, bloqueo_segundos: int) -> None:
        self._max = max_intentos
        self._ventana = bloqueo_segundos
        self._fallos: dict[str, list[float]] = {}
        self._lock = Lock()

    def _vigentes(self, clave: str, ahora: float) -> list[float]:
        fallos = [t for t in self._fallos.get(clave, []) if ahora - t < self._ventana]
        if fallos:
            self._fallos[clave] = fallos
        else:
            self._fallos.pop(clave, None)
        return fallos

    def verificar(self, clave: str) -> None:
        with self._lock:
            if len(self._vigentes(clave, time.monotonic())) >= self._max:
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=(
                        "Demasiados intentos fallidos. Espera "
                        f"{self._ventana // 60} minutos e intenta de nuevo."
                    ),
                )

    def registrar_fallo(self, clave: str) -> None:
        with self._lock:
            ahora = time.monotonic()
            self._vigentes(clave, ahora)
            self._fallos.setdefault(clave, []).append(ahora)

    def limpiar(self, clave: str) -> None:
        with self._lock:
            self._fallos.pop(clave, None)


limitador_login = LimitadorLogin(LOGIN_MAX_INTENTOS, LOGIN_BLOQUEO_MINUTOS * 60)


def clave_login(request: Request, email: str) -> str:
    # Render pone la IP real del cliente en X-Forwarded-For.
    reenviada = request.headers.get("x-forwarded-for", "")
    ip = reenviada.split(",")[0].strip() if reenviada else (request.client.host if request.client else "?")
    return f"{ip}|{email.strip().lower()}"
