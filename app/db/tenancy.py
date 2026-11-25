"""Aislamiento de datos por sede (multi-tenant).

La sede activa de la petición se guarda en `session.info["sede_id"]` (la pone
`app.core.security.require_sede`). Con eso:

- Todo SELECT del ORM sobre una clase `SedeScoped` recibe automáticamente
  `WHERE <tabla>.sede_id = :sede` (incluye `Session.get`, relaciones lazy,
  joins y agregados como `query(func.sum(Venta.total))`).
- Todo objeto `SedeScoped` nuevo recibe `sede_id` al hacer flush.
- Si una sesión intenta tocar datos de sede sin sede activa, se lanza un
  error en vez de devolver datos de todas las sedes (falla cerrado). Solo los
  procesos que de verdad necesitan ver todas las sedes (scripts, alta de una
  sede) usan `sin_filtro_de_sede(session)`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

from app.models.sede import SedeScoped

CLAVE_SEDE = "sede_id"
CLAVE_SIN_FILTRO = "sin_filtro_de_sede"


class SedeNoDefinidaError(RuntimeError):
    """Se intentó acceder a datos de una sede sin sede activa en la sesión."""


def fijar_sede(session: Session, sede_id: int) -> None:
    session.info[CLAVE_SEDE] = sede_id


def sede_actual(session: Session) -> int | None:
    return session.info.get(CLAVE_SEDE)


@contextmanager
def sin_filtro_de_sede(session: Session) -> Iterator[Session]:
    anterior = session.info.get(CLAVE_SIN_FILTRO, False)
    session.info[CLAVE_SIN_FILTRO] = True
    try:
        yield session
    finally:
        session.info[CLAVE_SIN_FILTRO] = anterior


def _toca_tabla_de_sede(state: ORMExecuteState) -> bool:
    for mapper in state.all_mappers:
        if issubclass(mapper.class_, SedeScoped):
            return True
    return False


@event.listens_for(Session, "do_orm_execute")
def _filtrar_por_sede(state: ORMExecuteState) -> None:
    if not (state.is_select or state.is_update or state.is_delete):
        return
    session = state.session
    if session.info.get(CLAVE_SIN_FILTRO):
        return
    sede_id = session.info.get(CLAVE_SEDE)
    if sede_id is None:
        if _toca_tabla_de_sede(state):
            raise SedeNoDefinidaError("Consulta a datos de sede sin sede activa")
        return
    state.statement = state.statement.options(
        with_loader_criteria(
            SedeScoped,
            lambda cls: cls.sede_id == sede_id,
            include_aliases=True,
        )
    )


@event.listens_for(Session, "before_flush")
def _asignar_sede(session: Session, flush_context, instances) -> None:  # noqa: ANN001
    sede_id = session.info.get(CLAVE_SEDE)
    sin_filtro = session.info.get(CLAVE_SIN_FILTRO)
    for obj in session.new:
        if not isinstance(obj, SedeScoped):
            continue
        if obj.sede_id is None:
            if sede_id is None:
                raise SedeNoDefinidaError(
                    f"No se puede crear {type(obj).__name__} sin sede activa"
                )
            obj.sede_id = sede_id
        elif sede_id is not None and obj.sede_id != sede_id and not sin_filtro:
            raise SedeNoDefinidaError(f"{type(obj).__name__} pertenece a otra sede")
    if sede_id is None or sin_filtro:
        return
    for obj in session.dirty:
        if isinstance(obj, SedeScoped) and obj.sede_id != sede_id:
            raise SedeNoDefinidaError(f"{type(obj).__name__} pertenece a otra sede")
