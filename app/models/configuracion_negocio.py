from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.sede import SedeScoped

class ConfiguracionNegocio(SedeScoped, Base):
    __tablename__ = "configuracion_negocio"
    __table_args__ = (
        CheckConstraint("ancho_papel_mm IN (58, 80)", name="ck_configuracion_negocio_ancho"),
        UniqueConstraint("sede_id", name="uq_configuracion_negocio_sede"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre_negocio: Mapped[str] = mapped_column(
        String(100), nullable=False, default="Chupe y Me Deja"
    )
    nit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    direccion: Mapped[str | None] = mapped_column(String(200), nullable=True)
    telefono: Mapped[str | None] = mapped_column(String(30), nullable=True)
    mensaje_pie: Mapped[str | None] = mapped_column(
        String(200), nullable=True, default="¡Gracias por su compra!"
    )
    imprimir_comanda_auto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    imprimir_factura_auto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ancho_papel_mm: Mapped[int] = mapped_column(Integer, nullable=False, default=80)
