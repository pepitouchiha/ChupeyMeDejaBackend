from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from app.db.base import Base


class Sede(Base):
    """Una sede del negocio (ej. Asunción, Machado). Es el tenant: cada sede
    tiene su propio menú, inventario, mesas, caja, ventas, gastos y personal."""

    __tablename__ = "sedes"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    direccion: Mapped[str | None] = mapped_column(String(200), nullable=True)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class SedeScoped:
    """Mixin para toda tabla cuyos datos pertenecen a una sede.

    No hace falta asignar `sede_id` a mano ni filtrar por él en las consultas:
    `app.db.tenancy` lo asigna al insertar y agrega `WHERE sede_id = <sede
    activa>` a todo SELECT/UPDATE/DELETE del ORM sobre estas clases.
    """

    @declared_attr
    def sede_id(cls) -> Mapped[int]:
        return mapped_column(ForeignKey("sedes.id"), nullable=False, index=True)
