from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent

load_dotenv(BASE_DIR / ".env")

# Zona horaria de negocio (BE-024): un solo local, en Colombia, sin horario de
# verano, por lo que el offset es fijo (UTC-5). Todo lo que necesite
# interpretar "hoy"/rangos de fecha en hora local del negocio (reportes,
# filtros de ventas) debe usar esta constante en vez de asumir la hora local
# del servidor. `Venta.creado_en` sigue guardándose en UTC naive; esta
# constante solo se usa para convertir en la capa de consulta/presentación.
BUSINESS_TIMEZONE = ZoneInfo("America/Bogota")

def _resolver_ruta(valor: str) -> Path:
    """Resuelve rutas relativas del `.env` contra `backend/`, no contra el
    directorio de trabajo: si el backend se lanza desde otra carpeta (acceso
    directo, tarea programada), `./brainfreeze.db` apuntaría a una base vacía."""
    ruta = Path(valor)
    return ruta if ruta.is_absolute() else (BASE_DIR / ruta).resolve()


def _resolver_database_url(url: str) -> str:
    prefijo = "sqlite:///"
    if not url.startswith(prefijo) or url == f"{prefijo}:memory:":
        return url
    return f"{prefijo}{_resolver_ruta(url[len(prefijo):]).as_posix()}"


DATABASE_URL: str = _resolver_database_url(
    os.getenv("DATABASE_URL", f"sqlite:///{(BASE_DIR / 'brainfreeze.db').as_posix()}")
)

CORS_ORIGINS: list[str] = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if origin.strip()
]

JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "dev-secret-change-me")
JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))

SHEETS_SYNC_ENABLED: bool = os.getenv("SHEETS_SYNC_ENABLED", "false").strip().lower() == "true"
SHEETS_SPREADSHEET_NAME: str = os.getenv("SHEETS_SPREADSHEET_NAME", "BrainFreeze POS")
SHEETS_WORKSHEET_NAME: str = os.getenv("SHEETS_WORKSHEET_NAME", "Ventas_Diarias")
SHEETS_WORKSHEET_CATEGORIAS: str = os.getenv("SHEETS_WORKSHEET_CATEGORIAS", "Categorias")
SHEETS_WORKSHEET_PRODUCTOS: str = os.getenv("SHEETS_WORKSHEET_PRODUCTOS", "Productos")
SHEETS_WORKSHEET_INSUMOS: str = os.getenv("SHEETS_WORKSHEET_INSUMOS", "Insumos")
SHEETS_CREDENTIALS_FILE: Path = _resolver_ruta(
    os.getenv("SHEETS_CREDENTIALS_FILE", str(BASE_DIR / "credentials.json"))
)
SHEETS_AUTHORIZED_USER_FILE: Path = _resolver_ruta(
    os.getenv("SHEETS_AUTHORIZED_USER_FILE", str(BASE_DIR / "authorized_user.json"))
)
