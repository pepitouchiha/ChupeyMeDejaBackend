"""Ajustes de esquema ligeros para bases de datos SQLite preexistentes.

Sin Alembic, `Base.metadata.create_all` (ver `app/main.py`) solo crea tablas
que todavía no existen — nunca altera una tabla ya existente para agregarle
una columna nueva. Varias tareas anteriores (BE-009/010/011/017) documentaron
esto como un paso manual ("borrar `brainfreeze.db` en desarrollo"), aceptable
mientras no hubiera una base de datos real en producción. Con BE-020, sí
existe una base real del cliente instalada (2026-09-04, con ventas
históricas) que no se puede borrar sin perder datos: este módulo agrega,
al arrancar el backend, un chequeo explícito y acotado por columna (no un
motor de migraciones genérico) que detecta si falta una columna nueva
conocida y la agrega vía `ALTER TABLE ... ADD COLUMN` antes de que el resto
de la aplicación intente usarla.

Limitación aceptada conscientemente: `ALTER TABLE ADD COLUMN` en SQLite no
agrega el `CheckConstraint` que sí aplica `Base.metadata.create_all` en una
tabla creada desde cero (`ck_ventas_estado`, `estado IN ('activa',
'cancelada')`). Una base de datos migrada por esta vía queda sin esa
validación a nivel de motor; la validación efectiva sigue ocurriendo en la
capa de aplicación (el enum `EstadoVenta` de Pydantic y las constantes
`ESTADO_ACTIVA`/`ESTADO_CANCELADA` usadas explícitamente por el código, que
son las únicas vías por las que el backend escribe esa columna). Agregar el
`CHECK` requeriría recrear la tabla completa (patrón "copiar a tabla nueva,
migrar filas, renombrar"), fuera de alcance de este ajuste ligero.

**BE-025 (estado 'abierta' y `metodo_pago` nullable):** a diferencia del
`CheckConstraint` de `estado` (limitación aceptada arriba, porque nunca
bloquea un `INSERT`/`UPDATE` válido ya que la app nunca escribe un valor
fuera del enum), `metodo_pago` pasó de `NOT NULL` a nullable, y esto **sí**
bloquea funcionalidad real: en cualquier base SQLite donde la columna
`metodo_pago` siga siendo `NOT NULL` a nivel de motor, `POST /ventas/abrir`
fallaría con `sqlite3.IntegrityError` al intentar insertar
`metodo_pago=NULL`. SQLite no soporta `ALTER TABLE ... ALTER COLUMN` para
relajar un `NOT NULL` (ni para reescribir un `CheckConstraint` ya grabado en
el `CREATE TABLE` original). Por eso, a diferencia del resto de este módulo
(que solo agrega columnas), esta migración puntual sí aplica el patrón
completo "copiar a tabla nueva con el esquema correcto, migrar filas,
renombrar" — ver `_permitir_metodo_pago_nulo_ventas`. Se decidió no hacerlo
"a medias" (dejar el `NOT NULL` real y solo confiar en la capa de
aplicación, como sí se aceptó para el `CheckConstraint` de `estado`) porque
en este caso la restricción de motor rompe un flujo nuevo pedido
explícitamente (abrir pedidos), no es solo una validación redundante.
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.models.venta import (
    ESTADO_ABIERTA,
    ESTADO_ACTIVA,
    ESTADO_CANCELADA,
    METODO_EFECTIVO,
    METODO_TRANSFERENCIA,
)

logger = logging.getLogger(__name__)


def _agregar_columna_estado_ventas(engine: Engine) -> None:
    inspector = inspect(engine)
    if "ventas" not in inspector.get_table_names():
        return  # tabla nueva: create_all ya la crea con el esquema completo

    columnas = {columna["name"] for columna in inspector.get_columns("ventas")}
    if "estado" in columnas:
        return

    logger.warning(
        "La tabla 'ventas' no tiene la columna 'estado' (base de datos "
        "preexistente de antes de BE-020). Agregándola automáticamente vía "
        "ALTER TABLE con default '%s'...",
        ESTADO_ACTIVA,
    )
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE ventas ADD COLUMN estado VARCHAR(10) "
                f"NOT NULL DEFAULT '{ESTADO_ACTIVA}'"
            )
        )
    logger.warning("Columna 'estado' agregada correctamente a la tabla 'ventas'.")


def _permitir_metodo_pago_nulo_ventas(engine: Engine) -> None:
    inspector = inspect(engine)
    if "ventas" not in inspector.get_table_names():
        return  # tabla nueva: create_all ya la crea con el esquema completo

    columnas = {columna["name"]: columna for columna in inspector.get_columns("ventas")}
    metodo_pago_col = columnas.get("metodo_pago")
    if metodo_pago_col is None or metodo_pago_col["nullable"]:
        return  # ya migrada, o creada de cero ya con el esquema correcto

    logger.warning(
        "La columna 'metodo_pago' de 'ventas' es NOT NULL (esquema previo a "
        "BE-025). SQLite no soporta relajar un NOT NULL con ALTER TABLE; "
        "reconstruyendo la tabla completa (copiar filas a una tabla nueva "
        "con el esquema correcto y renombrarla) para permitir NULL..."
    )
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE ventas RENAME TO _ventas_old_be025"))
        conn.execute(
            text(
                "CREATE TABLE ventas ("
                "id INTEGER NOT NULL PRIMARY KEY, "
                "mesa_id INTEGER, "
                "metodo_pago VARCHAR(20), "
                f"estado VARCHAR(10) NOT NULL DEFAULT '{ESTADO_ACTIVA}', "
                "total INTEGER NOT NULL, "
                "creado_en DATETIME NOT NULL, "
                "FOREIGN KEY(mesa_id) REFERENCES mesas (id), "
                "CONSTRAINT ck_ventas_metodo_pago CHECK ("
                f"metodo_pago IS NULL OR metodo_pago IN "
                f"('{METODO_EFECTIVO}', '{METODO_TRANSFERENCIA}')"
                "), "
                "CONSTRAINT ck_ventas_estado CHECK ("
                f"estado IN ('{ESTADO_ACTIVA}', '{ESTADO_CANCELADA}', '{ESTADO_ABIERTA}')"
                ")"
                ")"
            )
        )
        conn.execute(
            text(
                "INSERT INTO ventas (id, mesa_id, metodo_pago, estado, total, creado_en) "
                "SELECT id, mesa_id, metodo_pago, estado, total, creado_en "
                "FROM _ventas_old_be025"
            )
        )
        conn.execute(text("DROP TABLE _ventas_old_be025"))
    logger.warning(
        "Tabla 'ventas' reconstruida correctamente: 'metodo_pago' ahora es "
        "nullable y el CheckConstraint de 'estado' admite 'abierta'."
    )


def run_lightweight_migrations(engine: Engine) -> None:
    """Corre, en orden, todos los ajustes de esquema ligeros conocidos.

    Debe llamarse después de `Base.metadata.create_all` en el `lifespan` de
    `app/main.py`: `create_all` cubre instalaciones nuevas (tabla creada ya
    con la columna), esta función cubre instalaciones preexistentes (tabla
    ya creada, sin la columna nueva). Orden importante:
    `_agregar_columna_estado_ventas` primero (garantiza que la columna
    `estado` exista antes de que `_permitir_metodo_pago_nulo_ventas` la
    copie al reconstruir la tabla).
    """
    _agregar_columna_estado_ventas(engine)
    _permitir_metodo_pago_nulo_ventas(engine)
