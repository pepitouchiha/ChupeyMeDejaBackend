from __future__ import annotations

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.sede import SedeScoped

COLOR_DEFAULT = "#6b7280"


class Categoria(SedeScoped, Base):
    __tablename__ = "categorias"
    __table_args__ = (UniqueConstraint("sede_id", "nombre", name="uq_categorias_sede_nombre"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    color: Mapped[str] = mapped_column(String(7), nullable=False, default=COLOR_DEFAULT)
