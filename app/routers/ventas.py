from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session, joinedload

from app.core import config
from app.core.security import require_auth
from app.core.timezone import (
    fin_dia_local_a_utc_naive,
    inicio_dia_local_a_utc_naive,
    utc_naive_a_local,
)
from app.db.session import get_db
from app.models.mesa import ESTADO_LIBRE, ESTADO_OCUPADA, Mesa
from app.models.producto import Producto
from app.models.venta import ESTADO_ABIERTA, ESTADO_ACTIVA, ESTADO_CANCELADA, Venta, VentaItem
from app.schemas.venta import (
    EstadoVenta,
    VentaAbrir,
    VentaAgregarItems,
    VentaCambiarCantidadItem,
    VentaCerrar,
    VentaCreate,
    VentaOut,
    VentaUpdate,
)
from app.services.sheets_service import sync_venta_to_sheets

router = APIRouter(prefix="/ventas", tags=["ventas"], dependencies=[Depends(require_auth)])


def _venta_a_dict_para_sheets(venta: Venta, productos_por_id: dict[int, Producto]) -> dict[str, Any]:
    return {
        "id": venta.id,
        "creado_en": utc_naive_a_local(venta.creado_en).isoformat(),
        "metodo_pago": venta.metodo_pago,
        "mesa_id": venta.mesa_id,
        "total": venta.total,
        "estado": venta.estado,
        "items": [
            {
                "producto_id": item.producto_id,
                "cantidad": item.cantidad,
                "precio_unitario": item.precio_unitario,
                "nombre_producto": productos_por_id[item.producto_id].nombre,
            }
            for item in venta.items
        ],
    }


def _mesa_tiene_otra_venta_activa(db: Session, mesa_id: int, excluir_venta_id: int) -> bool:
    return (
        db.query(Venta.id)
        .filter(
            Venta.mesa_id == mesa_id,
            Venta.estado == ESTADO_ACTIVA,
            Venta.id != excluir_venta_id,
        )
        .first()
        is not None
    )


@router.get("", response_model=list[VentaOut])
def listar_ventas(
    desde: date | None = None,
    hasta: date | None = None,
    mesa_id: int | None = None,
    estado: EstadoVenta | None = None,
    db: Session = Depends(get_db),
) -> list[Venta]:
    query = db.query(Venta).options(joinedload(Venta.items))
    if desde is not None:
        query = query.filter(Venta.creado_en >= inicio_dia_local_a_utc_naive(desde))
    if hasta is not None:
        query = query.filter(Venta.creado_en <= fin_dia_local_a_utc_naive(hasta))
    if mesa_id is not None:
        query = query.filter(Venta.mesa_id == mesa_id)
    if estado is not None:
        query = query.filter(Venta.estado == estado.value)
    return query.order_by(Venta.creado_en.desc()).all()


@router.post("", response_model=VentaOut, status_code=status.HTTP_201_CREATED)
def crear_venta(
    payload: VentaCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> Venta:
    mesa: Mesa | None = None
    if payload.mesa_id is not None:
        mesa = db.get(Mesa, payload.mesa_id)
        if mesa is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Mesa no encontrada")

    productos_por_id: dict[int, Producto] = {}
    for item in payload.items:
        if item.producto_id in productos_por_id:
            continue
        producto = db.get(Producto, item.producto_id)
        if producto is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail=f"Producto {item.producto_id} no encontrado",
            )
        productos_por_id[item.producto_id] = producto

    total = 0
    venta_items: list[VentaItem] = []
    for item in payload.items:
        producto = productos_por_id[item.producto_id]
        total += producto.precio * item.cantidad
        venta_items.append(
            VentaItem(
                producto_id=producto.id,
                cantidad=item.cantidad,
                precio_unitario=producto.precio,
            )
        )

    venta = Venta(
        mesa_id=payload.mesa_id,
        metodo_pago=payload.metodo_pago.value,
        total=total,
        items=venta_items,
    )
    db.add(venta)

    if mesa is not None:
        mesa.estado = ESTADO_OCUPADA

    db.commit()
    db.refresh(venta)

    if config.SHEETS_SYNC_ENABLED:
        venta_dict = _venta_a_dict_para_sheets(venta, productos_por_id)
        background_tasks.add_task(sync_venta_to_sheets, venta_dict)

    return venta


@router.post("/abrir", response_model=VentaOut, status_code=status.HTTP_201_CREATED)
def abrir_venta(payload: VentaAbrir, db: Session = Depends(get_db)) -> Venta:
    """Abre un pedido vacío (estado 'abierta') en una mesa, sin cobrar nada."""
    mesa = db.get(Mesa, payload.mesa_id)
    if mesa is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Mesa no encontrada")

    ya_tiene_pedido_abierto = (
        db.query(Venta.id)
        .filter(Venta.mesa_id == payload.mesa_id, Venta.estado == ESTADO_ABIERTA)
        .first()
        is not None
    )
    if ya_tiene_pedido_abierto:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="La mesa ya tiene un pedido abierto"
        )

    venta = Venta(
        mesa_id=payload.mesa_id,
        metodo_pago=None,
        estado=ESTADO_ABIERTA,
        total=0,
        items=[],
    )
    db.add(venta)
    mesa.estado = ESTADO_OCUPADA

    db.commit()
    db.refresh(venta)
    return venta


@router.get("/{venta_id}", response_model=VentaOut)
def obtener_venta(venta_id: int, db: Session = Depends(get_db)) -> Venta:
    venta = (
        db.query(Venta)
        .options(joinedload(Venta.items))
        .filter(Venta.id == venta_id)
        .first()
    )
    if venta is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Venta no encontrada")
    return venta


@router.put("/{venta_id}", response_model=VentaOut)
def actualizar_venta(
    venta_id: int,
    payload: VentaUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> Venta:
    venta = db.get(Venta, venta_id)
    if venta is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Venta no encontrada")
    if venta.estado == ESTADO_CANCELADA:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="No se puede editar una venta cancelada")

    mesa_nueva: Mesa | None = None
    if payload.mesa_id is not None:
        mesa_nueva = db.get(Mesa, payload.mesa_id)
        if mesa_nueva is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Mesa no encontrada")

    productos_por_id: dict[int, Producto] = {}
    for item in payload.items:
        if item.producto_id in productos_por_id:
            continue
        producto = db.get(Producto, item.producto_id)
        if producto is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail=f"Producto {item.producto_id} no encontrado",
            )
        productos_por_id[item.producto_id] = producto

    total = 0
    nuevos_items: list[VentaItem] = []
    for item in payload.items:
        producto = productos_por_id[item.producto_id]
        total += producto.precio * item.cantidad
        nuevos_items.append(
            VentaItem(
                producto_id=producto.id,
                cantidad=item.cantidad,
                precio_unitario=producto.precio,
            )
        )

    mesa_vieja_id = venta.mesa_id
    mesa_nueva_id = payload.mesa_id

    if mesa_nueva_id != mesa_vieja_id:
        if mesa_nueva is not None:
            mesa_nueva.estado = ESTADO_OCUPADA
        if mesa_vieja_id is not None and not _mesa_tiene_otra_venta_activa(
            db, mesa_vieja_id, venta.id
        ):
            mesa_vieja = db.get(Mesa, mesa_vieja_id)
            if mesa_vieja is not None:
                mesa_vieja.estado = ESTADO_LIBRE

    venta.items = nuevos_items
    venta.total = total
    venta.mesa_id = payload.mesa_id
    venta.metodo_pago = payload.metodo_pago.value

    db.commit()
    db.refresh(venta)

    if config.SHEETS_SYNC_ENABLED:
        venta_dict = _venta_a_dict_para_sheets(venta, productos_por_id)
        background_tasks.add_task(sync_venta_to_sheets, venta_dict)

    return venta


@router.post("/{venta_id}/cancelar", response_model=VentaOut)
def cancelar_venta(
    venta_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> Venta:
    venta = db.get(Venta, venta_id)
    if venta is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Venta no encontrada")
    if venta.estado == ESTADO_CANCELADA:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="La venta ya está cancelada")

    venta.estado = ESTADO_CANCELADA

    if venta.mesa_id is not None:
        mesa = db.get(Mesa, venta.mesa_id)
        if mesa is not None:
            mesa.estado = ESTADO_LIBRE

    db.commit()
    db.refresh(venta)

    if config.SHEETS_SYNC_ENABLED:
        producto_ids = {item.producto_id for item in venta.items}
        productos_por_id = {
            producto.id: producto
            for producto in db.query(Producto).filter(Producto.id.in_(producto_ids)).all()
        }
        venta_dict = _venta_a_dict_para_sheets(venta, productos_por_id)
        background_tasks.add_task(sync_venta_to_sheets, venta_dict)

    return venta


@router.post("/{venta_id}/items", response_model=VentaOut)
def agregar_items_venta(
    venta_id: int,
    payload: VentaAgregarItems,
    db: Session = Depends(get_db),
) -> Venta:
    """Agrega productos nuevos a un pedido abierto en curso (BE-026).

    Si el pedido ya tiene una línea del mismo producto con el mismo precio
    unitario, se le suma la cantidad (así el "+" del panel de la mesa no
    duplica líneas); si no, se crea un `VentaItem` nuevo con el precio
    vigente en este momento. Una línea con precio viejo (el producto cambió
    de precio) nunca se fusiona, para no alterar lo ya pedido.
    """
    venta = db.get(Venta, venta_id)
    if venta is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Venta no encontrada")
    if venta.estado != ESTADO_ABIERTA:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Solo se pueden agregar productos a un pedido abierto",
        )

    productos_por_id: dict[int, Producto] = {}
    for item in payload.items:
        if item.producto_id in productos_por_id:
            continue
        producto = db.get(Producto, item.producto_id)
        if producto is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail=f"Producto {item.producto_id} no encontrado",
            )
        productos_por_id[item.producto_id] = producto

    incremento = 0
    for item in payload.items:
        producto = productos_por_id[item.producto_id]
        incremento += producto.precio * item.cantidad
        existente = next(
            (
                linea
                for linea in venta.items
                if linea.producto_id == producto.id and linea.precio_unitario == producto.precio
            ),
            None,
        )
        if existente is not None:
            existente.cantidad += item.cantidad
        else:
            venta.items.append(
                VentaItem(
                    producto_id=producto.id,
                    cantidad=item.cantidad,
                    precio_unitario=producto.precio,
                )
            )

    venta.total += incremento

    db.commit()
    db.refresh(venta)
    return venta


@router.patch("/{venta_id}/items/{item_id}", response_model=VentaOut)
def cambiar_cantidad_item_venta(
    venta_id: int,
    item_id: int,
    payload: VentaCambiarCantidadItem,
    db: Session = Depends(get_db),
) -> Venta:
    """Cambia la cantidad de un item de un pedido abierto (botones -/+ del
    panel de la mesa). Para quitar la línea por completo se usa el DELETE."""
    venta = db.get(Venta, venta_id)
    if venta is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Venta no encontrada")

    item = db.get(VentaItem, item_id)
    if item is None or item.venta_id != venta_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Item no encontrado")

    if venta.estado != ESTADO_ABIERTA:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Solo se pueden modificar productos de un pedido abierto",
        )

    venta.total += item.precio_unitario * (payload.cantidad - item.cantidad)
    item.cantidad = payload.cantidad

    db.commit()
    db.refresh(venta)
    return venta


@router.delete("/{venta_id}/items/{item_id}", response_model=VentaOut)
def quitar_item_venta(venta_id: int, item_id: int, db: Session = Depends(get_db)) -> Venta:
    """Quita un item puntual de un pedido abierto en curso (BE-026)."""
    venta = db.get(Venta, venta_id)
    if venta is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Venta no encontrada")

    item = db.get(VentaItem, item_id)
    if item is None or item.venta_id != venta_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Item no encontrado")

    if venta.estado != ESTADO_ABIERTA:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Solo se pueden quitar productos de un pedido abierto",
        )

    venta.total -= item.precio_unitario * item.cantidad
    db.delete(item)

    db.commit()
    db.refresh(venta)
    return venta


@router.post("/{venta_id}/cerrar", response_model=VentaOut)
def cerrar_venta(
    venta_id: int,
    payload: VentaCerrar,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> Venta:
    """Cierra/cobra un pedido abierto: pasa a 'activa', libera la mesa y
    sincroniza a Sheets (primera sincronización de esta venta)."""
    venta = db.get(Venta, venta_id)
    if venta is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Venta no encontrada")
    if venta.estado != ESTADO_ABIERTA:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Solo se puede cerrar un pedido abierto"
        )
    if not venta.items:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="No se puede cerrar un pedido sin productos"
        )

    venta.total = sum(item.precio_unitario * item.cantidad for item in venta.items)
    venta.metodo_pago = payload.metodo_pago.value
    venta.estado = ESTADO_ACTIVA

    if venta.mesa_id is not None:
        mesa = db.get(Mesa, venta.mesa_id)
        if mesa is not None:
            mesa.estado = ESTADO_LIBRE

    db.commit()
    db.refresh(venta)

    if config.SHEETS_SYNC_ENABLED:
        producto_ids = {item.producto_id for item in venta.items}
        productos_por_id = {
            producto.id: producto
            for producto in db.query(Producto).filter(Producto.id.in_(producto_ids)).all()
        }
        venta_dict = _venta_a_dict_para_sheets(venta, productos_por_id)
        background_tasks.add_task(sync_venta_to_sheets, venta_dict)

    return venta


@router.post("/{venta_id}/descartar", response_model=None)
def descartar_venta(
    venta_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> Venta | Response:
    """Descarta un pedido abierto sin cobrar y libera la mesa.

    - Si el pedido no tiene items: hard-delete (nunca fue una venta real, ni
      se sincronizó a Sheets), responde `204 No Content` sin cuerpo.
    - Si el pedido tiene items: se conserva como soft-delete
      (`estado: "cancelada"`, igual criterio que `POST /ventas/{id}/cancelar`
      de BE-020) para dejar rastro de auditoría, y responde `200` con la
      `VentaOut` resultante.
    """
    venta = db.get(Venta, venta_id)
    if venta is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Venta no encontrada")
    if venta.estado != ESTADO_ABIERTA:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Solo se puede descartar un pedido abierto"
        )

    if venta.mesa_id is not None:
        mesa = db.get(Mesa, venta.mesa_id)
        if mesa is not None:
            mesa.estado = ESTADO_LIBRE

    if not venta.items:
        db.delete(venta)
        db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    producto_ids = {item.producto_id for item in venta.items}
    productos_por_id = {
        producto.id: producto
        for producto in db.query(Producto).filter(Producto.id.in_(producto_ids)).all()
    }

    venta.estado = ESTADO_CANCELADA

    db.commit()
    db.refresh(venta)

    if config.SHEETS_SYNC_ENABLED:
        venta_dict = _venta_a_dict_para_sheets(venta, productos_por_id)
        background_tasks.add_task(sync_venta_to_sheets, venta_dict)

    return VentaOut.model_validate(venta)
