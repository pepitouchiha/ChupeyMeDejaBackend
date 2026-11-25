from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.sede import SedeScoped


class CajaSesion(SedeScoped, Base):
    __tablename__ = "caja_sesiones"
    __table_args__ = (
        CheckConstraint("base_inicial >= 0", name="ck_caja_base_inicial"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    abierta_en: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True
    )
    cerrada_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    base_inicial: Mapped[int] = mapped_column(Integer, nullable=False)
    notas_apertura: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Foto de los totales, solo se llena al cerrar.
    ventas_efectivo: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ventas_transferencia: Mapped[int | None] = mapped_column(Integer, nullable=True)
    num_ventas: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gastos_desde_caja: Mapped[int | None] = mapped_column(Integer, nullable=True)
    efectivo_esperado: Mapped[int | None] = mapped_column(Integer, nullable=True)
    efectivo_contado: Mapped[int | None] = mapped_column(Integer, nullable=True)
    diferencia: Mapped[int | None] = mapped_column(Integer, nullable=True)
    base_siguiente: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retiro: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notas_cierre: Mapped[str | None] = mapped_column(String(255), nullable=True)
