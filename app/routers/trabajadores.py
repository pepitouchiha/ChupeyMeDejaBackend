from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import require_sede, solo_admin
from app.core.timezone import hoy_local, utc_naive_a_local
from app.db.session import get_db
from app.models.gasto import CAT_NOMINA, Gasto
from app.models.trabajador import Trabajador
from app.routers.gastos import gasto_a_out
from app.schemas.gasto import GastoOut
from app.schemas.trabajador import (
    PagoCreate,
    TrabajadorCreate,
    TrabajadorOut,
    TrabajadorUpdate,
)
from app.services import caja as caja_service

router = APIRouter(
    prefix="/trabajadores", tags=["trabajadores"], dependencies=[Depends(require_sede), solo_admin]
)


def _total_mes_actual(db: Session, trabajador_id: int) -> int:
    hoy = hoy_local()
    inicio = hoy.replace(day=1)
    siguiente = date(inicio.year + (inicio.month == 12), inicio.month % 12 + 1, 1)
    total = (
        db.query(func.coalesce(func.sum(Gasto.monto), 0))
        .filter(
            Gasto.trabajador_id == trabajador_id,
            Gasto.fecha >= inicio,
            Gasto.fecha < siguiente,
        )
        .scalar()
    )
    return int(total or 0)


def _a_out(db: Session, t: Trabajador) -> TrabajadorOut:
    return TrabajadorOut(
        id=t.id,
        nombre=t.nombre,
        cargo=t.cargo,
        telefono=t.telefono,
        documento=t.documento,
        tipo_pago=t.tipo_pago,  # type: ignore[arg-type]
        monto_pago=t.monto_pago,
        activo=t.activo,
        fecha_ingreso=t.fecha_ingreso,
        creado_en=utc_naive_a_local(t.creado_en),
        total_pagado_mes_actual=_total_mes_actual(db, t.id),
    )


def _obtener_o_404(db: Session, trabajador_id: int) -> Trabajador:
    trabajador = db.get(Trabajador, trabajador_id)
    if trabajador is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Trabajador no encontrado")
    return trabajador


@router.get("", response_model=list[TrabajadorOut])
def listar_trabajadores(
    incluir_inactivos: bool = False, db: Session = Depends(get_db)
) -> list[TrabajadorOut]:
    query = db.query(Trabajador)
    if not incluir_inactivos:
        query = query.filter(Trabajador.activo.is_(True))
    return [_a_out(db, t) for t in query.order_by(Trabajador.nombre, Trabajador.id).all()]


@router.get("/{trabajador_id}", response_model=TrabajadorOut)
def obtener_trabajador(trabajador_id: int, db: Session = Depends(get_db)) -> TrabajadorOut:
    return _a_out(db, _obtener_o_404(db, trabajador_id))


@router.post("", response_model=TrabajadorOut, status_code=status.HTTP_201_CREATED)
def crear_trabajador(payload: TrabajadorCreate, db: Session = Depends(get_db)) -> TrabajadorOut:
    trabajador = Trabajador(
        nombre=payload.nombre,
        cargo=payload.cargo,
        telefono=payload.telefono,
        documento=payload.documento,
        tipo_pago=payload.tipo_pago.value,
        monto_pago=payload.monto_pago,
        activo=True,
        fecha_ingreso=payload.fecha_ingreso,
    )
    db.add(trabajador)
    db.commit()
    db.refresh(trabajador)
    return _a_out(db, trabajador)


@router.put("/{trabajador_id}", response_model=TrabajadorOut)
@router.patch("/{trabajador_id}", response_model=TrabajadorOut)
def actualizar_trabajador(
    trabajador_id: int, payload: TrabajadorUpdate, db: Session = Depends(get_db)
) -> TrabajadorOut:
    trabajador = _obtener_o_404(db, trabajador_id)
    campos = payload.model_dump(exclude_unset=True)
    for nombre_campo in ("cargo", "telefono", "documento", "fecha_ingreso"):
        if nombre_campo in campos:
            setattr(trabajador, nombre_campo, campos[nombre_campo])
    if payload.nombre is not None:
        trabajador.nombre = payload.nombre
    if payload.tipo_pago is not None:
        trabajador.tipo_pago = payload.tipo_pago.value
    if payload.monto_pago is not None:
        trabajador.monto_pago = payload.monto_pago
    if payload.activo is not None:
        trabajador.activo = payload.activo
    db.commit()
    db.refresh(trabajador)
    return _a_out(db, trabajador)


@router.delete("/{trabajador_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def eliminar_trabajador(trabajador_id: int, db: Session = Depends(get_db)) -> None:
    trabajador = _obtener_o_404(db, trabajador_id)
    pagos = (
        db.query(func.count(Gasto.id)).filter(Gasto.trabajador_id == trabajador_id).scalar() or 0
    )
    if pagos:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                f"No se puede eliminar al trabajador: tiene {pagos} pago(s) registrados. "
                "Desactívalo (activo=false) en su lugar"
            ),
        )
    db.delete(trabajador)
    db.commit()


@router.post(
    "/{trabajador_id}/pagos", response_model=GastoOut, status_code=status.HTTP_201_CREATED
)
def registrar_pago(
    trabajador_id: int, payload: PagoCreate, db: Session = Depends(get_db)
) -> GastoOut:
    trabajador = _obtener_o_404(db, trabajador_id)
    if not trabajador.activo:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="No se pueden registrar pagos a un trabajador inactivo",
        )
    gasto = Gasto(
        categoria=CAT_NOMINA,
        descripcion=(payload.descripcion or f"Pago a {trabajador.nombre}")[:255],
        monto=payload.monto,
        pagado_desde_caja=payload.pagado_desde_caja,
        trabajador_id=trabajador.id,
    )
    if payload.fecha is not None:
        gasto.fecha = payload.fecha
    caja_service.asignar_caja_si_corresponde(db, gasto)
    db.add(gasto)
    db.commit()
    db.refresh(gasto)
    return gasto_a_out(gasto)


@router.get("/{trabajador_id}/pagos", response_model=list[GastoOut])
def listar_pagos(
    trabajador_id: int,
    desde: date | None = None,
    hasta: date | None = None,
    db: Session = Depends(get_db),
) -> list[GastoOut]:
    _obtener_o_404(db, trabajador_id)
    query = db.query(Gasto).filter(Gasto.trabajador_id == trabajador_id)
    if desde is not None:
        query = query.filter(Gasto.fecha >= desde)
    if hasta is not None:
        query = query.filter(Gasto.fecha <= hasta)
    return [gasto_a_out(g) for g in query.order_by(Gasto.fecha.desc(), Gasto.id.desc()).all()]
