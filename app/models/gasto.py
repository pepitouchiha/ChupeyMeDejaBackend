from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, and_
from sqlalchemy.orm import Mapped, foreign, mapped_column, relationship

from app.core.timezone import hoy_local
from app.db.base import Base
from app.models.sede import SedeScoped

# Claves de las categorías de sistema: el código las usa directamente
# (nómina desde pagos a trabajadores, compra de inventario desde entradas de
# insumos), por eso no se pueden eliminar ni desactivar desde la app.
CAT_COMPRA_INVENTARIO = "compra_inventario"
CAT_INSUMOS_PREPARACION = "insumos_preparacion"
CAT_NOMINA = "nomina"
CAT_ARRIENDO = "arriendo"
CAT_SERVICIOS = "servicios"
CAT_MANTENIMIENTO = "mantenimiento"
CAT_OTROS = "otros"

CATEGORIAS_SISTEMA = (CAT_COMPRA_INVENTARIO, CAT_NOMINA)

COLOR_CATEGORIA_DEFAULT = "#00e5ff"

# (clave, nombre, color) de las categorías que se crean la primera vez.
CATEGORIAS_INICIALES: tuple[tuple[str, str, str], ...] = (
    (CAT_COMPRA_INVENTARIO, "Compra de inventario", "#b2ff05"),
    (CAT_INSUMOS_PREPARACION, "Insumos de preparación", "#b2ff05"),
    (CAT_NOMINA, "Nómina", "#ff007f"),
    (CAT_ARRIENDO, "Arriendo", "#ff8a1e"),
    (CAT_SERVICIOS, "Servicios", "#ff8a1e"),
    (CAT_MANTENIMIENTO, "Mantenimiento", "#00e5ff"),
    (CAT_OTROS, "Otros", "#6b7280"),
)

ORIGEN_MANUAL = "manual"
ORIGEN_INVENTARIO = "inventario"
ORIGEN_NOMINA = "nomina"


class CategoriaGasto(SedeScoped, Base):
    """Categoría de gasto administrable desde la app.

    `clave` es el identificador estable que se guarda en `gastos.categoria`;
    se genera al crearla y no cambia aunque se renombre (`nombre`).
    """

    __tablename__ = "categorias_gasto"
    __table_args__ = (
        UniqueConstraint("sede_id", "clave", name="uq_categorias_gasto_sede_clave"),
        UniqueConstraint("sede_id", "nombre", name="uq_categorias_gasto_sede_nombre"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    clave: Mapped[str] = mapped_column(String(30), nullable=False)
    nombre: Mapped[str] = mapped_column(String(60), nullable=False)
    color: Mapped[str] = mapped_column(String(7), nullable=False, default=COLOR_CATEGORIA_DEFAULT)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    @property
    def sistema(self) -> bool:
        return self.clave in CATEGORIAS_SISTEMA


class Gasto(SedeScoped, Base):
    __tablename__ = "gastos"

    id: Mapped[int] = mapped_column(primary_key=True)
    fecha: Mapped[date] = mapped_column(Date, nullable=False, default=hoy_local, index=True)
    # Clave de `categorias_gasto`; se valida en la capa de aplicación.
    categoria: Mapped[str] = mapped_column(String(30), nullable=False)
    descripcion: Mapped[str] = mapped_column(String(255), nullable=False)
    monto: Mapped[int] = mapped_column(Integer, nullable=False)
    pagado_desde_caja: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    caja_sesion_id: Mapped[int | None] = mapped_column(
        ForeignKey("caja_sesiones.id"), nullable=True
    )
    movimiento_inventario_id: Mapped[int | None] = mapped_column(
        ForeignKey("inventario_movimientos.id"), nullable=True
    )
    trabajador_id: Mapped[int | None] = mapped_column(
        ForeignKey("trabajadores.id"), nullable=True
    )
    creado_en: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    categoria_rel: Mapped[CategoriaGasto | None] = relationship(
        CategoriaGasto,
        primaryjoin=lambda: and_(
            foreign(Gasto.categoria) == CategoriaGasto.clave,
            foreign(Gasto.sede_id) == CategoriaGasto.sede_id,
        ),
        viewonly=True,
        lazy="selectin",
    )

    @property
    def categoria_nombre(self) -> str:
        return self.categoria_rel.nombre if self.categoria_rel else self.categoria

    @property
    def categoria_color(self) -> str:
        return self.categoria_rel.color if self.categoria_rel else COLOR_CATEGORIA_DEFAULT

    @property
    def origen(self) -> str:
        if self.movimiento_inventario_id is not None:
            return ORIGEN_INVENTARIO
        if self.trabajador_id is not None or self.categoria == CAT_NOMINA:
            return ORIGEN_NOMINA
        return ORIGEN_MANUAL
