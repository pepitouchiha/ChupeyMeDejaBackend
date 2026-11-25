from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    and_,
)
from sqlalchemy.orm import Mapped, foreign, mapped_column, relationship

from app.db.base import Base
from app.models.sede import SedeScoped

ESTADO_CRITICO = "Crítico"
ESTADO_BAJO = "Bajo"
ESTADO_OK = "OK"

# Tipos con los que arranca cada sede (clave, nombre). Después se administran
# desde la app (Inventario > Tipos): se pueden renombrar, desactivar, borrar
# o agregar otros.
TIPOS_INICIALES: tuple[tuple[str, str], ...] = (
    ("vaso", "Vaso"),
    ("bebida", "Bebida"),
    ("licor", "Licor"),
    ("implemento", "Implemento"),
    ("otro", "Otro"),
)

MOV_ENTRADA = "entrada"
MOV_AJUSTE = "ajuste"
MOV_VENTA = "venta"
MOV_REVERSO_VENTA = "reverso_venta"
TIPOS_MOVIMIENTO = (MOV_ENTRADA, MOV_AJUSTE, MOV_VENTA, MOV_REVERSO_VENTA)


def calcular_estado(stock: float, stock_minimo: float) -> str:
    """Deriva el estado del insumo comparando `stock` contra `stock_minimo`.

    Umbrales (replican `tagStyleFor` del mockup):
    - `stock <= 0` -> 'Crítico'
    - `0 < stock <= stock_minimo` -> 'Bajo'
    - `stock > stock_minimo` -> 'OK'
    """
    if stock <= 0:
        return ESTADO_CRITICO
    if stock <= stock_minimo:
        return ESTADO_BAJO
    return ESTADO_OK


def _en_lista(valores: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in valores)


class TipoInsumo(SedeScoped, Base):
    """Tipo de insumo administrable por sede (Vaso, Bebida, Licor...).

    `clave` es el identificador estable que se guarda en `insumos.tipo`; se
    genera al crearlo y no cambia aunque se renombre.
    """

    __tablename__ = "tipos_insumo"
    __table_args__ = (
        UniqueConstraint("sede_id", "clave", name="uq_tipos_insumo_sede_clave"),
        UniqueConstraint("sede_id", "nombre", name="uq_tipos_insumo_sede_nombre"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    clave: Mapped[str] = mapped_column(String(30), nullable=False)
    nombre: Mapped[str] = mapped_column(String(60), nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Insumo(SedeScoped, Base):
    __tablename__ = "insumos"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    # Clave de `tipos_insumo` de la misma sede; se valida en la capa de aplicación.
    tipo: Mapped[str] = mapped_column(String(30), nullable=False)
    unidad: Mapped[str] = mapped_column(String(20), nullable=False, default="unidad")
    stock: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    stock_minimo: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    costo_unitario: Mapped[int | None] = mapped_column(Integer, nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    tipo_rel: Mapped[TipoInsumo | None] = relationship(
        TipoInsumo,
        primaryjoin=lambda: and_(
            foreign(Insumo.tipo) == TipoInsumo.clave,
            foreign(Insumo.sede_id) == TipoInsumo.sede_id,
        ),
        viewonly=True,
        lazy="selectin",
    )

    @property
    def tipo_nombre(self) -> str:
        return self.tipo_rel.nombre if self.tipo_rel else self.tipo


class MovimientoInventario(SedeScoped, Base):
    __tablename__ = "inventario_movimientos"
    __table_args__ = (
        CheckConstraint(
            f"tipo IN ({_en_lista(TIPOS_MOVIMIENTO)})", name="ck_inventario_movimientos_tipo"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    insumo_id: Mapped[int] = mapped_column(ForeignKey("insumos.id"), nullable=False, index=True)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    cantidad: Mapped[float] = mapped_column(Float, nullable=False)
    stock_resultante: Mapped[float] = mapped_column(Float, nullable=False)
    costo_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    venta_id: Mapped[int | None] = mapped_column(ForeignKey("ventas.id"), nullable=True)
    nota: Mapped[str | None] = mapped_column(String(255), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
