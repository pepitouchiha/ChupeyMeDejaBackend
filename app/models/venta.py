from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

METODO_EFECTIVO = "efectivo"
METODO_TRANSFERENCIA = "transferencia"

ESTADO_ACTIVA = "activa"
ESTADO_CANCELADA = "cancelada"
ESTADO_ABIERTA = "abierta"


class Venta(Base):
    __tablename__ = "ventas"
    __table_args__ = (
        CheckConstraint(
            f"metodo_pago IS NULL OR metodo_pago IN "
            f"('{METODO_EFECTIVO}', '{METODO_TRANSFERENCIA}')",
            name="ck_ventas_metodo_pago",
        ),
        CheckConstraint(
            f"estado IN ('{ESTADO_ACTIVA}', '{ESTADO_CANCELADA}', '{ESTADO_ABIERTA}')",
            name="ck_ventas_estado",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    mesa_id: Mapped[int | None] = mapped_column(ForeignKey("mesas.id"), nullable=True)
    # Nullable desde BE-025: un pedido "abierta" todavía no tiene método de
    # pago, se asigna recién al cerrarlo (BE-027).
    metodo_pago: Mapped[str | None] = mapped_column(String(20), nullable=True)
    estado: Mapped[str] = mapped_column(String(10), nullable=False, default=ESTADO_ACTIVA)
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    items: Mapped[list["VentaItem"]] = relationship(
        "VentaItem", back_populates="venta", cascade="all, delete-orphan"
    )


class VentaItem(Base):
    __tablename__ = "venta_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    venta_id: Mapped[int] = mapped_column(ForeignKey("ventas.id"), nullable=False)
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"), nullable=False)
    cantidad: Mapped[int] = mapped_column(Integer, nullable=False)
    precio_unitario: Mapped[int] = mapped_column(Integer, nullable=False)

    venta: Mapped["Venta"] = relationship("Venta", back_populates="items")
