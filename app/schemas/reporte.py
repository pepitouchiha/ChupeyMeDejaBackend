from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict


class VentaPorHora(BaseModel):
    hora: int
    total: int
    num_ventas: int

    model_config = ConfigDict(from_attributes=True)


class ReporteHoyOut(BaseModel):
    fecha: date
    total: int
    num_ventas: int
    por_hora: list[VentaPorHora]
    margen: int
    margen_incompleto: bool

    model_config = ConfigDict(from_attributes=True)


class VentaPorMes(BaseModel):
    anio: int
    mes: int
    total: int
    num_ventas: int
    ticket_promedio: float
    margen: int
    margen_incompleto: bool

    model_config = ConfigDict(from_attributes=True)


class ReporteMensualOut(BaseModel):
    meses: list[VentaPorMes]
    ytd_total: int
    ytd_margen: int
    ytd_margen_incompleto: bool

    model_config = ConfigDict(from_attributes=True)


class VentaPorDia(BaseModel):
    fecha: date
    total: int
    num_ventas: int
    total_efectivo: int
    total_transferencia: int
    margen: int
    margen_incompleto: bool

    model_config = ConfigDict(from_attributes=True)


class InvertidoPorCategoria(BaseModel):
    categoria: str
    etiqueta: str
    total: int


class ContabilidadPorDia(BaseModel):
    fecha: date
    ventas: int
    invertido: int
    ganancia_neta: int


class ReporteContabilidadOut(BaseModel):
    desde: date
    hasta: date
    ventas_total: int
    ventas_efectivo: int
    ventas_transferencia: int
    num_ventas: int
    invertido_total: int
    invertido_por_categoria: list[InvertidoPorCategoria]
    ganancia_neta: int
    margen_productos: int
    margen_incompleto: bool
    valor_inventario_actual: int
    por_dia: list[ContabilidadPorDia]
