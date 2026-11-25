from __future__ import annotations

from datetime import date

import re
import unicodedata

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import require_sede, solo_admin
from app.core.timezone import utc_naive_a_local
from app.db.session import get_db
from app.models.gasto import CAT_NOMINA, CategoriaGasto, Gasto
from app.services import caja as caja_service
from app.schemas.gasto import (
    MENSAJE_NOMINA,
    CategoriaGastoCreate,
    CategoriaGastoOut,
    CategoriaGastoUpdate,
    GastoCreate,
    GastoOut,
    GastoUpdate,
)

router = APIRouter(prefix="/gastos", tags=["gastos"], dependencies=[Depends(require_sede)])


def gasto_a_out(gasto: Gasto) -> GastoOut:
    return GastoOut(
        id=gasto.id,
        fecha=gasto.fecha,
        categoria=gasto.categoria,
        categoria_nombre=gasto.categoria_nombre,
        categoria_color=gasto.categoria_color,
        descripcion=gasto.descripcion,
        monto=gasto.monto,
        pagado_desde_caja=gasto.pagado_desde_caja,
        caja_sesion_id=gasto.caja_sesion_id,
        movimiento_inventario_id=gasto.movimiento_inventario_id,
        trabajador_id=gasto.trabajador_id,
        creado_en=utc_naive_a_local(gasto.creado_en),
        origen=gasto.origen,  # type: ignore[arg-type]
    )


def _obtener_o_404(db: Session, gasto_id: int) -> Gasto:
    gasto = db.get(Gasto, gasto_id)
    if gasto is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Gasto no encontrado")
    return gasto


# ---------------------------------------------------------------------------
# Categorías de gasto
# ---------------------------------------------------------------------------


def _slug(nombre: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "_", sin_tildes.lower()).strip("_")
    return (slug or "categoria")[:24]


def _clave_unica(db: Session, nombre: str) -> str:
    base = _slug(nombre)
    clave, n = base, 2
    while db.query(CategoriaGasto.id).filter(CategoriaGasto.clave == clave).first() is not None:
        clave = f"{base}_{n}"
        n += 1
    return clave


def _nombre_duplicado(db: Session, nombre: str, excluir_id: int | None = None) -> bool:
    query = db.query(CategoriaGasto.id).filter(func.lower(CategoriaGasto.nombre) == nombre.lower())
    if excluir_id is not None:
        query = query.filter(CategoriaGasto.id != excluir_id)
    return query.first() is not None


def _categoria_a_out(categoria: CategoriaGasto, num_gastos: int) -> CategoriaGastoOut:
    return CategoriaGastoOut(
        id=categoria.id,
        clave=categoria.clave,
        nombre=categoria.nombre,
        color=categoria.color,
        activa=categoria.activa,
        sistema=categoria.sistema,
        seleccionable=categoria.clave != CAT_NOMINA,
        num_gastos=num_gastos,
    )


def _conteo_gastos(db: Session, clave: str) -> int:
    return db.query(func.count(Gasto.id)).filter(Gasto.categoria == clave).scalar() or 0


def _categoria_o_404(db: Session, categoria_id: int) -> CategoriaGasto:
    categoria = db.get(CategoriaGasto, categoria_id)
    if categoria is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Categoría de gasto no encontrada")
    return categoria


def _validar_categoria_para_gasto(db: Session, clave: str, actual: str | None = None) -> None:
    """Valida que `clave` pueda asignarse a un gasto manual.

    Una categoría desactivada solo se acepta si el gasto ya la tenía.
    """
    if clave == CAT_NOMINA:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=MENSAJE_NOMINA)
    categoria = db.query(CategoriaGasto).filter(CategoriaGasto.clave == clave).first()
    if categoria is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="La categoría no existe")
    if not categoria.activa and clave != actual:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="La categoría está desactivada"
        )


@router.get("/categorias", response_model=list[CategoriaGastoOut])
def listar_categorias(db: Session = Depends(get_db)) -> list[CategoriaGastoOut]:
    conteos = dict(
        db.query(Gasto.categoria, func.count(Gasto.id)).group_by(Gasto.categoria).all()
    )
    categorias = (
        db.query(CategoriaGasto).order_by(CategoriaGasto.orden, CategoriaGasto.id).all()
    )
    return [_categoria_a_out(c, int(conteos.get(c.clave, 0))) for c in categorias]


@router.post("/categorias", dependencies=[solo_admin], response_model=CategoriaGastoOut, status_code=status.HTTP_201_CREATED)
def crear_categoria(payload: CategoriaGastoCreate, db: Session = Depends(get_db)) -> CategoriaGastoOut:
    if _nombre_duplicado(db, payload.nombre):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Ya existe una categoría con ese nombre")
    orden_max = db.query(func.max(CategoriaGasto.orden)).scalar() or 0
    categoria = CategoriaGasto(
        clave=_clave_unica(db, payload.nombre),
        nombre=payload.nombre,
        activa=True,
        orden=orden_max + 1,
    )
    if payload.color is not None:
        categoria.color = payload.color.lower()
    db.add(categoria)
    db.commit()
    db.refresh(categoria)
    return _categoria_a_out(categoria, 0)


@router.patch("/categorias/{categoria_id}", dependencies=[solo_admin], response_model=CategoriaGastoOut)
def actualizar_categoria(
    categoria_id: int, payload: CategoriaGastoUpdate, db: Session = Depends(get_db)
) -> CategoriaGastoOut:
    categoria = _categoria_o_404(db, categoria_id)
    if payload.nombre is not None:
        if _nombre_duplicado(db, payload.nombre, excluir_id=categoria.id):
            raise HTTPException(
                status.HTTP_409_CONFLICT, detail="Ya existe una categoría con ese nombre"
            )
        categoria.nombre = payload.nombre
    if payload.color is not None:
        categoria.color = payload.color.lower()
    if payload.activa is not None:
        if categoria.sistema and not payload.activa:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="Las categorías del sistema no se pueden desactivar",
            )
        categoria.activa = payload.activa
    db.commit()
    db.refresh(categoria)
    return _categoria_a_out(categoria, _conteo_gastos(db, categoria.clave))


@router.delete(
    "/categorias/{categoria_id}", dependencies=[solo_admin], status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
def eliminar_categoria(categoria_id: int, db: Session = Depends(get_db)) -> None:
    categoria = _categoria_o_404(db, categoria_id)
    if categoria.sistema:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Las categorías del sistema no se pueden eliminar"
        )
    num = _conteo_gastos(db, categoria.clave)
    if num > 0:
        plural = "s" if num != 1 else ""
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                f"La categoría tiene {num} gasto{plural} registrado{plural}; "
                "desactívala en lugar de eliminarla"
            ),
        )
    db.delete(categoria)
    db.commit()


# ---------------------------------------------------------------------------
# Gastos
# ---------------------------------------------------------------------------


@router.get("", response_model=list[GastoOut])
def listar_gastos(
    desde: date | None = None,
    hasta: date | None = None,
    categoria: str | None = None,
    db: Session = Depends(get_db),
) -> list[GastoOut]:
    query = db.query(Gasto)
    if desde is not None:
        query = query.filter(Gasto.fecha >= desde)
    if hasta is not None:
        query = query.filter(Gasto.fecha <= hasta)
    if categoria is not None:
        query = query.filter(Gasto.categoria == categoria)
    gastos = query.order_by(Gasto.fecha.desc(), Gasto.id.desc()).all()
    return [gasto_a_out(g) for g in gastos]


@router.post("", response_model=GastoOut, status_code=status.HTTP_201_CREATED)
def crear_gasto(payload: GastoCreate, db: Session = Depends(get_db)) -> GastoOut:
    _validar_categoria_para_gasto(db, payload.categoria)
    gasto = Gasto(
        categoria=payload.categoria,
        descripcion=payload.descripcion,
        monto=payload.monto,
        pagado_desde_caja=payload.pagado_desde_caja,
    )
    if payload.fecha is not None:
        gasto.fecha = payload.fecha
    caja_service.asignar_caja_si_corresponde(db, gasto)
    db.add(gasto)
    db.commit()
    db.refresh(gasto)
    return gasto_a_out(gasto)


@router.patch("/{gasto_id}", dependencies=[solo_admin], response_model=GastoOut)
def actualizar_gasto(gasto_id: int, payload: GastoUpdate, db: Session = Depends(get_db)) -> GastoOut:
    gasto = _obtener_o_404(db, gasto_id)
    if payload.categoria is not None and gasto.trabajador_id is not None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No se puede cambiar la categoría de un pago de nómina",
        )
    if payload.fecha is not None:
        gasto.fecha = payload.fecha
    if payload.categoria is not None and payload.categoria != gasto.categoria:
        _validar_categoria_para_gasto(db, payload.categoria, actual=gasto.categoria)
        gasto.categoria = payload.categoria
    if payload.descripcion is not None:
        gasto.descripcion = payload.descripcion
    if payload.monto is not None:
        gasto.monto = payload.monto
    if payload.pagado_desde_caja is not None and payload.pagado_desde_caja != gasto.pagado_desde_caja:
        gasto.pagado_desde_caja = payload.pagado_desde_caja
        caja_service.asignar_caja_si_corresponde(db, gasto)
    db.commit()
    db.refresh(gasto)
    return gasto_a_out(gasto)


@router.delete("/{gasto_id}", dependencies=[solo_admin], status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def eliminar_gasto(gasto_id: int, db: Session = Depends(get_db)) -> None:
    """Quita solo el registro contable; si el gasto viene de una entrada de
    inventario, el stock y el movimiento de esa entrada no se tocan."""
    gasto = _obtener_o_404(db, gasto_id)
    db.delete(gasto)
    db.commit()
