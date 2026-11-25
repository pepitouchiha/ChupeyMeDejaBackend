from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.security import PASSWORD_MIN_LEN

Rol = Literal["superadmin", "dueno", "administrador", "cajero"]
RolAsignable = Literal["dueno", "administrador", "cajero"]


def _normalizar_email(v: str) -> str:
    v = v.strip().lower()
    local, _, dominio = v.partition("@")
    if not local or "." not in dominio or " " in v:
        raise ValueError("Escribe un correo válido, por ejemplo nombre@correo.com")
    return v


def _validar_password(v: str) -> str:
    if len(v) < PASSWORD_MIN_LEN:
        raise ValueError(f"La contraseña debe tener al menos {PASSWORD_MIN_LEN} caracteres")
    if v.isdigit() or v.isalpha():
        raise ValueError("La contraseña debe combinar letras y números")
    return v


def _limpiar_texto(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("Este campo es obligatorio")
    return v


class LoginRequest(BaseModel):
    email: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=200)

    @field_validator("email")
    @classmethod
    def validar_email(cls, v: str) -> str:
        return v.strip().lower()


class SedeResumen(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    direccion: str | None = None
    activa: bool


class UsuarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    nombre: str
    rol: Rol
    sede_id: int | None
    sede_nombre: str | None
    activo: bool


class SesionOut(BaseModel):
    """Respuesta de login/registro: token + datos para armar la interfaz."""

    access_token: str
    token_type: str = "bearer"
    usuario: UsuarioOut
    sedes: list[SedeResumen]


class SedeNueva(BaseModel):
    nombre: str = Field(min_length=1, max_length=100)
    direccion: str | None = Field(default=None, max_length=200)

    _nombre = field_validator("nombre")(_limpiar_texto)


class CambiarPasswordRequest(BaseModel):
    password_actual: str = Field(min_length=1, max_length=200)
    password_nueva: str = Field(min_length=1, max_length=200)

    _password = field_validator("password_nueva")(_validar_password)


class UsuarioCreate(BaseModel):
    nombre: str = Field(min_length=1, max_length=150)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=200)
    rol: RolAsignable
    # Obligatoria para administrador y cajero; se ignora para dueño.
    sede_id: int | None = None

    _nombre = field_validator("nombre")(_limpiar_texto)
    _email = field_validator("email")(_normalizar_email)
    _password = field_validator("password")(_validar_password)


class UsuarioUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=150)
    rol: RolAsignable | None = None
    sede_id: int | None = None
    activo: bool | None = None

    @field_validator("nombre")
    @classmethod
    def validar_nombre(cls, v: str | None) -> str | None:
        return None if v is None else _limpiar_texto(v)


class RestablecerPasswordRequest(BaseModel):
    password: str = Field(min_length=1, max_length=200)

    _password = field_validator("password")(_validar_password)


class SedeCreate(SedeNueva):
    pass


class SedeUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=100)
    direccion: str | None = Field(default=None, max_length=200)
    activa: bool | None = None

    @field_validator("nombre")
    @classmethod
    def validar_nombre(cls, v: str | None) -> str | None:
        return None if v is None else _limpiar_texto(v)
