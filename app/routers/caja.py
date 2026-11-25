from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.security import require_sede
from app.core.timezone import (
    fin_dia_local_a_utc_naive,
    inicio_dia_local_a_utc_naive,
    utc_naive_a_local,
)
from app.db.session import get_db
from app.models.caja import CajaSesion
from app.models.gasto import Gasto
from app.models.venta import Venta
from app.routers.gastos import gasto_a_out
from app.schemas.caja import (
    CajaAbrir,
    CajaActualOut,
    CajaCerrar,
    CajaSesionDetalleOut,
    CajaSesionOut,
)
from app.schemas.venta import VentaOut
from app.services import caja as caja_service

router = APIRouter(prefix="/caja", tags=["caja"], dependencies=[Depends(require_sede)])


def _sesion_a_out(db: Session, sesion: CajaSesion) -> CajaSesionOut:
    """Sesión cerrada: devuelve la foto guardada. Abierta: resumen en vivo."""
    if sesion.cerrada_en is None:
        resumen = caja_service.calcular_resumen(db, sesion)
        totales = {
            "ventas_efectivo": resumen.ventas_efectivo,
            "ventas_transferencia": resumen.ventas_transferencia,
            "num_ventas": resumen.num_ventas,
            "gastos_desde_caja": resumen.gastos_desde_caja,
            "efectivo_esperado": resumen.efectivo_esperado,
        }
    else:
        totales = {
            "ventas_efectivo": sesion.ventas_efectivo or 0,
            "ventas_transferencia": sesion.ventas_transferencia or 0,
            "num_ventas": sesion.num_ventas or 0,
            "gastos_desde_caja": sesion.gastos_desde_caja or 0,
            "efectivo_esperado": sesion.efectivo_esperado or 0,
        }
    return CajaSesionOut(
        id=sesion.id,
        abierta_en=utc_naive_a_local(sesion.abierta_en),
        cerrada_en=utc_naive_a_local(sesion.cerrada_en) if sesion.cerrada_en else None,
        base_inicial=sesion.base_inicial,
        notas_apertura=sesion.notas_apertura,
        efectivo_contado=sesion.efectivo_contado,
        diferencia=sesion.diferencia,
        base_siguiente=sesion.base_siguiente,
        retiro=sesion.retiro,
        notas_cierre=sesion.notas_cierre,
        **totales,
    )


def _actual_out(db: Session, sesion: CajaSesion) -> CajaActualOut:
    s = _sesion_a_out(db, sesion)
    return CajaActualOut(
        abierta=True,
        base_sugerida=caja_service.base_sugerida(db),
        id=s.id,
        abierta_en=s.abierta_en,
        base_inicial=s.base_inicial,
        notas_apertura=s.notas_apertura,
        ventas_efectivo=s.ventas_efectivo,
        ventas_transferencia=s.ventas_transferencia,
        num_ventas=s.num_ventas,
        gastos_desde_caja=s.gastos_desde_caja,
        efectivo_esperado=s.efectivo_esperado,
        pedidos_abiertos=caja_service.contar_pedidos_abiertos(db),
    )


@router.get("/actual", response_model=CajaActualOut)
def caja_actual(db: Session = Depends(get_db)) -> CajaActualOut:
    sesion = caja_service.sesion_abierta(db)
    if sesion is None:
        return CajaActualOut(abierta=False, base_sugerida=caja_service.base_sugerida(db))
    return _actual_out(db, sesion)


@router.post("/abrir", response_model=CajaActualOut, status_code=status.HTTP_201_CREATED)
def abrir_caja(payload: CajaAbrir, db: Session = Depends(get_db)) -> CajaActualOut:
    if caja_service.sesion_abierta(db) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Ya hay una caja abierta")
    sesion = CajaSesion(base_inicial=payload.base_inicial, notas_apertura=payload.notas)
    db.add(sesion)
    try:
        db.commit()
    except IntegrityError:
        # Otra apertura simultánea ganó (índice único de caja abierta por sede).
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Ya hay una caja abierta")
    db.refresh(sesion)
    return _actual_out(db, sesion)


@router.post("/cerrar", response_model=CajaSesionOut)
def cerrar_caja(payload: CajaCerrar, db: Session = Depends(get_db)) -> CajaSesionOut:
    sesion = caja_service.sesion_abierta(db, bloqueo="exclusivo")
    if sesion is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="No hay una caja abierta")
    pendientes = caja_service.contar_pedidos_abiertos(db)
    if pendientes:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                f"Hay {pendientes} pedido(s) abierto(s). Cóbralos o descártalos "
                "antes de cerrar la caja"
            ),
        )
    if payload.base_siguiente > payload.efectivo_contado:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La base para la próxima apertura no puede superar el efectivo contado",
        )

    resumen = caja_service.calcular_resumen(db, sesion)
    sesion.ventas_efectivo = resumen.ventas_efectivo
    sesion.ventas_transferencia = resumen.ventas_transferencia
    sesion.num_ventas = resumen.num_ventas
    sesion.gastos_desde_caja = resumen.gastos_desde_caja
    sesion.efectivo_esperado = resumen.efectivo_esperado
    sesion.efectivo_contado = payload.efectivo_contado
    sesion.diferencia = payload.efectivo_contado - resumen.efectivo_esperado
    sesion.base_siguiente = payload.base_siguiente
    sesion.retiro = payload.efectivo_contado - payload.base_siguiente
    sesion.notas_cierre = payload.notas
    sesion.cerrada_en = datetime.now(timezone.utc)
    db.commit()
    db.refresh(sesion)
    return _sesion_a_out(db, sesion)


@router.get("/sesiones", response_model=list[CajaSesionOut])
def listar_sesiones(
    desde: date | None = None,
    hasta: date | None = None,
    db: Session = Depends(get_db),
) -> list[CajaSesionOut]:
    query = db.query(CajaSesion)
    if desde is not None:
        query = query.filter(CajaSesion.abierta_en >= inicio_dia_local_a_utc_naive(desde))
    if hasta is not None:
        query = query.filter(CajaSesion.abierta_en <= fin_dia_local_a_utc_naive(hasta))
    sesiones = query.order_by(CajaSesion.abierta_en.desc(), CajaSesion.id.desc()).all()
    return [_sesion_a_out(db, s) for s in sesiones]


@router.get("/sesiones/{sesion_id}", response_model=CajaSesionDetalleOut)
def obtener_sesion(sesion_id: int, db: Session = Depends(get_db)) -> CajaSesionDetalleOut:
    sesion = db.get(CajaSesion, sesion_id)
    if sesion is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Sesión de caja no encontrada")
    ventas = (
        db.query(Venta)
        .options(joinedload(Venta.items))
        .filter(Venta.caja_sesion_id == sesion_id)
        .order_by(Venta.creado_en.desc())
        .all()
    )
    gastos = (
        db.query(Gasto)
        .filter(Gasto.caja_sesion_id == sesion_id)
        .order_by(Gasto.fecha.desc(), Gasto.id.desc())
        .all()
    )
    base = _sesion_a_out(db, sesion)
    return CajaSesionDetalleOut(
        **base.model_dump(),
        ventas=[VentaOut.model_validate(v) for v in ventas],
        gastos=[gasto_a_out(g) for g in gastos],
    )
