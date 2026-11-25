from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.sede import Sede

# Roles (de mayor a menor):
# - superadmin: quien instala y mantiene el sistema. Crea las sedes y las
#   cuentas de dueño y administrador. Se crea solo por línea de comandos
#   (app/scripts/crear_superadmin.py); no hay registro público.
# - dueno: ve y opera todas las sedes; puede crear cajeros en cualquier sede.
# - administrador: administra todo dentro de su sede y crea cajeros de su sede.
# - cajero: opera su sede (vender, mesas, caja, registrar gastos de caja).
ROL_SUPERADMIN = "superadmin"
ROL_DUENO = "dueno"
ROL_ADMINISTRADOR = "administrador"
ROL_CAJERO = "cajero"
ROLES = (ROL_SUPERADMIN, ROL_DUENO, ROL_ADMINISTRADOR, ROL_CAJERO)
# Roles que no pertenecen a una sede y eligen la sede activa.
ROLES_GLOBALES = (ROL_SUPERADMIN, ROL_DUENO)


class Usuario(Base):
    __tablename__ = "usuarios"
    __table_args__ = (
        CheckConstraint(
            "rol IN (" + ", ".join(f"'{r}'" for r in ROLES) + ")", name="ck_usuarios_rol"
        ),
        # Administradores y cajeros pertenecen a exactamente una sede.
        CheckConstraint(
            f"rol IN ('{ROL_SUPERADMIN}', '{ROL_DUENO}') OR sede_id IS NOT NULL",
            name="ck_usuarios_sede_requerida",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False, default="")
    rol: Mapped[str] = mapped_column(String(20), nullable=False, default=ROL_CAJERO)
    sede_id: Mapped[int | None] = mapped_column(ForeignKey("sedes.id"), nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Se incrementa al cambiar la contraseña o desactivar: invalida los tokens viejos.
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    sede: Mapped[Sede | None] = relationship(Sede, lazy="joined")

    @property
    def es_global(self) -> bool:
        """Super admin y dueño: no pertenecen a una sede, eligen cuál operar."""
        return self.rol in ROLES_GLOBALES

    @property
    def es_superadmin(self) -> bool:
        return self.rol == ROL_SUPERADMIN

    @property
    def sede_nombre(self) -> str | None:
        return self.sede.nombre if self.sede is not None else None
