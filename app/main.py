from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import CORS_ORIGINS, ES_PRODUCCION
from app.db.base_all import Base
from app.db.session import SessionLocal, engine
from app.db.tenancy import SedeNoDefinidaError
from app.routers import (
    auth,
    caja,
    categorias,
    configuracion,
    gastos,
    health,
    insumos,
    mesas,
    productos,
    reportes,
    trabajadores,
    usuarios,
    ventas,
)
from app.services.sedes import completar_datos_base

logger = logging.getLogger("chupeymedeja")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Crea las tablas que falten (no modifica tablas existentes).
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        completar_datos_base(db)
    yield


app = FastAPI(
    title="Chupe y Me Deja API",
    lifespan=lifespan,
    # En producción no se publica la documentación interactiva de la API.
    docs_url=None if ES_PRODUCCION else "/docs",
    redoc_url=None,
    openapi_url=None if ES_PRODUCCION else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Sede-Id"],
)


@app.middleware("http")
async def cabeceras_seguridad(request: Request, call_next):  # noqa: ANN001, ANN201
    respuesta = await call_next(request)
    respuesta.headers.setdefault("X-Content-Type-Options", "nosniff")
    respuesta.headers.setdefault("X-Frame-Options", "DENY")
    respuesta.headers.setdefault("Referrer-Policy", "no-referrer")
    if ES_PRODUCCION:
        respuesta.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return respuesta


@app.exception_handler(SedeNoDefinidaError)
async def sede_no_definida(request: Request, exc: SedeNoDefinidaError) -> JSONResponse:
    # Nunca debería pasar: indica una ruta de datos de sede sin `require_sede`.
    logger.error("Acceso a datos de sede sin sede activa en %s: %s", request.url.path, exc)
    return JSONResponse(status_code=400, content={"detail": "Selecciona una sede para continuar."})


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(usuarios.router)
app.include_router(categorias.router)
app.include_router(mesas.router)
app.include_router(productos.router)
app.include_router(insumos.router)
app.include_router(gastos.router)
app.include_router(caja.router)
app.include_router(trabajadores.router)
app.include_router(ventas.router)
app.include_router(reportes.router)
app.include_router(configuracion.router)
