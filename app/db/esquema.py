"""Verificación del esquema al arrancar.

Las tablas se crean con `create_all`, que crea las que faltan pero NO modifica
las que ya existen. Si la app apunta a una base creada con una versión
anterior (sin la columna `sede_id`), cada consulta fallaría con un error 500
poco claro. Esta verificación detiene el arranque con un mensaje que explica
qué pasa.
"""

from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from app.db.base_all import Base
from app.models.sede import SedeScoped


class EsquemaDesactualizadoError(RuntimeError):
    pass


def verificar_esquema(engine: Engine) -> None:
    inspector = inspect(engine)
    existentes = set(inspector.get_table_names())
    faltantes: list[str] = []
    for mapper in Base.registry.mappers:
        clase = mapper.class_
        tabla = mapper.local_table.name
        if not issubclass(clase, SedeScoped) or tabla not in existentes:
            continue
        columnas = {c["name"] for c in inspector.get_columns(tabla)}
        if "sede_id" not in columnas:
            faltantes.append(tabla)
    if faltantes:
        raise EsquemaDesactualizadoError(
            "La base de datos tiene un esquema anterior a las sedes (falta sede_id en: "
            + ", ".join(sorted(faltantes))
            + "). Usa una base nueva o migra los datos antes de arrancar."
        )
