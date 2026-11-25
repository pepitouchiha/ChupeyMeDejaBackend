from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.gasto import CAT_COMPRA_INVENTARIO, Gasto
from app.models.insumo import (
    MOV_AJUSTE,
    MOV_ENTRADA,
    MOV_REVERSO_VENTA,
    MOV_VENTA,
    Insumo,
    MovimientoInventario,
)
from app.models.producto import ProductoInsumo
from app.models.venta import Venta
from app.services import caja as caja_service


def registrar_movimiento(
    db: Session,
    insumo: Insumo,
    *,
    tipo: str,
    cantidad: float,
    costo_total: int | None = None,
    venta_id: int | None = None,
    nota: str | None = None,
) -> MovimientoInventario:
    """Aplica `cantidad` (con signo) al stock del insumo y deja el movimiento.

    No hace commit: el llamador decide, para que stock y movimiento se
    persistan siempre en la misma transacción.
    """
    insumo.stock = insumo.stock + cantidad
    movimiento = MovimientoInventario(
        insumo_id=insumo.id,
        tipo=tipo,
        cantidad=cantidad,
        stock_resultante=insumo.stock,
        costo_total=costo_total,
        venta_id=venta_id,
        nota=nota,
    )
    db.add(movimiento)
    return movimiento


def registrar_gasto_de_entrada(
    db: Session,
    insumo: Insumo,
    movimiento: MovimientoInventario,
    *,
    pagado_desde_caja: bool,
) -> Gasto | None:
    """Crea el `Gasto` `compra_inventario` vinculado a una entrada con costo.

    Sin commit: queda en la misma transacción que el movimiento.
    """
    if movimiento.costo_total is None or movimiento.costo_total <= 0:
        return None
    db.flush()
    gasto = Gasto(
        categoria=CAT_COMPRA_INVENTARIO,
        descripcion=f"Compra: {movimiento.cantidad:g} {insumo.unidad} de {insumo.nombre}"[:255],
        monto=movimiento.costo_total,
        pagado_desde_caja=pagado_desde_caja,
        movimiento_inventario_id=movimiento.id,
    )
    caja_service.asignar_caja_si_corresponde(db, gasto)
    db.add(gasto)
    return gasto


def registrar_entrada(
    db: Session,
    insumo: Insumo,
    *,
    cantidad: float,
    costo_total: int | None,
    nota: str | None,
    registrar_gasto: bool,
    pagado_desde_caja: bool,
) -> MovimientoInventario:
    if registrar_gasto and pagado_desde_caja and costo_total is not None and costo_total > 0:
        caja_service.exigir_sesion_abierta(db, caja_service.MENSAJE_CAJA_CERRADA_GASTO)
    movimiento = registrar_movimiento(
        db, insumo, tipo=MOV_ENTRADA, cantidad=cantidad, costo_total=costo_total, nota=nota
    )
    if costo_total is not None:
        insumo.costo_unitario = round(costo_total / cantidad)
        if registrar_gasto:
            registrar_gasto_de_entrada(
                db, insumo, movimiento, pagado_desde_caja=pagado_desde_caja
            )
    return movimiento


def registrar_ajuste(
    db: Session, insumo: Insumo, *, delta: float, nota: str | None
) -> MovimientoInventario:
    return registrar_movimiento(db, insumo, tipo=MOV_AJUSTE, cantidad=delta, nota=nota)


def descontar_por_venta(db: Session, venta: Venta) -> None:
    """Descuenta del stock lo que consumen los items de la venta según la
    receta vigente: un movimiento `venta` por insumo. Sin commit. Nunca bloquea
    por falta de stock (puede quedar negativo)."""
    unidades_por_producto: dict[int, int] = {}
    for item in venta.items:
        unidades_por_producto[item.producto_id] = (
            unidades_por_producto.get(item.producto_id, 0) + item.cantidad
        )
    if not unidades_por_producto:
        return

    recetas = (
        db.query(ProductoInsumo)
        .filter(ProductoInsumo.producto_id.in_(unidades_por_producto))
        .order_by(ProductoInsumo.id)
        .all()
    )
    consumo: dict[int, float] = {}
    for linea in recetas:
        unidades = unidades_por_producto[linea.producto_id]
        consumo[linea.insumo_id] = consumo.get(linea.insumo_id, 0.0) + unidades * linea.cantidad

    for insumo_id, cantidad in consumo.items():
        insumo = db.get(Insumo, insumo_id)
        if insumo is None:
            continue
        registrar_movimiento(
            db,
            insumo,
            tipo=MOV_VENTA,
            cantidad=-cantidad,
            venta_id=venta.id,
            nota=f"Venta #{venta.id}",
        )


def revertir_venta(db: Session, venta: Venta) -> None:
    """Deja en cero lo realmente descontado por la venta (movimientos `venta`
    + `reverso_venta` existentes), sin mirar la receta actual. Sin commit."""
    db.flush()
    netos = (
        db.query(MovimientoInventario.insumo_id, func.sum(MovimientoInventario.cantidad))
        .filter(
            MovimientoInventario.venta_id == venta.id,
            MovimientoInventario.tipo.in_((MOV_VENTA, MOV_REVERSO_VENTA)),
        )
        .group_by(MovimientoInventario.insumo_id)
        .order_by(MovimientoInventario.insumo_id)
        .all()
    )
    for insumo_id, neto in netos:
        if abs(neto) < 1e-9:
            continue
        insumo = db.get(Insumo, insumo_id)
        if insumo is None:
            continue
        registrar_movimiento(
            db,
            insumo,
            tipo=MOV_REVERSO_VENTA,
            cantidad=-neto,
            venta_id=venta.id,
            nota=f"Reverso venta #{venta.id}",
        )
