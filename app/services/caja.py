from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.caja import CajaSesion
from app.models.gasto import Gasto
from app.models.venta import (
    ESTADO_ABIERTA,
    ESTADO_ACTIVA,
    METODO_EFECTIVO,
    METODO_TRANSFERENCIA,
    Venta,
)

MENSAJE_CAJA_CERRADA = "La caja está cerrada. Abre la caja para registrar ventas."
MENSAJE_CAJA_CERRADA_MESA = "La caja está cerrada. Abre la caja para abrir una mesa."
MENSAJE_CAJA_CERRADA_GASTO = "La caja está cerrada. Abre la caja para registrar pagos desde caja."


@dataclass
class ResumenCaja:
    ventas_efectivo: int
    ventas_transferencia: int
    num_ventas: int
    gastos_desde_caja: int
    efectivo_esperado: int


def sesion_abierta(db: Session) -> CajaSesion | None:
    return (
        db.query(CajaSesion)
        .filter(CajaSesion.cerrada_en.is_(None))
        .order_by(CajaSesion.id.desc())
        .first()
    )


def exigir_sesion_abierta(db: Session, mensaje: str = MENSAJE_CAJA_CERRADA) -> CajaSesion:
    sesion = sesion_abierta(db)
    if sesion is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=mensaje)
    return sesion


def asignar_caja_si_corresponde(db: Session, gasto: Gasto) -> None:
    """Si el gasto sale de caja, exige sesión abierta y la asigna. Si no sale
    de caja, deja `caja_sesion_id` en None. Sin commit."""
    if gasto.pagado_desde_caja:
        gasto.caja_sesion_id = exigir_sesion_abierta(db, MENSAJE_CAJA_CERRADA_GASTO).id
    else:
        gasto.caja_sesion_id = None


def calcular_resumen(db: Session, sesion: CajaSesion) -> ResumenCaja:
    filas = (
        db.query(Venta.metodo_pago, func.coalesce(func.sum(Venta.total), 0), func.count(Venta.id))
        .filter(Venta.caja_sesion_id == sesion.id, Venta.estado == ESTADO_ACTIVA)
        .group_by(Venta.metodo_pago)
        .all()
    )
    efectivo = transferencia = num = 0
    for metodo, suma, cantidad in filas:
        num += cantidad
        if metodo == METODO_EFECTIVO:
            efectivo += int(suma)
        elif metodo == METODO_TRANSFERENCIA:
            transferencia += int(suma)
    gastos = int(
        db.query(func.coalesce(func.sum(Gasto.monto), 0))
        .filter(Gasto.caja_sesion_id == sesion.id, Gasto.pagado_desde_caja.is_(True))
        .scalar()
        or 0
    )
    return ResumenCaja(
        ventas_efectivo=efectivo,
        ventas_transferencia=transferencia,
        num_ventas=num,
        gastos_desde_caja=gastos,
        efectivo_esperado=sesion.base_inicial + efectivo - gastos,
    )


def contar_pedidos_abiertos(db: Session) -> int:
    return db.query(func.count(Venta.id)).filter(Venta.estado == ESTADO_ABIERTA).scalar() or 0


def base_sugerida(db: Session) -> int:
    ultima = (
        db.query(CajaSesion)
        .filter(CajaSesion.cerrada_en.is_not(None))
        .order_by(CajaSesion.cerrada_en.desc(), CajaSesion.id.desc())
        .first()
    )
    return ultima.base_siguiente or 0 if ultima is not None else 0
