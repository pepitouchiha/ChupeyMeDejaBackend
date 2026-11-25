from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EstadoInsumo(str, Enum):
    critico = "Crítico"
    bajo = "Bajo"
    ok = "OK"


class TipoMovimiento(str, Enum):
    entrada = "entrada"
    ajuste = "ajuste"
    venta = "venta"
    reverso_venta = "reverso_venta"


def _limpiar_texto(v: str | None) -> str | None:
    if v is None:
        return v
    v = v.strip()
    if not v:
        raise ValueError("no puede estar vacío")
    return v


def _limpiar_nota(v: str | None) -> str | None:
    if v is None:
        return None
    return v.strip() or None


class TipoInsumoOut(BaseModel):
    id: int
    clave: str
    nombre: str
    activo: bool
    num_insumos: int


class TipoInsumoCreate(BaseModel):
    nombre: str = Field(min_length=1, max_length=60)

    @field_validator("nombre")
    @classmethod
    def validar_nombre(cls, v: str) -> str:
        return _limpiar_texto(v)  # type: ignore[return-value]


class TipoInsumoUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=60)
    activo: bool | None = None

    @field_validator("nombre")
    @classmethod
    def validar_nombre(cls, v: str | None) -> str | None:
        return _limpiar_texto(v)


class InsumoCreate(BaseModel):
    nombre: str = Field(min_length=1, max_length=150)
    # Clave de un tipo de insumo activo de la sede.
    tipo: str = Field(min_length=1, max_length=30)
    unidad: str = Field(default="unidad", min_length=1, max_length=20)
    stock: float = Field(default=0, ge=0)
    stock_minimo: float = Field(default=0, ge=0)
    costo_unitario: int | None = Field(default=None, ge=0)

    @field_validator("nombre", "unidad")
    @classmethod
    def validar_texto(cls, v: str) -> str:
        return _limpiar_texto(v)  # type: ignore[return-value]


class InsumoUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=150)
    tipo: str | None = Field(default=None, min_length=1, max_length=30)
    unidad: str | None = Field(default=None, min_length=1, max_length=20)
    stock_minimo: float | None = Field(default=None, ge=0)
    costo_unitario: int | None = Field(default=None, ge=0)
    activo: bool | None = None

    @field_validator("nombre", "unidad")
    @classmethod
    def validar_texto(cls, v: str | None) -> str | None:
        return _limpiar_texto(v)


class AjusteStock(BaseModel):
    cantidad: float = Field(description="Delta a aplicar al stock actual, positivo o negativo")
    nota: str | None = Field(default=None, max_length=255)

    @field_validator("cantidad")
    @classmethod
    def validar_cantidad(cls, v: float) -> float:
        if v == 0:
            raise ValueError("cantidad no puede ser 0")
        return v

    @field_validator("nota")
    @classmethod
    def validar_nota(cls, v: str | None) -> str | None:
        return _limpiar_nota(v)


class EntradaInsumo(BaseModel):
    cantidad: float = Field(gt=0)
    costo_total: int | None = Field(default=None, ge=0)
    nota: str | None = Field(default=None, max_length=255)
    registrar_gasto: bool = True
    pagado_desde_caja: bool = False

    @field_validator("nota")
    @classmethod
    def validar_nota(cls, v: str | None) -> str | None:
        return _limpiar_nota(v)


class ConteoInsumo(BaseModel):
    stock_contado: float = Field(ge=0)
    nota: str | None = Field(default=None, max_length=255)

    @field_validator("nota")
    @classmethod
    def validar_nota(cls, v: str | None) -> str | None:
        return _limpiar_nota(v)


class InsumoOut(BaseModel):
    id: int
    nombre: str
    tipo: str
    tipo_nombre: str
    unidad: str
    stock: float
    stock_minimo: float
    costo_unitario: int | None
    activo: bool
    estado: EstadoInsumo

    model_config = ConfigDict(from_attributes=True)


class MovimientoOut(BaseModel):
    id: int
    insumo_id: int
    tipo: TipoMovimiento
    cantidad: float
    stock_resultante: float
    costo_total: int | None
    venta_id: int | None
    nota: str | None
    creado_en: datetime

    model_config = ConfigDict(from_attributes=True)
