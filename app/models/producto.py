from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.sede import SedeScoped

ESTADO_DISPONIBLE = "disponible"
ESTADO_AGOTADO = "agotado"


class Producto(SedeScoped, Base):
    __tablename__ = "productos"
    __table_args__ = (
        CheckConstraint(
            f"estado IN ('{ESTADO_DISPONIBLE}', '{ESTADO_AGOTADO}')", name="ck_productos_estado"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    categoria_id: Mapped[int] = mapped_column(ForeignKey("categorias.id"), nullable=False)
    precio: Mapped[int] = mapped_column(Integer, nullable=False)
    costo: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    estado: Mapped[str] = mapped_column(String(10), nullable=False, default=ESTADO_DISPONIBLE)
    sabor: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tamano: Mapped[str | None] = mapped_column(String(50), nullable=True)
    imagen_base64: Mapped[str | None] = mapped_column(Text, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    insumos: Mapped[list["ProductoInsumo"]] = relationship(
        "ProductoInsumo",
        back_populates="producto",
        cascade="all, delete-orphan",
        order_by="ProductoInsumo.id",
    )


class ProductoInsumo(SedeScoped, Base):
    __tablename__ = "producto_insumos"
    __table_args__ = (
        UniqueConstraint("producto_id", "insumo_id", name="uq_producto_insumos_producto_insumo"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"), nullable=False, index=True)
    insumo_id: Mapped[int] = mapped_column(ForeignKey("insumos.id"), nullable=False, index=True)
    cantidad: Mapped[float] = mapped_column(Float, nullable=False)

    producto: Mapped["Producto"] = relationship("Producto", back_populates="insumos")
    insumo: Mapped["Insumo"] = relationship("Insumo", viewonly=True)

    @property
    def nombre(self) -> str:
        return self.insumo.nombre

    @property
    def unidad(self) -> str:
        return self.insumo.unidad
