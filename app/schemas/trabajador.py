from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TipoPago(str, Enum):
    mensual = "mensual"
    quincenal = "quincenal"
    semanal = "semanal"
    diario = "diario"
    por_turno = "por_turno"


def _requerido(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("no puede estar vacío")
    return v


def _opcional(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


class TrabajadorCreate(BaseModel):
    nombre: str = Field(min_length=1, max_length=150)
    cargo: str | None = Field(default=None, max_length=80)
    telefono: str | None = Field(default=None, max_length=30)
    documento: str | None = Field(default=None, max_length=30)
    tipo_pago: TipoPago
    monto_pago: int = Field(default=0, ge=0)
    fecha_ingreso: date | None = None

    _nombre = field_validator("nombre")(_requerido)
    _opcionales = field_validator("cargo", "telefono", "documento")(_opcional)


class TrabajadorUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=150)
    cargo: str | None = Field(default=None, max_length=80)
    telefono: str | None = Field(default=None, max_length=30)
    documento: str | None = Field(default=None, max_length=30)
    tipo_pago: TipoPago | None = None
    monto_pago: int | None = Field(default=None, ge=0)
    activo: bool | None = None
    fecha_ingreso: date | None = None

    @field_validator("nombre")
    @classmethod
    def _nombre(cls, v: str | None) -> str | None:
        return None if v is None else _requerido(v)

    _opcionales = field_validator("cargo", "telefono", "documento")(_opcional)


class TrabajadorOut(BaseModel):
    id: int
    nombre: str
    cargo: str | None
    telefono: str | None
    documento: str | None
    tipo_pago: TipoPago
    monto_pago: int
    activo: bool
    fecha_ingreso: date | None
    creado_en: datetime
    total_pagado_mes_actual: int

    model_config = ConfigDict(from_attributes=True)


class PagoCreate(BaseModel):
    monto: int = Field(gt=0)
    fecha: date | None = None
    descripcion: str | None = Field(default=None, max_length=255)
    pagado_desde_caja: bool = False

    _descripcion = field_validator("descripcion")(_opcional)
