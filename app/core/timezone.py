"""Helpers de conversión hora local (BUSINESS_TIMEZONE) <-> UTC naive.

Las fechas (`Venta.creado_en`, etc.) se guardan como naive-UTC. Estos helpers
centralizan la conversión entre "hora local del negocio" (la que percibe el
usuario en Colombia) y los valores naive-UTC que hay que usar para filtrar y
agrupar contra esas columnas. Las expresiones SQL funcionan igual en SQLite
(desarrollo local) y en PostgreSQL (Supabase, producción).
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone

from sqlalchemy import ColumnElement, DateTime, String, extract
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement

from app.core.config import BUSINESS_TIMEZONE, BUSINESS_TIMEZONE_NAME


def hoy_local() -> date:
    """`date` de "hoy" en hora local del negocio (no la del servidor)."""
    return datetime.now(BUSINESS_TIMEZONE).date()


def inicio_dia_local_a_utc_naive(dia: date) -> datetime:
    """00:00:00 local de `dia`, convertido a su equivalente naive-UTC."""
    inicio_local = datetime.combine(dia, time.min, tzinfo=BUSINESS_TIMEZONE)
    return inicio_local.astimezone(timezone.utc).replace(tzinfo=None)


def fin_dia_local_a_utc_naive(dia: date) -> datetime:
    """23:59:59.999999 local de `dia`, convertido a su equivalente naive-UTC."""
    fin_local = datetime.combine(dia, time.max, tzinfo=BUSINESS_TIMEZONE)
    return fin_local.astimezone(timezone.utc).replace(tzinfo=None)


def limites_dia_local(dia: date) -> tuple[datetime, datetime]:
    """Límites (inicio, fin) de `dia` en hora local, como naive-UTC."""
    return inicio_dia_local_a_utc_naive(dia), fin_dia_local_a_utc_naive(dia)


def utc_naive_a_local(valor: datetime) -> datetime:
    """Convierte un valor naive-UTC (leído de la BD) a hora local, aware."""
    return valor.replace(tzinfo=timezone.utc).astimezone(BUSINESS_TIMEZONE)


class _EnHoraLocal(FunctionElement):
    """Traslada una columna naive-UTC a la hora local del negocio (naive)."""

    inherit_cache = True
    type = DateTime()


@compiles(_EnHoraLocal, "sqlite")
def _en_hora_local_sqlite(element, compiler, **kw):  # noqa: ANN001, ANN202
    # Colombia no tiene horario de verano: el offset es constante.
    offset = datetime(2000, 1, 1, tzinfo=BUSINESS_TIMEZONE).utcoffset()
    assert offset is not None
    minutos = int(offset.total_seconds() // 60)
    columna = compiler.process(list(element.clauses)[0], **kw)
    return f"datetime({columna}, '{minutos:+d} minutes')"


@compiles(_EnHoraLocal, "postgresql")
def _en_hora_local_pg(element, compiler, **kw):  # noqa: ANN001, ANN202
    columna = compiler.process(list(element.clauses)[0], **kw)
    return f"timezone('{BUSINESS_TIMEZONE_NAME}', timezone('UTC', {columna}))"


class _DiaLocal(FunctionElement):
    """Fecha local ('YYYY-MM-DD', texto) de una columna naive-UTC."""

    inherit_cache = True
    type = String()


@compiles(_DiaLocal, "sqlite")
def _dia_local_sqlite(element, compiler, **kw):  # noqa: ANN001, ANN202
    return f"date({compiler.process(_EnHoraLocal(*element.clauses), **kw)})"


@compiles(_DiaLocal, "postgresql")
def _dia_local_pg(element, compiler, **kw):  # noqa: ANN001, ANN202
    local = compiler.process(_EnHoraLocal(*element.clauses), **kw)
    return f"to_char({local}, 'YYYY-MM-DD')"


def columna_creado_en_local(columna: ColumnElement) -> ColumnElement:
    """Expresión SQL con la hora local de una columna naive-UTC."""
    return _EnHoraLocal(columna)


def dia_local(columna: ColumnElement) -> ColumnElement:
    """Expresión SQL con la fecha local ('YYYY-MM-DD') de una columna naive-UTC."""
    return _DiaLocal(columna)


def anio_local(columna: ColumnElement) -> ColumnElement:
    return extract("year", _EnHoraLocal(columna))


def mes_local(columna: ColumnElement) -> ColumnElement:
    return extract("month", _EnHoraLocal(columna))
