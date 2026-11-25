from __future__ import annotations

import re
import unicodedata
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import require_sede, solo_admin
from app.core.timezone import (
    fin_dia_local_a_utc_naive,
    inicio_dia_local_a_utc_naive,
    utc_naive_a_local,
)
from app.db.session import get_db
from app.models.insumo import ESTADO_OK, Insumo, MovimientoInventario, TipoInsumo, calcular_estado
from app.models.producto import ProductoInsumo
from app.schemas.insumo import (
    AjusteStock,
    ConteoInsumo,
    EntradaInsumo,
    InsumoCreate,
    InsumoOut,
    InsumoUpdate,
    MovimientoOut,
    TipoInsumoCreate,
    TipoInsumoOut,
    TipoInsumoUpdate,
)
from app.services import inventario

router = APIRouter(prefix="/insumos", tags=["insumos"], dependencies=[Depends(require_sede)])




def _a_out(insumo: Insumo) -> InsumoOut:
    return InsumoOut(
        id=insumo.id,
        nombre=insumo.nombre,
        tipo=insumo.tipo,
        tipo_nombre=insumo.tipo_nombre,
        unidad=insumo.unidad,
        stock=insumo.stock,
        stock_minimo=insumo.stock_minimo,
        costo_unitario=insumo.costo_unitario,
        activo=insumo.activo,
        estado=calcular_estado(insumo.stock, insumo.stock_minimo),  # type: ignore[arg-type]
    )


def _movimiento_a_out(mov: MovimientoInventario) -> MovimientoOut:
    return MovimientoOut(
        id=mov.id,
        insumo_id=mov.insumo_id,
        tipo=mov.tipo,  # type: ignore[arg-type]
        cantidad=mov.cantidad,
        stock_resultante=mov.stock_resultante,
        costo_total=mov.costo_total,
        venta_id=mov.venta_id,
        nota=mov.nota,
        creado_en=utc_naive_a_local(mov.creado_en),
    )


def _obtener_o_404(db: Session, insumo_id: int) -> Insumo:
    insumo = db.get(Insumo, insumo_id)
    if insumo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Insumo no encontrado")
    return insumo


# ---------------------------------------------------------------------------
# Tipos de insumo (van antes de /{insumo_id} para que "tipos" no se lea como id)
# ---------------------------------------------------------------------------


def _slug(nombre: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "_", sin_tildes.lower()).strip("_")
    return (slug or "tipo")[:24]


def _clave_tipo_unica(db: Session, nombre: str) -> str:
    base = _slug(nombre)
    clave, n = base, 2
    while db.query(TipoInsumo.id).filter(TipoInsumo.clave == clave).first() is not None:
        clave = f"{base}_{n}"
        n += 1
    return clave


def _tipo_nombre_duplicado(db: Session, nombre: str, excluir_id: int | None = None) -> bool:
    query = db.query(TipoInsumo.id).filter(func.lower(TipoInsumo.nombre) == nombre.lower())
    if excluir_id is not None:
        query = query.filter(TipoInsumo.id != excluir_id)
    return query.first() is not None


def _conteo_insumos_por_tipo(db: Session) -> dict[str, int]:
    return dict(db.query(Insumo.tipo, func.count(Insumo.id)).group_by(Insumo.tipo).all())


def _tipo_a_out(tipo: TipoInsumo, num: int) -> TipoInsumoOut:
    return TipoInsumoOut(
        id=tipo.id, clave=tipo.clave, nombre=tipo.nombre, activo=tipo.activo, num_insumos=num
    )


def _tipo_o_404(db: Session, tipo_id: int) -> TipoInsumo:
    tipo = db.get(TipoInsumo, tipo_id)
    if tipo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Tipo de insumo no encontrado")
    return tipo


def _validar_tipo(db: Session, clave: str, actual: str | None = None) -> None:
    """El tipo debe existir en la sede y estar activo (salvo que el insumo ya lo tuviera)."""
    tipo = db.query(TipoInsumo).filter(TipoInsumo.clave == clave).first()
    if tipo is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="El tipo de insumo no existe")
    if not tipo.activo and clave != actual:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="El tipo de insumo está desactivado")


@router.get("/tipos", response_model=list[TipoInsumoOut])
def listar_tipos(db: Session = Depends(get_db)) -> list[TipoInsumoOut]:
    conteos = _conteo_insumos_por_tipo(db)
    tipos = db.query(TipoInsumo).order_by(TipoInsumo.orden, TipoInsumo.id).all()
    return [_tipo_a_out(t, int(conteos.get(t.clave, 0))) for t in tipos]


@router.post("/tipos", dependencies=[solo_admin], response_model=TipoInsumoOut, status_code=status.HTTP_201_CREATED)
def crear_tipo(payload: TipoInsumoCreate, db: Session = Depends(get_db)) -> TipoInsumoOut:
    if _tipo_nombre_duplicado(db, payload.nombre):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Ya existe un tipo con ese nombre")
    orden_max = db.query(func.max(TipoInsumo.orden)).scalar() or 0
    tipo = TipoInsumo(
        clave=_clave_tipo_unica(db, payload.nombre),
        nombre=payload.nombre,
        activo=True,
        orden=orden_max + 1,
    )
    db.add(tipo)
    db.commit()
    db.refresh(tipo)
    return _tipo_a_out(tipo, 0)


@router.patch("/tipos/{tipo_id}", dependencies=[solo_admin], response_model=TipoInsumoOut)
def actualizar_tipo(tipo_id: int, payload: TipoInsumoUpdate, db: Session = Depends(get_db)) -> TipoInsumoOut:
    tipo = _tipo_o_404(db, tipo_id)
    if payload.nombre is not None:
        if _tipo_nombre_duplicado(db, payload.nombre, excluir_id=tipo.id):
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Ya existe un tipo con ese nombre")
        tipo.nombre = payload.nombre
    if payload.activo is not None:
        tipo.activo = payload.activo
    db.commit()
    db.refresh(tipo)
    return _tipo_a_out(tipo, int(_conteo_insumos_por_tipo(db).get(tipo.clave, 0)))


@router.delete("/tipos/{tipo_id}", dependencies=[solo_admin], status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def eliminar_tipo(tipo_id: int, db: Session = Depends(get_db)) -> None:
    tipo = _tipo_o_404(db, tipo_id)
    num = int(_conteo_insumos_por_tipo(db).get(tipo.clave, 0))
    if num > 0:
        plural = "s" if num != 1 else ""
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Hay {num} insumo{plural} de este tipo; cámbiales el tipo o desactívalo en lugar de eliminarlo",
        )
    db.delete(tipo)
    db.commit()


# ---------------------------------------------------------------------------
# Insumos
# ---------------------------------------------------------------------------


@router.get("", response_model=list[InsumoOut])
def listar_insumos(
    tipo: str | None = None,
    solo_alertas: bool = False,
    incluir_inactivos: bool = False,
    db: Session = Depends(get_db),
) -> list[InsumoOut]:
    query = db.query(Insumo)
    if tipo is not None:
        query = query.filter(Insumo.tipo == tipo)
    if not incluir_inactivos:
        query = query.filter(Insumo.activo.is_(True))
    salida = [_a_out(i) for i in query.order_by(Insumo.nombre).all()]
    if solo_alertas:
        salida = [i for i in salida if i.estado.value != ESTADO_OK]
    return salida


@router.get("/{insumo_id}", response_model=InsumoOut)
def obtener_insumo(insumo_id: int, db: Session = Depends(get_db)) -> InsumoOut:
    return _a_out(_obtener_o_404(db, insumo_id))


@router.post("", dependencies=[solo_admin], response_model=InsumoOut, status_code=status.HTTP_201_CREATED)
def crear_insumo(
    payload: InsumoCreate,
    db: Session = Depends(get_db),
) -> InsumoOut:
    _validar_tipo(db, payload.tipo)
    insumo = Insumo(
        nombre=payload.nombre,
        tipo=payload.tipo,
        unidad=payload.unidad,
        stock=0,
        stock_minimo=payload.stock_minimo,
        costo_unitario=payload.costo_unitario,
        activo=True,
    )
    db.add(insumo)
    db.flush()
    if payload.stock > 0:
        inventario.registrar_ajuste(db, insumo, delta=payload.stock, nota="Stock inicial")
    db.commit()
    db.refresh(insumo)
    return _a_out(insumo)


@router.put("/{insumo_id}", dependencies=[solo_admin], response_model=InsumoOut)
@router.patch("/{insumo_id}", dependencies=[solo_admin], response_model=InsumoOut)
def actualizar_insumo(
    insumo_id: int,
    payload: InsumoUpdate,
    db: Session = Depends(get_db),
) -> InsumoOut:
    insumo = _obtener_o_404(db, insumo_id)

    campos = payload.model_dump(exclude_unset=True)
    if "nombre" in campos and payload.nombre is not None:
        insumo.nombre = payload.nombre
    if "tipo" in campos and payload.tipo is not None:
        _validar_tipo(db, payload.tipo, actual=insumo.tipo)
        insumo.tipo = payload.tipo
    if "unidad" in campos and payload.unidad is not None:
        insumo.unidad = payload.unidad
    if "stock_minimo" in campos and payload.stock_minimo is not None:
        insumo.stock_minimo = payload.stock_minimo
    if "costo_unitario" in campos:
        insumo.costo_unitario = payload.costo_unitario
    if "activo" in campos and payload.activo is not None:
        insumo.activo = payload.activo

    db.commit()
    db.refresh(insumo)
    return _a_out(insumo)


@router.post("/{insumo_id}/entradas", dependencies=[solo_admin], response_model=InsumoOut)
def registrar_entrada(
    insumo_id: int,
    payload: EntradaInsumo,
    db: Session = Depends(get_db),
) -> InsumoOut:
    insumo = _obtener_o_404(db, insumo_id)
    inventario.registrar_entrada(
        db,
        insumo,
        cantidad=payload.cantidad,
        costo_total=payload.costo_total,
        nota=payload.nota,
        registrar_gasto=payload.registrar_gasto,
        pagado_desde_caja=payload.pagado_desde_caja,
    )
    db.commit()
    db.refresh(insumo)
    return _a_out(insumo)


@router.post("/{insumo_id}/ajustar-stock", dependencies=[solo_admin], response_model=InsumoOut)
def ajustar_stock(
    insumo_id: int,
    payload: AjusteStock,
    db: Session = Depends(get_db),
) -> InsumoOut:
    insumo = _obtener_o_404(db, insumo_id)

    nuevo_stock = insumo.stock + payload.cantidad
    if nuevo_stock < 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"El ajuste dejaría el stock en {nuevo_stock}, no puede ser negativo",
        )
    inventario.registrar_ajuste(db, insumo, delta=payload.cantidad, nota=payload.nota)
    db.commit()
    db.refresh(insumo)
    return _a_out(insumo)


@router.post("/{insumo_id}/conteo", dependencies=[solo_admin], response_model=InsumoOut)
def contar_stock(
    insumo_id: int,
    payload: ConteoInsumo,
    db: Session = Depends(get_db),
) -> InsumoOut:
    insumo = _obtener_o_404(db, insumo_id)

    delta = payload.stock_contado - insumo.stock
    if delta == 0:
        return _a_out(insumo)

    movimiento = inventario.registrar_ajuste(db, insumo, delta=delta, nota=payload.nota)
    # Fija el valor exacto contado y evita arrastre de error de punto flotante.
    insumo.stock = payload.stock_contado
    movimiento.stock_resultante = payload.stock_contado
    db.commit()
    db.refresh(insumo)
    return _a_out(insumo)


@router.get("/{insumo_id}/movimientos", response_model=list[MovimientoOut])
def listar_movimientos(
    insumo_id: int,
    desde: date | None = None,
    hasta: date | None = None,
    db: Session = Depends(get_db),
) -> list[MovimientoOut]:
    _obtener_o_404(db, insumo_id)
    query = db.query(MovimientoInventario).filter(MovimientoInventario.insumo_id == insumo_id)
    if desde is not None:
        query = query.filter(MovimientoInventario.creado_en >= inicio_dia_local_a_utc_naive(desde))
    if hasta is not None:
        query = query.filter(MovimientoInventario.creado_en <= fin_dia_local_a_utc_naive(hasta))
    movimientos = query.order_by(
        MovimientoInventario.creado_en.desc(), MovimientoInventario.id.desc()
    ).all()
    return [_movimiento_a_out(m) for m in movimientos]


@router.delete("/{insumo_id}", dependencies=[solo_admin], status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def eliminar_insumo(insumo_id: int, db: Session = Depends(get_db)) -> None:
    insumo = _obtener_o_404(db, insumo_id)
    movimientos = (
        db.query(func.count(MovimientoInventario.id))
        .filter(MovimientoInventario.insumo_id == insumo_id)
        .scalar()
        or 0
    )
    if movimientos:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                f"No se puede eliminar el insumo: tiene {movimientos} movimiento(s) "
                "registrados. Desactívalo (activo=false) en su lugar"
            ),
        )
    recetas = (
        db.query(func.count(ProductoInsumo.id))
        .filter(ProductoInsumo.insumo_id == insumo_id)
        .scalar()
        or 0
    )
    if recetas:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                f"No se puede eliminar el insumo: está en la receta de {recetas} producto(s). "
                "Desactívalo (activo=false) en su lugar"
            ),
        )
    db.delete(insumo)
    db.commit()
