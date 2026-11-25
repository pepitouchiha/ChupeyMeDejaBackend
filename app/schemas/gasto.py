from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OrigenGasto(str, Enum):
    manual = "manual"
    inventario = "inventario"
    nomina = "nomina"


MENSAJE_NOMINA = "La categoría 'nomina' se registra desde los pagos a trabajadores, no como gasto manual"


def _limpiar_descripcion(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("descripcion no puede estar vacía")
    return v


def _limpiar_clave(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("categoria no puede estar vacía")
    return v


class GastoCreate(BaseModel):
    fecha: date | None = None
    categoria: str = Field(min_length=1, max_length=30)
    descripcion: str = Field(min_length=1, max_length=255)
    monto: int = Field(gt=0)
    pagado_desde_caja: bool = False

    @field_validator("descripcion")
    @classmethod
    def validar_descripcion(cls, v: str) -> str:
        return _limpiar_descripcion(v)

    @field_validator("categoria")
    @classmethod
    def validar_categoria(cls, v: str) -> str:
        return _limpiar_clave(v)


class GastoUpdate(BaseModel):
    fecha: date | None = None
    categoria: str | None = Field(default=None, min_length=1, max_length=30)
    descripcion: str | None = Field(default=None, min_length=1, max_length=255)
    monto: int | None = Field(default=None, gt=0)
    pagado_desde_caja: bool | None = None

    @field_validator("descripcion")
    @classmethod
    def validar_descripcion(cls, v: str | None) -> str | None:
        return None if v is None else _limpiar_descripcion(v)

    @field_validator("categoria")
    @classmethod
    def validar_categoria(cls, v: str | None) -> str | None:
        return None if v is None else _limpiar_clave(v)


class GastoOut(BaseModel):
    id: int
    fecha: date
    categoria: str
    categoria_nombre: str
    categoria_color: str
    descripcion: str
    monto: int
    pagado_desde_caja: bool
    caja_sesion_id: int | None
    movimiento_inventario_id: int | None
    trabajador_id: int | None
    creado_en: datetime
    origen: OrigenGasto

    model_config = ConfigDict(from_attributes=True)


_HEX_COLOR = r"^#[0-9a-fA-F]{6}$"


def _limpiar_nombre(v: str) -> str:
    v = " ".join(v.split())
    if not v:
        raise ValueError("nombre no puede estar vacío")
    return v


class CategoriaGastoCreate(BaseModel):
    nombre: str = Field(min_length=1, max_length=60)
    color: str | None = Field(default=None, pattern=_HEX_COLOR)

    @field_validator("nombre")
    @classmethod
    def validar_nombre(cls, v: str) -> str:
        return _limpiar_nombre(v)


class CategoriaGastoUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=60)
    color: str | None = Field(default=None, pattern=_HEX_COLOR)
    activa: bool | None = None

    @field_validator("nombre")
    @classmethod
    def validar_nombre(cls, v: str | None) -> str | None:
        return None if v is None else _limpiar_nombre(v)


class CategoriaGastoOut(BaseModel):
    id: int
    clave: str
    nombre: str
    color: str
    activa: bool
    sistema: bool
    # False solo para nómina: se registra desde los pagos a trabajadores.
    seleccionable: bool
    num_gastos: int
