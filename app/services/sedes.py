from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.tenancy import fijar_sede, sede_actual
from app.models.configuracion_negocio import ConfiguracionNegocio
from app.models.gasto import CATEGORIAS_INICIALES, CategoriaGasto
from app.models.insumo import TIPOS_INICIALES, TipoInsumo
from app.models.sede import Sede

NOMBRE_NEGOCIO = "Chupe y Me Deja"


def crear_sede(db: Session, nombre: str, direccion: str | None) -> Sede:
    """Crea una sede con lo mínimo para operar: categorías de gasto, tipos
    de insumo y la configuración de impresión. Sin commit."""
    sede = Sede(nombre=nombre, direccion=direccion)
    db.add(sede)
    db.flush()

    anterior = sede_actual(db)
    fijar_sede(db, sede.id)
    try:
        for orden, (clave, nombre_cat, color) in enumerate(CATEGORIAS_INICIALES):
            db.add(CategoriaGasto(clave=clave, nombre=nombre_cat, color=color, orden=orden))
        sembrar_tipos_insumo(db)
        db.add(
            ConfiguracionNegocio(
                nombre_negocio=f"{NOMBRE_NEGOCIO} {nombre}"[:100],
                direccion=direccion,
            )
        )
        db.flush()
    finally:
        if anterior is None:
            db.info.pop("sede_id", None)
        else:
            fijar_sede(db, anterior)
    return sede


def sembrar_tipos_insumo(db: Session) -> None:
    """Crea los tipos de insumo iniciales en la sede activa de `db`. Sin commit."""
    for orden, (clave, nombre) in enumerate(TIPOS_INICIALES):
        db.add(TipoInsumo(clave=clave, nombre=nombre, orden=orden))


def completar_datos_base(db: Session) -> None:
    """Agrega los tipos de insumo iniciales a las sedes que no tengan ninguno
    (sedes creadas antes de que existieran los tipos administrables)."""
    anterior = sede_actual(db)
    try:
        for sede in db.query(Sede).all():
            fijar_sede(db, sede.id)
            if db.query(TipoInsumo.id).first() is None:
                sembrar_tipos_insumo(db)
                # Guardar antes de cambiar de sede: el sede_id se asigna al hacer flush.
                db.flush()
        db.commit()
    finally:
        if anterior is None:
            db.info.pop("sede_id", None)
        else:
            fijar_sede(db, anterior)
