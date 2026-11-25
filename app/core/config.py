from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent

load_dotenv(BASE_DIR / ".env")

# "development" (por defecto) o "production". En producción se exigen
# DATABASE_URL y un JWT_SECRET_KEY propio, y se ocultan /docs.
ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development").strip().lower()
ES_PRODUCCION = ENVIRONMENT == "production"

# Zona horaria del negocio: ambas sedes están en Colombia (UTC-5, sin horario
# de verano). Las fechas se guardan en UTC naive y se convierten con esto al
# calcular "hoy" y agrupar reportes.
BUSINESS_TIMEZONE_NAME = os.getenv("BUSINESS_TIMEZONE", "America/Bogota")
BUSINESS_TIMEZONE = ZoneInfo(BUSINESS_TIMEZONE_NAME)


def _resolver_database_url(url: str) -> str:
    """Normaliza la URL de la base de datos.

    - SQLite relativo (desarrollo local) se resuelve contra `backend/`.
    - `postgres://` / `postgresql://` (lo que entrega Supabase) se convierte a
      `postgresql+psycopg://` para usar el driver psycopg 3.
    """
    if url.startswith("sqlite:///") and url != "sqlite:///:memory:":
        ruta = Path(url[len("sqlite:///"):])
        if not ruta.is_absolute():
            ruta = (BASE_DIR / ruta).resolve()
        return f"sqlite:///{ruta.as_posix()}"
    for prefijo in ("postgres://", "postgresql://"):
        if url.startswith(prefijo):
            return "postgresql+psycopg://" + url[len(prefijo):]
    return url


_database_url_env = os.getenv("DATABASE_URL", "").strip()
if ES_PRODUCCION and not _database_url_env:
    raise RuntimeError("DATABASE_URL es obligatoria en producción (cadena de conexión de Supabase).")
DATABASE_URL: str = _resolver_database_url(
    _database_url_env or f"sqlite:///{(BASE_DIR / 'chupeymedeja.db').as_posix()}"
)

CORS_ORIGINS: list[str] = [
    origin.strip().rstrip("/")
    for origin in os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if origin.strip()
]

_SECRETO_DESARROLLO = "dev-secret-change-me"
JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", _SECRETO_DESARROLLO)
if ES_PRODUCCION and (JWT_SECRET_KEY == _SECRETO_DESARROLLO or len(JWT_SECRET_KEY) < 32):
    raise RuntimeError(
        "JWT_SECRET_KEY debe ser un secreto propio de al menos 32 caracteres en producción."
    )
JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "720"))

# Intentos de login fallidos permitidos por IP + email antes de bloquear un rato.
LOGIN_MAX_INTENTOS: int = int(os.getenv("LOGIN_MAX_INTENTOS", "5"))
LOGIN_BLOQUEO_MINUTOS: int = int(os.getenv("LOGIN_BLOQUEO_MINUTOS", "15"))
