"""Helpers de conversión hora local (BUSINESS_TIMEZONE) <-> UTC naive (BE-024).

`Venta.creado_en` se guarda como naive-UTC (SQLite/SQLAlchemy descartan el
`tzinfo` al persistir). Estos helpers centralizan la conversión entre "hora
local del negocio" (la que percibe el usuario en Colombia) y los valores
naive-UTC que hay que usar para filtrar/agrupar contra esa columna, para no
repetir el mismo truco (`.astimezone(timezone.utc).replace(tzinfo=None)`) en
cada router.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from sqlalchemy import ColumnElement, func

from app.core.config import BUSINESS_TIMEZONE


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
    """Convierte un `creado_en` naive-UTC (leído de la BD) a hora local, aware."""
    return valor.replace(tzinfo=timezone.utc).astimezone(BUSINESS_TIMEZONE)


def _offset_sqlite_modifier() -> str:
    """Modifier de `datetime()` de SQLite equivalente al offset de BUSINESS_TIMEZONE.

    Colombia no tiene horario de verano: el offset es constante para
    cualquier fecha, así que basta con calcularlo una vez a partir de
    `BUSINESS_TIMEZONE` (evita hardcodear "-5 hours" como número mágico
    desconectado de la config).
    """
    offset = datetime(2000, 1, 1, tzinfo=BUSINESS_TIMEZONE).utcoffset()
    assert offset is not None
    minutos = int(offset.total_seconds() // 60)
    return f"{minutos:+d} minutes"


def columna_creado_en_local(columna: ColumnElement) -> ColumnElement:
    """Expresión SQL que traslada una columna naive-UTC a su hora local.

    Útil para agrupar (`strftime`) por mes/año/hora **local** en vez de UTC,
    sin tener que traer todas las filas a Python para reagruparlas.
    """
    return func.datetime(columna, _offset_sqlite_modifier())
