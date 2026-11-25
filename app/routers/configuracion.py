from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import require_sede, solo_admin
from app.db.session import get_db
from app.models.configuracion_negocio import ConfiguracionNegocio
from app.schemas.configuracion_negocio import (
    ConfiguracionNegocioOut,
    ConfiguracionNegocioUpdate,
)

router = APIRouter(
    prefix="/configuracion", tags=["configuracion"], dependencies=[Depends(require_sede)]
)


def _obtener_o_crear(db: Session) -> ConfiguracionNegocio:
    # Una fila por sede (el filtro por sede activa ya aplica a esta consulta).
    config = db.query(ConfiguracionNegocio).first()
    if config is None:
        config = ConfiguracionNegocio()
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


@router.get("/negocio", response_model=ConfiguracionNegocioOut)
def obtener_configuracion_negocio(db: Session = Depends(get_db)) -> ConfiguracionNegocio:
    return _obtener_o_crear(db)


@router.put("/negocio", dependencies=[solo_admin], response_model=ConfiguracionNegocioOut)
def actualizar_configuracion_negocio(
    payload: ConfiguracionNegocioUpdate, db: Session = Depends(get_db)
) -> ConfiguracionNegocio:
    config = _obtener_o_crear(db)
    for campo, valor in payload.model_dump().items():
        setattr(config, campo, valor)
    db.commit()
    db.refresh(config)
    return config
