from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.core.security import require_sede, solo_admin
from app.core.timezone import (
    anio_local,
    dia_local,
    fin_dia_local_a_utc_naive,
    hoy_local,
    inicio_dia_local_a_utc_naive,
    limites_dia_local,
    mes_local,
    utc_naive_a_local,
)
from app.db.session import get_db
from app.models.producto import Producto
from app.models.venta import (
    ESTADO_ACTIVA,
    METODO_EFECTIVO,
    METODO_TRANSFERENCIA,
    Venta,
    VentaItem,
)
from app.models.gasto import CategoriaGasto, Gasto
from app.models.insumo import Insumo
from app.routers.insumos import listar_insumos
from app.schemas.insumo import InsumoOut
from app.schemas.reporte import (
    ContabilidadPorDia,
    InvertidoPorCategoria,
    ReporteContabilidadOut,
    ReporteHoyOut,
    ReporteMensualOut,
    VentaPorDia,
    VentaPorHora,
    VentaPorMes,
)

router = APIRouter(prefix="/reportes", tags=["reportes"], dependencies=[Depends(require_sede)])

# Nota (BE-018): el margen se calcula con el costo ACTUAL de cada producto
# (Producto.costo en el momento de generar el reporte), no un costo histórico
# "congelado" al momento de la venta, ya que VentaItem no guarda costo_unitario
# (mismo tipo de limitación punto-en-el-tiempo-vs-actual que BE-007 documentó
# para timezone). Items cuyo producto no tiene costo definido se excluyen de
# la suma (nunca se asume costo=0) y se señalizan vía *_incompleto=True.
# Nota (BE-023): las ventas con Venta.estado == ESTADO_CANCELADA se excluyen
# por completo de todos los cálculos de este módulo (total, num_ventas,
# ticket_promedio, margen, ytd_*) — una venta cancelada no debe contarse como
# venta real, ni con costo 0 ni disparando margen_incompleto por el solo
# hecho de estar cancelada.


def _margen_query(db: Session):
    return (
        db.query(
            func.coalesce(
                func.sum(
                    case(
                        (
                            Producto.costo.isnot(None),
                            (VentaItem.precio_unitario - Producto.costo) * VentaItem.cantidad,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("margen"),
            func.sum(case((Producto.costo.is_(None), 1), else_=0)).label("items_sin_costo"),
        )
        .join(Venta, VentaItem.venta_id == Venta.id)
        .join(Producto, VentaItem.producto_id == Producto.id)
        .filter(Venta.estado == ESTADO_ACTIVA)
    )


def _calcular_margen(db: Session, desde: datetime, hasta: datetime | None = None) -> tuple[int, bool]:
    query = _margen_query(db).filter(Venta.creado_en >= desde)
    if hasta is not None:
        query = query.filter(Venta.creado_en <= hasta)
    fila = query.one()
    return int(fila.margen or 0), (fila.items_sin_costo or 0) > 0


def _margen_por_mes(db: Session, desde: datetime) -> dict[tuple[int, int], tuple[int, bool]]:
    filas = (
        _margen_query(db)
        .add_columns(
            anio_local(Venta.creado_en).label("anio"),
            mes_local(Venta.creado_en).label("mes"),
        )
        .filter(Venta.creado_en >= desde)
        .group_by("anio", "mes")
        .all()
    )
    return {
        (int(fila.anio), int(fila.mes)): (int(fila.margen or 0), (fila.items_sin_costo or 0) > 0)
        for fila in filas
    }


def _ultimos_n_meses(n: int, referencia: date) -> list[tuple[int, int]]:
    meses: list[tuple[int, int]] = []
    anio, mes = referencia.year, referencia.month
    for _ in range(n):
        meses.append((anio, mes))
        mes -= 1
        if mes == 0:
            mes = 12
            anio -= 1
    meses.reverse()
    return meses


@router.get("/hoy", response_model=ReporteHoyOut)
def reporte_hoy(db: Session = Depends(get_db)) -> ReporteHoyOut:
    hoy = hoy_local()
    inicio, fin = limites_dia_local(hoy)
    ventas = (
        db.query(Venta)
        .filter(Venta.creado_en >= inicio)
        .filter(Venta.creado_en <= fin)
        .filter(Venta.estado == ESTADO_ACTIVA)
        .all()
    )

    por_hora: dict[int, dict[str, int]] = {h: {"total": 0, "num_ventas": 0} for h in range(24)}
    for venta in ventas:
        bucket = por_hora[utc_naive_a_local(venta.creado_en).hour]
        bucket["total"] += venta.total
        bucket["num_ventas"] += 1

    margen, margen_incompleto = _calcular_margen(db, inicio, fin)

    return ReporteHoyOut(
        fecha=hoy,
        total=sum(v.total for v in ventas),
        num_ventas=len(ventas),
        por_hora=[
            VentaPorHora(hora=hora, total=datos["total"], num_ventas=datos["num_ventas"])
            for hora, datos in sorted(por_hora.items())
        ],
        margen=margen,
        margen_incompleto=margen_incompleto,
    )


@router.get("/mensual", dependencies=[solo_admin], response_model=ReporteMensualOut)
def reporte_mensual(
    meses: int = Query(default=12, ge=1, le=60),
    db: Session = Depends(get_db),
) -> ReporteMensualOut:
    hoy = hoy_local()
    meses_solicitados = _ultimos_n_meses(meses, hoy)
    anio_min = meses_solicitados[0][0]
    inicio_anio_min = inicio_dia_local_a_utc_naive(date(anio_min, 1, 1))

    filas = (
        db.query(
            anio_local(Venta.creado_en).label("anio"),
            mes_local(Venta.creado_en).label("mes"),
            func.sum(Venta.total).label("total"),
            func.count(Venta.id).label("num_ventas"),
        )
        .filter(Venta.creado_en >= inicio_anio_min)
        .filter(Venta.estado == ESTADO_ACTIVA)
        .group_by("anio", "mes")
        .all()
    )
    agregados = {(int(fila.anio), int(fila.mes)): (fila.total or 0, fila.num_ventas) for fila in filas}
    agregados_margen = _margen_por_mes(db, inicio_anio_min)

    salida: list[VentaPorMes] = []
    for anio, mes in meses_solicitados:
        total, num_ventas = agregados.get((anio, mes), (0, 0))
        ticket_promedio = total / num_ventas if num_ventas else 0.0
        margen, margen_incompleto = agregados_margen.get((anio, mes), (0, False))
        salida.append(
            VentaPorMes(
                anio=anio,
                mes=mes,
                total=total,
                num_ventas=num_ventas,
                ticket_promedio=ticket_promedio,
                margen=margen,
                margen_incompleto=margen_incompleto,
            )
        )

    inicio_anio_actual = inicio_dia_local_a_utc_naive(date(hoy.year, 1, 1))
    ytd_total = (
        db.query(func.coalesce(func.sum(Venta.total), 0))
        .filter(Venta.creado_en >= inicio_anio_actual)
        .filter(Venta.estado == ESTADO_ACTIVA)
        .scalar()
    )
    ytd_margen, ytd_margen_incompleto = _calcular_margen(db, inicio_anio_actual)

    return ReporteMensualOut(
        meses=salida,
        ytd_total=ytd_total or 0,
        ytd_margen=ytd_margen,
        ytd_margen_incompleto=ytd_margen_incompleto,
    )


DIAS_HISTORIAL_POR_DEFECTO = 30


@router.get("/diario", dependencies=[solo_admin], response_model=list[VentaPorDia])
def reporte_diario(
    desde: date | None = None,
    hasta: date | None = None,
    db: Session = Depends(get_db),
) -> list[VentaPorDia]:
    """Historial de ventas agrupado por día calendario local (el mismo "día"
    que usa `/reportes/hoy`). Solo devuelve días con al menos una venta
    activa, del más reciente al más antiguo. Por defecto, últimos 30 días."""
    hasta = hasta or hoy_local()
    desde = desde or hasta - timedelta(days=DIAS_HISTORIAL_POR_DEFECTO - 1)
    if desde > hasta:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="'desde' no puede ser posterior a 'hasta'"
        )
    inicio = inicio_dia_local_a_utc_naive(desde)
    fin = fin_dia_local_a_utc_naive(hasta)

    dia_expr = dia_local(Venta.creado_en)
    filas = (
        db.query(
            dia_expr.label("dia"),
            func.sum(Venta.total).label("total"),
            func.count(Venta.id).label("num_ventas"),
            func.sum(case((Venta.metodo_pago == METODO_EFECTIVO, Venta.total), else_=0)).label(
                "total_efectivo"
            ),
            func.sum(
                case((Venta.metodo_pago == METODO_TRANSFERENCIA, Venta.total), else_=0)
            ).label("total_transferencia"),
        )
        .filter(Venta.creado_en >= inicio)
        .filter(Venta.creado_en <= fin)
        .filter(Venta.estado == ESTADO_ACTIVA)
        .group_by("dia")
        .order_by(dia_expr.desc())
        .all()
    )

    filas_margen = (
        _margen_query(db)
        .add_columns(dia_expr.label("dia"))
        .filter(Venta.creado_en >= inicio)
        .filter(Venta.creado_en <= fin)
        .group_by("dia")
        .all()
    )
    margen_por_dia = {
        fila.dia: (int(fila.margen or 0), (fila.items_sin_costo or 0) > 0) for fila in filas_margen
    }

    salida: list[VentaPorDia] = []
    for fila in filas:
        margen, margen_incompleto = margen_por_dia.get(fila.dia, (0, False))
        salida.append(
            VentaPorDia(
                fecha=date.fromisoformat(fila.dia),
                total=fila.total or 0,
                num_ventas=fila.num_ventas,
                total_efectivo=fila.total_efectivo or 0,
                total_transferencia=fila.total_transferencia or 0,
                margen=margen,
                margen_incompleto=margen_incompleto,
            )
        )
    return salida


@router.get("/alertas-stock", response_model=list[InsumoOut])
def reporte_alertas_stock(db: Session = Depends(get_db)) -> list[InsumoOut]:
    return listar_insumos(solo_alertas=True, db=db)


@router.get("/contabilidad", dependencies=[solo_admin], response_model=ReporteContabilidadOut)
def reporte_contabilidad(
    desde: date | None = None,
    hasta: date | None = None,
    db: Session = Depends(get_db),
) -> ReporteContabilidadOut:
    """Ventas, invertido y ganancia neta de un rango de fechas locales
    (por defecto, el mes local actual).

    La ganancia neta es **base caja**: ventas activas del periodo menos todos
    los gastos (`gastos.fecha`) del periodo, incluidas compras de inventario y
    nómina. Una compra grande de vasos baja la ganancia del día en que se
    compró, aunque los vasos se usen después. `margen_productos` (precio -
    costo actual de producto) se entrega solo como referencia informativa.
    """
    hoy = hoy_local()
    desde = desde or hoy.replace(day=1)
    hasta = hasta or hoy
    if desde > hasta:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="'desde' no puede ser posterior a 'hasta'"
        )
    inicio = inicio_dia_local_a_utc_naive(desde)
    fin = fin_dia_local_a_utc_naive(hasta)

    dia_expr = dia_local(Venta.creado_en)
    filas_ventas = (
        db.query(
            dia_expr.label("dia"),
            func.sum(Venta.total).label("total"),
            func.count(Venta.id).label("num_ventas"),
            func.sum(case((Venta.metodo_pago == METODO_EFECTIVO, Venta.total), else_=0)).label(
                "efectivo"
            ),
            func.sum(case((Venta.metodo_pago == METODO_TRANSFERENCIA, Venta.total), else_=0)).label(
                "transferencia"
            ),
        )
        .filter(Venta.creado_en >= inicio, Venta.creado_en <= fin)
        .filter(Venta.estado == ESTADO_ACTIVA)
        .group_by("dia")
        .all()
    )
    ventas_por_dia = {fila.dia: int(fila.total or 0) for fila in filas_ventas}

    filas_gastos = (
        db.query(Gasto.fecha, Gasto.categoria, func.sum(Gasto.monto))
        .filter(Gasto.fecha >= desde, Gasto.fecha <= hasta)
        .group_by(Gasto.fecha, Gasto.categoria)
        .all()
    )
    invertido_por_dia: dict[str, int] = {}
    invertido_cat: dict[str, int] = {}
    for fecha, categoria, monto in filas_gastos:
        invertido_por_dia[fecha.isoformat()] = invertido_por_dia.get(fecha.isoformat(), 0) + int(monto or 0)
        invertido_cat[categoria] = invertido_cat.get(categoria, 0) + int(monto or 0)

    fila_margen = (
        _margen_query(db).filter(Venta.creado_en >= inicio, Venta.creado_en <= fin).one()
    )

    valor_inventario = sum(
        i.stock * i.costo_unitario
        for i in db.query(Insumo)
        .filter(Insumo.activo.is_(True), Insumo.stock > 0, Insumo.costo_unitario.isnot(None))
        .all()
    )

    por_dia: list[ContabilidadPorDia] = []
    dia = desde
    while dia <= hasta:
        clave = dia.isoformat()
        ventas = ventas_por_dia.get(clave, 0)
        invertido = invertido_por_dia.get(clave, 0)
        por_dia.append(
            ContabilidadPorDia(
                fecha=dia, ventas=ventas, invertido=invertido, ganancia_neta=ventas - invertido
            )
        )
        dia += timedelta(days=1)

    ventas_total = sum(ventas_por_dia.values())
    invertido_total = sum(invertido_cat.values())

    # Todas las categorías activas (aunque estén en 0) más cualquier otra que
    # tenga gastos en el periodo (desactivadas o claves sin categoría).
    categorias = db.query(CategoriaGasto).order_by(CategoriaGasto.orden, CategoriaGasto.id).all()
    invertido_por_categoria = [
        InvertidoPorCategoria(
            categoria=c.clave, etiqueta=c.nombre, total=invertido_cat.get(c.clave, 0)
        )
        for c in categorias
        if c.activa or invertido_cat.get(c.clave, 0) > 0
    ]
    claves_conocidas = {c.clave for c in categorias}
    invertido_por_categoria += [
        InvertidoPorCategoria(categoria=clave, etiqueta=clave, total=total)
        for clave, total in invertido_cat.items()
        if clave not in claves_conocidas
    ]
    return ReporteContabilidadOut(
        desde=desde,
        hasta=hasta,
        ventas_total=ventas_total,
        ventas_efectivo=sum(int(f.efectivo or 0) for f in filas_ventas),
        ventas_transferencia=sum(int(f.transferencia or 0) for f in filas_ventas),
        num_ventas=sum(int(f.num_ventas) for f in filas_ventas),
        invertido_total=invertido_total,
        invertido_por_categoria=invertido_por_categoria,
        ganancia_neta=ventas_total - invertido_total,
        margen_productos=int(fila_margen.margen or 0),
        margen_incompleto=(fila_margen.items_sin_costo or 0) > 0,
        valor_inventario_actual=int(round(valor_inventario)),
        por_dia=por_dia,
    )
