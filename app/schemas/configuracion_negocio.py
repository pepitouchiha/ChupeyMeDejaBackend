from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConfiguracionNegocioUpdate(BaseModel):
    nombre_negocio: str = Field(min_length=1, max_length=100)
    nit: str | None = Field(default=None, max_length=30)
    direccion: str | None = Field(default=None, max_length=200)
    telefono: str | None = Field(default=None, max_length=30)
    mensaje_pie: str | None = Field(default=None, max_length=200)
    imprimir_comanda_auto: bool = True
    imprimir_factura_auto: bool = False
    ancho_papel_mm: Literal[58, 80] = 80

    @field_validator("nombre_negocio")
    @classmethod
    def validar_nombre(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("El nombre del negocio no puede estar vacío")
        return v

    @field_validator("nit", "direccion", "telefono", "mensaje_pie")
    @classmethod
    def normalizar_opcional(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None


class ConfiguracionNegocioOut(BaseModel):
    nombre_negocio: str
    nit: str | None
    direccion: str | None
    telefono: str | None
    mensaje_pie: str | None
    imprimir_comanda_auto: bool
    imprimir_factura_auto: bool
    ancho_papel_mm: int

    model_config = ConfigDict(from_attributes=True)
