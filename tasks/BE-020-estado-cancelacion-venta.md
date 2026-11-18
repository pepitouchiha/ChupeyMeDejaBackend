---
id: BE-020
title: Estado de Venta (activa/cancelada), endpoint de cancelación y liberación de mesa
area: backend
status: done
priority: high
depends_on: [BE-006]
created_by: planner
---

## Objetivo

Hoy una `Venta` no tiene ningún concepto de estado: una vez creada vía
`POST /ventas` es inmutable y permanente. El dueño del negocio pidió poder
"cancelar" una orden ya registrada. La decisión de producto (confirmada, no
a discutir en esta tarea) es **soft-delete**: la venta se conserva en SQLite
marcada como `cancelada`, nunca se borra. Esta tarea agrega el campo de
estado al modelo, el endpoint para cancelar, y ajusta `GET /ventas` para
poder filtrar por estado. La exclusión de ventas canceladas en reportes/
margen es responsabilidad de BE-023 (depende de esta); el reflejo en Google
Sheets es responsabilidad de BE-022 (depende de esta) — ninguna de las dos
cosas se hace aquí.

## Alcance

**Incluye:**

- `backend/app/models/venta.py`:
  - Constantes `ESTADO_ACTIVA = "activa"` y `ESTADO_CANCELADA = "cancelada"`
    (mismo patrón que `ESTADO_LIBRE`/`ESTADO_OCUPADA` en `mesa.py` y
    `METODO_EFECTIVO`/`METODO_TRANSFERENCIA` en este mismo archivo).
  - Columna nueva en `Venta`: `estado: Mapped[str] = mapped_column(String(10),
    nullable=False, default=ESTADO_ACTIVA)`, con un `CheckConstraint` nuevo
    (`estado IN ('activa', 'cancelada')`), agregado a `__table_args__` junto
    al `CheckConstraint` existente de `metodo_pago`.
- `backend/app/schemas/venta.py`:
  - `EstadoVenta` enum (`activa` / `cancelada`), mismo patrón que
    `MetodoPago`.
  - `VentaOut.estado: EstadoVenta` (campo nuevo en la salida).
- `backend/app/routers/ventas.py`:
  - `crear_venta` no cambia su firma ni su contrato de entrada — toda venta
    nueva se crea con `estado=ESTADO_ACTIVA` (el default del modelo ya lo
    garantiza, no hace falta pasarlo explícitamente si el constructor de
    SQLAlchemy respeta el `default`; verificar que efectivamente se persiste
    así y no como `NULL`).
  - `GET /ventas`: agregar parámetro opcional `estado: EstadoVenta | None =
    None` que, si viene, filtra `Venta.estado == estado.value`. Sin este
    parámetro, el comportamiento no cambia (se siguen listando ventas
    activas y canceladas mezcladas — el filtrado por defecto NO excluye
    canceladas aquí; eso es una decisión consciente para que la futura
    pantalla de "Órdenes" del frontend pueda mostrar el historial completo,
    incluidas las canceladas, y sea el frontend quien decida si filtra).
  - Endpoint nuevo `POST /ventas/{venta_id}/cancelar`:
    - 404 si `venta_id` no existe.
    - 409 si la venta ya tiene `estado == ESTADO_CANCELADA` (mensaje claro,
      ej. "La venta ya está cancelada"), sin ningún efecto secundario (no
      debe tocar la mesa ni nada más).
    - Si la venta está activa: `venta.estado = ESTADO_CANCELADA`.
    - Si `venta.mesa_id is not None`: buscar esa `Mesa` y, si existe (podría
      no existir si fue borrada, aunque hoy `DELETE /mesas/{id}` bloquea el
      borrado si tiene ventas asociadas — de cualquier forma no debe fallar
      si la mesa ya no existe, solo se omite la liberación), marcar
      `mesa.estado = ESTADO_LIBRE` incondicionalmente (no se valida si hay
      "otra" venta activa en la misma mesa — para una sola venta cancelada
      basta con liberar directamente; ese matiz de "no liberar si otra venta
      activa sigue usando la mesa" solo aplica al endpoint de edición de
      BE-021, que si cambia de mesa sí necesita ese cuidado).
    - `db.commit()`, `db.refresh(venta)`, devuelve `VentaOut` (con
      `estado: "cancelada"`).
    - No dispara ninguna sincronización a Google Sheets en esta tarea (ver
      BE-022).

**No incluye (fuera de alcance):**

- Editar los items/mesa/método de pago de una venta existente — eso es
  BE-021.
- Excluir ventas canceladas de `/reportes/hoy`, `/reportes/mensual` o del
  cálculo de margen — eso es BE-023.
- Reflejar el nuevo campo `estado` o la cancelación en
  `sheets_service.py`/Google Sheets — eso es BE-022.
- Cambiar `_contar_ventas` en `backend/app/routers/mesas.py` (el conteo que
  bloquea `DELETE /mesas/{id}` si tiene ventas asociadas) para excluir
  canceladas — no fue pedido explícitamente; si el dueño reporta que no
  puede borrar una mesa cuya única venta asociada está cancelada, es una
  tarea futura de un ticket aparte, no se improvisa aquí.
- Mismo caveat operativo que BE-009/BE-010/BE-017 (sin Alembic,
  `Base.metadata.create_all` no altera una tabla `ventas` ya existente):
  documentar en notas de implementación el paso de borrar `brainfreeze.db`
  en desarrollo para que la columna `estado` tome efecto.

## Criterios de aceptación

- [ ] `Venta` tiene una columna `estado` (`String`, `nullable=False`,
      `CheckConstraint IN ('activa', 'cancelada')`, default `'activa'`).
- [ ] `POST /ventas` (sin cambios en su payload) crea la venta con
      `estado: "activa"`, verificable en la respuesta y en un `GET /ventas`
      posterior.
- [ ] `GET /ventas` y `GET /ventas` con `mesa_id`/`desde`/`hasta` incluyen
      `estado` en cada elemento devuelto.
- [ ] `GET /ventas?estado=activa` y `GET /ventas?estado=cancelada` filtran
      correctamente; sin el parámetro, se listan ventas de ambos estados
      mezcladas (sin regresión respecto al comportamiento actual).
- [ ] `POST /ventas/{id}/cancelar` sobre una venta activa con `mesa_id`
      asociado responde `200` con `estado: "cancelada"`, y `GET /mesas`
      inmediatamente después muestra esa mesa con `estado: "libre"`.
- [ ] `POST /ventas/{id}/cancelar` sobre una venta activa sin `mesa_id`
      responde `200` con `estado: "cancelada"`, sin ningún efecto sobre
      mesas.
- [ ] `POST /ventas/{id}/cancelar` sobre una venta ya cancelada responde
      `409`, y la venta/mesa quedan exactamente igual que antes del intento
      (sin doble efecto, sin re-liberar una mesa que ya fue reasignada a
      otra venta activa mientras tanto).
- [ ] `POST /ventas/{id}/cancelar` con un `venta_id` inexistente responde
      `404`.
- [ ] Documentado en las notas de implementación el paso manual de borrar
      `brainfreeze.db` en desarrollo para que la columna nueva tome efecto
      (mismo criterio que BE-017).
- [ ] Endpoints existentes (`GET /ventas`, `POST /ventas`) sin header
      `Authorization` siguen devolviendo `401` (sin regresión).

## Notas de implementación

Implementado tal como está descrito en la tarea, sin desviaciones.

**Archivos tocados:**

- `backend/app/models/venta.py`: agregadas constantes `ESTADO_ACTIVA =
  "activa"` / `ESTADO_CANCELADA = "cancelada"` (mismo patrón que
  `ESTADO_LIBRE`/`ESTADO_OCUPADA` de `mesa.py`), columna nueva
  `estado: Mapped[str] = mapped_column(String(10), nullable=False,
  default=ESTADO_ACTIVA)`, y `CheckConstraint("estado IN ('activa',
  'cancelada')", name="ck_ventas_estado")` agregado a `__table_args__` junto
  al `CheckConstraint` existente de `metodo_pago`.
- `backend/app/schemas/venta.py`: `EstadoVenta` enum (`activa`/`cancelada`,
  mismo patrón que `MetodoPago`) y `VentaOut.estado: EstadoVenta` como campo
  de salida nuevo.
- `backend/app/routers/ventas.py`:
  - `listar_ventas`: parámetro opcional nuevo `estado: EstadoVenta | None =
    None` que filtra `Venta.estado == estado.value` cuando viene; sin él, el
    comportamiento no cambia (activas y canceladas mezcladas).
  - `crear_venta`: no se tocó su firma ni su contrato de entrada; el
    `default=ESTADO_ACTIVA` de la columna del modelo se persiste
    automáticamente (verificado con un `POST /ventas` real: la respuesta y
    un `GET /ventas` posterior muestran `estado: "activa"`, nunca `NULL`).
  - Endpoint nuevo `POST /ventas/{venta_id}/cancelar`: 404 si no existe la
    venta, 409 (`"La venta ya está cancelada"`) sin ningún efecto secundario
    si ya estaba cancelada, si no marca `venta.estado = ESTADO_CANCELADA` y,
    si `venta.mesa_id is not None`, busca la `Mesa` con `db.get` (tolera que
    ya no exista, en cuyo caso simplemente omite la liberación) y la marca
    `ESTADO_LIBRE` incondicionalmente (sin verificar otras ventas activas en
    la misma mesa, tal como especifica el alcance de esta tarea — ese
    cuidado extra es exclusivo de la reasignación de mesa en BE-021). No
    dispara ninguna sincronización a Google Sheets (eso es BE-022).

**Actualización posterior — migración automática ligera (pedida
explícitamente por el usuario tras revisar el estado inicial de esta
tarea):** el caveat original de "borrar `brainfreeze.db` manualmente" era
aceptable en desarrollo, pero la base de datos **real** del cliente
(`backend/brainfreeze.db` en su PC, instalada el 2026-09-04, con ventas
históricas) no se puede borrar sin perder datos, y `Base.metadata.create_all`
nunca altera una tabla `ventas` ya existente para agregarle la columna
`estado` — desplegar esta tarea tal cual habría roto esa base real con
`sqlite3.OperationalError: no such column: estado` en el primer
`GET`/`POST /ventas`. Para resolverlo sin Alembic (fuera de alcance del
proyecto) se agregó un módulo nuevo, acotado a este caso puntual (no un
motor de migraciones genérico):

- `backend/app/db/migrations.py` (nuevo): `run_lightweight_migrations(engine)`,
  que llama a `_agregar_columna_estado_ventas(engine)`. Esta función usa
  `sqlalchemy.inspect(engine)` para listar las columnas actuales de la
  tabla `ventas`; si la tabla no existe todavía (instalación nueva, la va a
  crear `create_all` con el esquema completo) o si la columna `estado` ya
  está presente (instalación ya migrada, o creada de cero después de esta
  tarea), no hace nada. Si la tabla existe **sin** la columna, ejecuta
  `ALTER TABLE ventas ADD COLUMN estado VARCHAR(10) NOT NULL DEFAULT
  'activa'` dentro de `engine.begin()` (commit automático), con un
  `logger.warning` antes y después para que quede visible en los logs de
  producción que se aplicó una migración automática.
- `backend/app/main.py`: en el `lifespan`, se agregó la llamada
  `run_lightweight_migrations(engine)` **después** de
  `Base.metadata.create_all(bind=engine)` (orden importante: `create_all`
  primero cubre instalaciones nuevas —tabla creada ya con `estado`—, y solo
  entonces esta función necesita revisar instalaciones preexistentes donde
  la tabla ya existía sin la columna).
- **Limitación aceptada conscientemente y documentada en el docstring del
  módulo:** `ALTER TABLE ADD COLUMN` en SQLite no agrega el
  `CheckConstraint` (`ck_ventas_estado`) que sí aplica `create_all` en una
  tabla creada desde cero. Una base migrada por esta vía queda sin esa
  validación a nivel de motor SQLite; la validación efectiva sigue
  ocurriendo en la capa de aplicación (el enum `EstadoVenta` de Pydantic y
  las constantes `ESTADO_ACTIVA`/`ESTADO_CANCELADA`, únicas vías por las
  que el backend escribe esa columna). Agregar el `CHECK` a una tabla
  existente requeriría el patrón "copiar a tabla nueva, migrar filas,
  renombrar", que se consideró desproporcionado para este ajuste ligero;
  si se necesita en el futuro, es una tarea aparte.

**Verificado explícitamente (no solo por lectura de código), simulando la
base de datos real del cliente:**

1. Se creó una SQLite nueva con el **esquema viejo** de `ventas`
   (`id`, `mesa_id`, `metodo_pago`, `total`, `creado_en` — sin `estado`, sin
   `ck_ventas_estado`, tal como quedaría la tabla real antes de esta tarea)
   vía `sqlite3` directo, y se insertó una venta histórica de prueba
   (`id=1`, `total=12345`, `creado_en='2026-09-04 15:30:00'`) con su item.
   Confirmado con `PRAGMA table_info(ventas)` que la columna `estado` **no**
   existía antes de arrancar el servidor.
2. Se levantó `uvicorn app.main:app` apuntando `DATABASE_URL` a esa base:
   el log de arranque mostró exactamente `La tabla 'ventas' no tiene la
   columna 'estado' (...) Agregándola automáticamente vía ALTER TABLE con
   default 'activa'...` seguido de `Columna 'estado' agregada
   correctamente...`, y el servidor arrancó sin error
   (`GET /health` -> `200`).
3. Tras el arranque, `PRAGMA table_info(ventas)` confirmó la columna
   `estado` presente, y `SELECT * FROM ventas` confirmó que la fila
   histórica **no perdió ningún dato** (mismos `id`/`mesa_id`/`metodo_pago`/
   `total`/`creado_en`) y quedó con `estado='activa'` (el default aplicado
   por el `ALTER TABLE`, consistente con "toda venta preexistente antes de
   esta tarea se asume activa").
4. Vía API (usuario de prueba creado con `crear_usuario.py`): `GET /ventas`
   y `GET /ventas/1` devolvieron la venta histórica migrada, completa y
   legible, con `"estado": "activa"`; `POST /ventas/1/cancelar` funcionó
   normalmente sobre ese dato migrado (`200`, `"estado": "cancelada"`),
   confirmando que la fila migrada es indistinguible, para el resto del
   backend, de una venta creada después de esta tarea.
5. **Idempotencia:** se reinició el servidor una segunda vez apuntando a
   esa misma base (ya migrada) — el log de arranque **no** mostró ningún
   mensaje de migración (la función detectó que `estado` ya existía y no
   hizo nada), y el servidor arrancó normal, confirmando que
   `run_lightweight_migrations` es segura de correr en cada arranque sin
   efectos repetidos ni errores por "columna duplicada".

Base de datos de prueba (con esquema viejo simulado) y procesos detenidos y
eliminados del scratchpad de la sesión al terminar; no se tocó en ningún
momento la `brainfreeze.db` real del repositorio (confirmado con `git
status`, que no la muestra modificada).

**Cómo se probó:** no hay suite de tests automatizada ni `httpx` instalado
(mismo estado que documentó BE-017), así que se probó end-to-end levantando
el servidor real (`uvicorn app.main:app --port 8123`) contra una SQLite
temporal nueva (fuera del repo, en el scratchpad), con
`SHEETS_SYNC_ENABLED=false` y un usuario creado vía
`python -m app.scripts.crear_usuario`. Flujo verificado con `curl`:

1. Login -> token. `POST /categorias`, `POST /productos`, `POST /mesas` para
   tener datos base.
2. `POST /ventas` con `mesa_id` -> `201`, `estado: "activa"` en la
   respuesta; `GET /mesas` muestra la mesa `ocupada`.
3. `GET /ventas` y `GET /ventas?estado=activa` devuelven la venta; `GET
   /ventas?estado=cancelada` devuelve `[]`.
4. `POST /ventas/1/cancelar` -> `200`, `estado: "cancelada"`; `GET /mesas`
   inmediatamente después muestra la mesa `libre`.
5. `POST /ventas/1/cancelar` de nuevo -> `409` `{"detail":"La venta ya está
   cancelada"}`, sin cambios adicionales.
6. `POST /ventas/999/cancelar` (inexistente) -> `404`.
7. `POST /ventas` sin `mesa_id`, luego cancelar esa venta -> `200`,
   `estado: "cancelada"`, sin ningún efecto en `GET /mesas`.
8. `POST /ventas` y `GET /ventas` sin header `Authorization` -> `401` en
   ambos (sin regresión).

Servidor y base de datos temporal detenidos/eliminados al terminar la
verificación (no queda ningún proceso ni artefacto fuera del scratchpad de
la sesión).

## Revisión

**Veredicto: `done`.**

Revisé `backend/app/models/venta.py`, `backend/app/schemas/venta.py`,
`backend/app/routers/ventas.py`, `backend/app/db/migrations.py` y
`backend/app/main.py` completos, y reproduje por mi cuenta (no solo leí) el
punto más crítico de esta tarea: la migración ligera contra una base con
esquema viejo.

- **Migración verificada de forma independiente:** creé con `sqlite3` puro
  una base con el esquema `ventas` viejo (sin columna `estado`) y una venta
  histórica (`id=1`, `total=12345`). Levanté `uvicorn` apuntando
  `DATABASE_URL` a esa base: el log mostró el `logger.warning` esperado y
  `ALTER TABLE ventas ADD COLUMN estado VARCHAR(10) NOT NULL DEFAULT
  'activa'` se ejecutó correctamente. Confirmé con `PRAGMA
  table_info(ventas)` y `SELECT * FROM ventas` que la fila histórica no
  perdió ningún dato y quedó con `estado='activa'`. Vía API,
  `GET /ventas`, `GET /ventas/1` y `POST /ventas/1/cancelar` funcionaron
  normalmente sobre ese dato migrado.
- **Idempotencia verificada:** reinicié el servidor una segunda vez sobre
  esa misma base ya migrada — sin ningún log de migración ni error de
  "columna duplicada", arranque normal.
- `estado IN ('activa','cancelada')` como `CheckConstraint` en el modelo,
  con el default `ESTADO_ACTIVA` a nivel de ORM (confirmado que
  `POST /ventas` persiste `estado: "activa"`, nunca `NULL`).
- `GET /ventas?estado=activa` / `?estado=cancelada` filtran correctamente;
  sin el parámetro, mezcla ambos estados (sin regresión) — verificado con
  curl en una base nueva.
- `POST /ventas/{id}/cancelar`: `200` + libera la mesa (verificado con
  `GET /mesas` antes/después) cuando hay `mesa_id`; `200` sin tocar mesas
  cuando no hay `mesa_id`; `409` (`"La venta ya está cancelada"`) sin
  efecto secundario en un segundo intento; `404` con id inexistente — los
  4 casos reproducidos con curl.
- `401` sin header `Authorization` en `GET`/`POST /ventas`, verificado sin
  regresión.
- Limitación documentada (el `ALTER TABLE ADD COLUMN` no agrega el
  `CheckConstraint` en bases migradas) está señalada honestamente en el
  docstring del módulo, con la mitigación real (validación en capa de
  aplicación vía el enum Pydantic) — aceptable dado el alcance ligero
  pedido (sin Alembic).

No se tocó la `brainfreeze.db` real del repo durante la verificación
(confirmado con `git status` en `backend/`, sin cambios fuera de los
archivos de código/tareas esperados). No se encontraron hallazgos
bloqueantes.
