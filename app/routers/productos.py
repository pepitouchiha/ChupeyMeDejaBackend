from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import require_sede, solo_admin
from app.db.session import get_db
from app.models.categoria import Categoria
from app.models.insumo import Insumo
from app.models.producto import Producto, ProductoInsumo
from app.models.venta import VentaItem
from app.schemas.producto import ProductoCreate, ProductoInsumoIn, ProductoOut, ProductoUpdate

router = APIRouter(prefix="/productos", tags=["productos"], dependencies=[Depends(require_sede)])


def _validar_categoria(db: Session, categoria_id: int) -> Categoria:
    categoria = db.get(Categoria, categoria_id)
    if categoria is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Categoría no encontrada")
    return categoria



@router.get("", response_model=list[ProductoOut])
def listar_productos(
    search: str | None = None,
    categoria_id: int | None = None,
    db: Session = Depends(get_db),
) -> list[Producto]:
    query = db.query(Producto)
    if search:
        query = query.filter(func.lower(Producto.nombre).contains(search.strip().lower()))
    if categoria_id is not None:
        query = query.filter(Producto.categoria_id == categoria_id)
    return query.order_by(Producto.nombre).all()


@router.get("/{producto_id}", response_model=ProductoOut)
def obtener_producto(producto_id: int, db: Session = Depends(get_db)) -> Producto:
    producto = db.get(Producto, producto_id)
    if producto is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Producto no encontrado")
    return producto


@router.post("", dependencies=[solo_admin], response_model=ProductoOut, status_code=status.HTTP_201_CREATED)
def crear_producto(
    payload: ProductoCreate,
    db: Session = Depends(get_db),
) -> Producto:
    categoria = _validar_categoria(db, payload.categoria_id)
    producto = Producto(
        nombre=payload.nombre,
        categoria_id=payload.categoria_id,
        precio=payload.precio,
        costo=payload.costo,
        estado=payload.estado.value,
        sabor=payload.sabor,
        tamano=payload.tamano,
        imagen_base64=payload.imagen_base64,
    )
    db.add(producto)
    db.commit()
    db.refresh(producto)

    return producto


@router.put("/{producto_id}", dependencies=[solo_admin], response_model=ProductoOut)
@router.patch("/{producto_id}", dependencies=[solo_admin], response_model=ProductoOut)
def actualizar_producto(
    producto_id: int,
    payload: ProductoUpdate,
    db: Session = Depends(get_db),
) -> Producto:
    producto = db.get(Producto, producto_id)
    if producto is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Producto no encontrado")

    categoria: Categoria | None = None
    if payload.categoria_id is not None:
        categoria = _validar_categoria(db, payload.categoria_id)
        producto.categoria_id = payload.categoria_id
    if payload.nombre is not None:
        producto.nombre = payload.nombre
    if payload.precio is not None:
        producto.precio = payload.precio
    if payload.estado is not None:
        producto.estado = payload.estado.value

    campos_enviados = payload.model_dump(exclude_unset=True)
    if "sabor" in campos_enviados:
        producto.sabor = payload.sabor
    if "tamano" in campos_enviados:
        producto.tamano = payload.tamano
    if "imagen_base64" in campos_enviados:
        producto.imagen_base64 = payload.imagen_base64
    if "costo" in campos_enviados:
        producto.costo = payload.costo

    db.commit()
    db.refresh(producto)

    return producto


@router.put("/{producto_id}/insumos", dependencies=[solo_admin], response_model=ProductoOut)
def reemplazar_insumos_producto(
    producto_id: int,
    payload: list[ProductoInsumoIn],
    db: Session = Depends(get_db),
) -> Producto:
    """Reemplaza la receta completa del producto (lista vacía = no consume nada)."""
    producto = db.get(Producto, producto_id)
    if producto is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Producto no encontrado")

    ids = [linea.insumo_id for linea in payload]
    repetidos = sorted({i for i in ids if ids.count(i) > 1})
    if repetidos:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"insumo_id repetido en la receta: {repetidos}",
        )
    existentes = (
        {i for (i,) in db.query(Insumo.id).filter(Insumo.id.in_(ids)).all()} if ids else set()
    )
    faltantes = sorted(set(ids) - existentes)
    if faltantes:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"Insumo(s) no encontrado(s): {faltantes}"
        )

    producto.insumos.clear()
    db.flush()
    for linea in payload:
        producto.insumos.append(ProductoInsumo(insumo_id=linea.insumo_id, cantidad=linea.cantidad))
    db.commit()
    db.refresh(producto)
    return producto


@router.delete("/{producto_id}", dependencies=[solo_admin], status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def eliminar_producto(producto_id: int, db: Session = Depends(get_db)) -> None:
    producto = db.get(Producto, producto_id)
    if producto is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Producto no encontrado")
    # Las ventas guardan referencia al producto: borrarlo dejaría el historial roto.
    if db.query(VentaItem.id).filter(VentaItem.producto_id == producto_id).first() is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Este producto ya tiene ventas registradas. Márcalo como agotado en lugar de eliminarlo.",
        )
    db.delete(producto)
    db.commit()
