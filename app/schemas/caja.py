from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.gasto import GastoOut
from app.schemas.venta import VentaOut


def _limpiar_notas(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


class CajaAbrir(BaseModel):
    base_inicial: int = Field(ge=0)
    notas: str | None = Field(default=None, max_length=255)

    _limpiar = field_validator("notas")(_limpiar_notas)


class CajaCerrar(BaseModel):
    efectivo_contado: int = Field(ge=0)
    base_siguiente: int = Field(ge=0)
    notas: str | None = Field(default=None, max_length=255)

    _limpiar = field_validator("notas")(_limpiar_notas)


class CajaSesionOut(BaseModel):
    id: int
    abierta_en: datetime
    cerrada_en: datetime | None
    base_inicial: int
    notas_apertura: str | None
    ventas_efectivo: int
    ventas_transferencia: int
    num_ventas: int
    gastos_desde_caja: int
    efectivo_esperado: int
    efectivo_contado: int | None
    diferencia: int | None
    base_siguiente: int | None
    retiro: int | None
    notas_cierre: str | None


class CajaActualOut(BaseModel):
    """`abierta=false` solo trae `base_sugerida`; con la caja abierta se suman
    los campos de la sesión con el resumen calculado en vivo."""

    abierta: bool
    base_sugerida: int
    id: int | None = None
    abierta_en: datetime | None = None
    base_inicial: int | None = None
    notas_apertura: str | None = None
    ventas_efectivo: int | None = None
    ventas_transferencia: int | None = None
    num_ventas: int | None = None
    gastos_desde_caja: int | None = None
    efectivo_esperado: int | None = None
    pedidos_abiertos: int | None = None


class CajaSesionDetalleOut(CajaSesionOut):
    ventas: list[VentaOut]
    gastos: list[GastoOut]
