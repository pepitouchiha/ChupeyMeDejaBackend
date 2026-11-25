from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.sede import SedeScoped

TIPOS_PAGO = ("mensual", "quincenal", "semanal", "diario", "por_turno")


class Trabajador(SedeScoped, Base):
    __tablename__ = "trabajadores"
    __table_args__ = (
        CheckConstraint(
            "tipo_pago IN (" + ", ".join(f"'{t}'" for t in TIPOS_PAGO) + ")",
            name="ck_trabajadores_tipo_pago",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    cargo: Mapped[str | None] = mapped_column(String(80), nullable=True)
    telefono: Mapped[str | None] = mapped_column(String(30), nullable=True)
    documento: Mapped[str | None] = mapped_column(String(30), nullable=True)
    tipo_pago: Mapped[str] = mapped_column(String(20), nullable=False)
    monto_pago: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    fecha_ingreso: Mapped[date | None] = mapped_column(Date, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
