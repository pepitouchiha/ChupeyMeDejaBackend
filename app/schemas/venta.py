from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MetodoPago(str, Enum):
    efectivo = "efectivo"
    transferencia = "transferencia"


class EstadoVenta(str, Enum):
    activa = "activa"
    cancelada = "cancelada"
    abierta = "abierta"


class VentaItemCreate(BaseModel):
    producto_id: int
    cantidad: int = Field(gt=0)


class _VentaItemsBase(BaseModel):
    items: list[VentaItemCreate]
    metodo_pago: MetodoPago
    mesa_id: int | None = None

    @field_validator("items")
    @classmethod
    def validar_items(cls, v: list[VentaItemCreate]) -> list[VentaItemCreate]:
        if not v:
            raise ValueError("La venta debe tener al menos un item")
        return v


class VentaCreate(_VentaItemsBase):
    pass


class VentaUpdate(_VentaItemsBase):
    pass


class VentaAbrir(BaseModel):
    # Un pedido abierto siempre está atado a una mesa (a diferencia de
    # VentaCreate, donde mesa_id es opcional para venta de mostrador).
    mesa_id: int


class VentaAgregarItems(BaseModel):
    items: list[VentaItemCreate]

    @field_validator("items")
    @classmethod
    def validar_items(cls, v: list[VentaItemCreate]) -> list[VentaItemCreate]:
        if not v:
            raise ValueError("Debe incluir al menos un item")
        return v


class VentaCambiarCantidadItem(BaseModel):
    cantidad: int = Field(gt=0)


class VentaCerrar(BaseModel):
    metodo_pago: MetodoPago


class VentaItemOut(BaseModel):
    id: int
    producto_id: int
    nombre_producto: str
    cantidad: int
    precio_unitario: int

    model_config = ConfigDict(from_attributes=True)


class VentaOut(BaseModel):
    id: int
    mesa_id: int | None
    mesa_nombre: str | None
    metodo_pago: MetodoPago | None
    estado: EstadoVenta
    total: int
    caja_sesion_id: int | None
    creado_en: datetime
    items: list[VentaItemOut]

    model_config = ConfigDict(from_attributes=True)
