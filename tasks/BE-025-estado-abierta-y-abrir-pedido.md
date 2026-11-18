---
id: BE-025
title: Nuevo estado "abierta" en Venta (pedido en curso) y endpoint para abrir un pedido en una mesa
area: backend
status: done
priority: high
depends_on: [BE-006, BE-020]
created_by: planner
---

## Objetivo

El dueño del negocio confirmó una feature nueva: hoy una `Venta` siempre se
crea completa de una sola vez (`POST /ventas`, se cobra en el acto). En la
operación real, cuando alguien se sienta en una mesa, los productos se van
pidiendo *progresivamente* a lo largo del tiempo (una bebida ahora, un
postre 20 minutos después) y todo se anota en el mismo pedido hasta que la
mesa se cierra y ahí sí se cobra todo junto. Hoy no hay forma de modelar un
pedido "a medio armar" — o se crea una venta completa, o se edita una ya
cobrada (BE-021, que es para corregir errores post-cobro, no para ir
armando un pedido en vivo).

**Decisión de modelo de datos (tomada por el planner, no a discutir en esta
tarea): se extiende el modelo `Venta` existente con un tercer estado
`abierta`, en vez de crear un modelo nuevo "Pedido"/"Comanda".** Razones:

1. Reportes (BE-007) y margen (BE-023) ya filtran explícitamente
   `Venta.estado == ESTADO_ACTIVA` (no `!= ESTADO_CANCELADA`) — un tercer
   estado queda excluido automáticamente de todos los cálculos agregados
   **sin tocar `reportes.py`** (se verifica, no se re-implementa, en
   BE-028).
2. El upsert-por-ID a Google Sheets (BE-022) y el disparo explícito de
   `sync_venta_to_sheets` por endpoint (nunca automático por cambio de
   columna) significan que una venta `abierta` simplemente nunca se
   sincroniza mientras no se cierre — no hace falta ninguna lógica nueva de
   exclusión en `sheets_service.py`.
3. `GET /ventas?estado=` (BE-020) ya soporta filtrar por cualquier valor del
   enum `EstadoVenta` — extenderlo con `abierta` da gratis la forma de que
   el frontend consulte "¿esta mesa ya tiene un pedido en curso?" vía
   `GET /ventas?mesa_id=X&estado=abierta`, sin necesidad de un endpoint de
   búsqueda nuevo.
4. Un modelo `Pedido` nuevo duplicaría `items`/`mesa_id`/relación con
   `Producto` y necesitaría su propia lógica de exclusión de reportes, su
   propia consideración en Sheets, y un paso de conversión/migración
   `Pedido -> Venta` al cerrarse — pura duplicación de lo que `estado` ya
   modela para `activa`/`cancelada`.

Esta tarea (BE-025) agrega el estado y el endpoint para **abrir** un pedido
vacío en una mesa. Agregar/quitar productos del pedido es BE-026. Cerrarlo
(cobrar) o descartarlo sin cobrar es BE-027. Verificar que reportes/Sheets/
conteo de mesas no traten "abierta" como venta real es BE-028.

## Alcance

**Incluye:**

- `backend/app/models/venta.py`:
  - Constante nueva `ESTADO_ABIERTA = "abierta"`, junto a `ESTADO_ACTIVA`/
    `ESTADO_CANCELADA`.
  - `CheckConstraint` de `estado` actualizado: `estado IN ('activa',
    'cancelada', 'abierta')`.
  - `metodo_pago` pasa a **nullable** (`Mapped[str | None] =
    mapped_column(String(20), nullable=True)`): un pedido `abierta` todavía
    no tiene método de pago (se asigna recién al cerrarlo, BE-027). El
    `CheckConstraint` de `metodo_pago` debe permitir `NULL` además de los
    dos valores existentes (ej. `metodo_pago IS NULL OR metodo_pago IN
    (...)`).
  - Mismo caveat de migración ligera que BE-017/BE-020 (sin Alembic,
    `ALTER TABLE` no reconstruye `CheckConstraint`s en SQLite): extender
    `backend/app/db/migrations.py` para que, sobre una tabla `ventas` ya
    existente sin el estado `abierta` soportado, no haga falta ningún
    `ALTER TABLE` de columna nueva (no se agrega columna, solo se relaja lo
    que la capa de aplicación permite escribir en `estado`/`metodo_pago`) —
    **sí** hace falta, sin embargo, alterar `metodo_pago` para permitir
    `NULL` en bases preexistentes donde quedó `NOT NULL` desde BE-006/BE-009
    (SQLite no soporta `ALTER COLUMN` directo; documentar y resolver con el
    mismo patrón de "detectar y migrar" ya usado por BE-020, evaluando si
    hace falta el patrón completo de "tabla nueva + copiar filas + renombrar"
    o si alcanza con dejar la restricción `NOT NULL` únicamente a nivel de
    aplicación — decisión y trade-off a documentar explícitamente en notas
    de implementación, igual que BE-020 documentó la limitación del
    `CheckConstraint` no migrado).
- `backend/app/schemas/venta.py`:
  - `EstadoVenta` enum: agregar `abierta = "abierta"`.
  - `VentaOut.metodo_pago` pasa a `MetodoPago | None`.
  - Schema nuevo `VentaAbrir`: `mesa_id: int` (obligatorio — un pedido
    abierto siempre está atado a una mesa, a diferencia de `VentaCreate`
    donde `mesa_id` es opcional para ventas de mostrador/venta libre).
- `backend/app/routers/ventas.py`:
  - Endpoint nuevo `POST /ventas/abrir` (antes de las rutas con
    `{venta_id}` en el path, para no chocar con el matching de rutas):
    - 404 si `payload.mesa_id` no existe.
    - 409 si la mesa ya tiene una venta con `estado == ESTADO_ABIERTA`
      (mensaje claro, ej. "La mesa ya tiene un pedido abierto"; devolver en
      el detalle o dejar que el frontend resuelva vía `GET
      /ventas?mesa_id=X&estado=abierta` — decisión del implementador, sin
      necesidad de exponer el id en el error). Esto establece el invariante
      que el resto de la feature asume: **como máximo una venta `abierta`
      por mesa a la vez**.
    - Crea una `Venta` con `mesa_id=payload.mesa_id`, `estado=
      ESTADO_ABIERTA`, `metodo_pago=None`, `total=0`, `items=[]` (sin
      items iniciales — agregarlos es responsabilidad de BE-026; esta
      tarea NO acepta `items` en el payload de apertura, para mantener el
      alcance acotado a "crear el contenedor vacío").
    - Marca la mesa como `ESTADO_OCUPADA` (mismo efecto que `crear_venta`
      hoy).
    - `db.commit()`, `db.refresh(venta)`, devuelve `VentaOut` (con
      `estado: "abierta"`, `metodo_pago: null`, `items: []`, `total: 0`).
    - **No** dispara sincronización a Google Sheets (un pedido abierto no
      es una venta real todavía; se sincroniza recién al cerrarse, BE-027).
  - `GET /ventas`: el parámetro `estado` ya acepta cualquier valor del enum
    `EstadoVenta` sin cambios de código (se beneficia automáticamente de
    agregar `abierta` al enum) — verificar explícitamente que
    `GET /ventas?mesa_id=X&estado=abierta` funciona para encontrar el
    pedido en curso de una mesa.
  - `crear_venta` (`POST /ventas`, flujo de venta directa existente): sin
    cambios de comportamiento — sigue creando siempre con
    `estado=ESTADO_ACTIVA` y `metodo_pago` obligatorio (su schema
    `VentaCreate` no cambia, `metodo_pago: MetodoPago` sigue siendo
    requerido ahí, solo la columna del modelo se vuelve nullable para
    permitir el caso `abierta`).

**No incluye (fuera de alcance):**

- Agregar o quitar productos de un pedido abierto — BE-026.
- Cerrar (cobrar) o descartar un pedido abierto — BE-027.
- Cualquier cambio en `reportes.py`, `sheets_service.py` o
  `_contar_ventas` de `mesas.py` — se **verifican** (sin asumir que ya
  funcionan) en BE-028.
- Permitir `items` en el payload de `POST /ventas/abrir` — no está pedido,
  mantiene el alcance acotado (si se necesita "abrir con el primer
  producto ya incluido" como atajo de UX, es responsabilidad del frontend
  encadenar `POST /ventas/abrir` + `POST /ventas/{id}/items` de BE-026, no
  de este endpoint).
- Permitir `mesa_id: null` en `VentaAbrir` — un pedido abierto sin mesa no
  tiene sentido de negocio (la venta libre de mostrador sigue siendo
  `POST /ventas` de una sola vez, sin pasar por "abierta").

## Criterios de aceptación

- [ ] `Venta.estado` acepta `"abierta"` además de `"activa"`/`"cancelada"`
      (columna y `CheckConstraint`, o documentado el trade-off si el
      `CheckConstraint` no se puede migrar en bases preexistentes, mismo
      criterio de honestidad que BE-020).
- [ ] `Venta.metodo_pago` es nullable en el modelo y en `VentaOut`.
- [ ] `POST /ventas/abrir` con un `mesa_id` existente y sin pedido abierto
      previo responde `201` con `estado: "abierta"`, `metodo_pago: null`,
      `items: []`, `total: 0`, y `GET /mesas` inmediatamente después
      muestra esa mesa `ocupada`.
- [ ] `POST /ventas/abrir` con `mesa_id` inexistente responde `404`.
- [ ] `POST /ventas/abrir` sobre una mesa que ya tiene una venta `abierta`
      responde `409`, sin crear una segunda venta abierta para esa mesa
      (verificado con un `GET /ventas?mesa_id=X&estado=abierta` que sigue
      devolviendo solo la original).
- [ ] `GET /ventas?estado=abierta` devuelve únicamente ventas en ese
      estado; `GET /ventas?mesa_id=X&estado=abierta` devuelve como máximo
      un elemento para cualquier mesa `X`.
- [ ] `POST /ventas` (flujo directo existente) sigue exigiendo
      `metodo_pago` en el payload y sigue creando con `estado: "activa"` —
      sin regresión.
- [ ] `POST /ventas/abrir` sin header `Authorization` responde `401`.
- [ ] Documentado en notas de implementación el paso de migración (o su
      limitación aceptada) para bases SQLite preexistentes, con el mismo
      nivel de detalle y honestidad que BE-020.

## Notas de implementación

Implementado tal como está descrito en la tarea, sin desviaciones.

**Archivos tocados:**

- `backend/app/models/venta.py`: constante nueva `ESTADO_ABIERTA = "abierta"`;
  `CheckConstraint` de `estado` actualizado a
  `estado IN ('activa', 'cancelada', 'abierta')`; `metodo_pago` pasa a
  `Mapped[str | None] = mapped_column(String(20), nullable=True)`, y su
  `CheckConstraint` a `metodo_pago IS NULL OR metodo_pago IN ('efectivo',
  'transferencia')`.
- `backend/app/schemas/venta.py`: `EstadoVenta.abierta = "abierta"`;
  `VentaOut.metodo_pago: MetodoPago | None`; schema nuevo `VentaAbrir`
  (`mesa_id: int`, obligatorio, sin `items`).
- `backend/app/routers/ventas.py`: `POST /ventas/abrir` agregado justo
  después de `crear_venta` (antes de las rutas con `{venta_id}` en el path,
  tal como pide el alcance, aunque en la práctica no había conflicto de
  matching porque ningún otro `POST` usa un solo segmento de path). 404 si
  la mesa no existe; 409 (`"La mesa ya tiene un pedido abierto"`) si ya hay
  una `Venta` con `estado == ESTADO_ABIERTA` para esa mesa (consulta
  explícita antes de crear, sin exponer el id de la venta existente en el
  error — el frontend puede recuperarlo con
  `GET /ventas?mesa_id=X&estado=abierta` si lo necesita); si no, crea la
  `Venta` con `metodo_pago=None`, `estado=ESTADO_ABIERTA`, `total=0`,
  `items=[]`, marca la mesa `ESTADO_OCUPADA`, y **no** encola ninguna
  sincronización a Sheets.

**Migración ligera (`backend/app/db/migrations.py`), decisión y trade-off
documentados explícitamente como pide la tarea:**

A diferencia del `CheckConstraint` de `estado` (cuya limitación de no poder
migrarse con `ALTER TABLE` ya fue aceptada conscientemente en BE-020, porque
nunca bloquea un `INSERT`/`UPDATE` real: la app nunca escribe un valor fuera
del enum), volver `metodo_pago` nullable **sí** es una migración que
importa para la funcionalidad: en cualquier base SQLite donde esa columna
siga siendo `NOT NULL` a nivel de motor (cualquier instalación previa a esta
tarea, sin importar si ya tenía o no la columna `estado`), `POST
/ventas/abrir` fallaría con `sqlite3.IntegrityError` al intentar persistir
`metodo_pago=NULL`. SQLite no soporta `ALTER TABLE ... ALTER COLUMN` para
relajar un `NOT NULL` ni para reescribir un `CheckConstraint` ya grabado en
el `CREATE TABLE` original. Se decidió, por lo tanto, sí aplicar aquí el
patrón completo "copiar a tabla nueva con el esquema correcto, migrar filas,
renombrar" (a diferencia del resto del módulo, que solo agrega columnas):

- `_permitir_metodo_pago_nulo_ventas(engine)` (nueva): inspecciona la
  columna `metodo_pago` de `ventas`; si ya es nullable (instalación nueva
  creada con el esquema completo, o ya migrada), no hace nada. Si es `NOT
  NULL`, renombra `ventas` a `_ventas_old_be025`, crea una tabla `ventas`
  nueva con el esquema completo y correcto (columnas idénticas,
  `metodo_pago` nullable, `CheckConstraint`s actualizados con `abierta` y
  `IS NULL OR ...`), copia todas las filas de la tabla vieja (mismos `id`,
  preservando también las referencias de `venta_items.venta_id`, que no se
  tocan) y borra la tabla vieja. Todo dentro de un único `engine.begin()`
  (transacción atómica: si algo falla, no queda a medio migrar).
- `run_lightweight_migrations` corre `_agregar_columna_estado_ventas`
  primero (garantiza que la columna `estado` exista, para el caso más
  antiguo de una base antes de BE-020) y **después**
  `_permitir_metodo_pago_nulo_ventas` (que copia esa columna al reconstruir
  la tabla).
- Documentado también en el docstring del módulo el porqué de este
  trade-off distinto al de BE-020 (aquí sí se justifica el costo de
  reconstruir la tabla, porque la limitación real bloquea una feature
  nueva pedida explícitamente, no es solo una validación redundante).

**Verificado explícitamente (no solo por lectura de código), con tres
escenarios de base de datos distintos, todos con servidores `uvicorn`
temporales en puertos propios (8197/8198/8199) sobre SQLite en el
scratchpad de la sesión — nunca se tocó `backend/brainfreeze.db` real
(confirmado con `git status` al final, sin cambios en ese archivo):**

1. **Base nueva (esquema ya correcto desde el inicio, puerto 8199):**
   `POST /ventas/abrir` con mesa existente y sin pedido previo -> `201`,
   `estado: "abierta"`, `metodo_pago: null`, `items: []`, `total: 0`; `GET
   /mesas` inmediatamente después muestra la mesa `ocupada`. Repetir `POST
   /ventas/abrir` sobre la misma mesa -> `409`, y `GET
   /ventas?mesa_id=X&estado=abierta` sigue devolviendo un único elemento
   (la original). `POST /ventas/abrir` con `mesa_id: 999` -> `404`. Sin
   header `Authorization` -> `401`. `POST /ventas` (flujo directo) sigue
   exigiendo `metodo_pago` (`422` si se omite) y sigue creando con
   `estado: "activa"` — sin regresión.
2. **Base "legacy" simulada con `sqlite3` puro (esquema post-BE-020/pre-
   BE-025: columna `estado` ya presente con `CheckConstraint` de 2 valores,
   `metodo_pago` `NOT NULL` con su propio `CheckConstraint` de 2 valores —
   tal como habría quedado una instalación creada entre el deploy de BE-020
   y el de BE-025), con una venta histórica de prueba (puerto 8198): antes
   de arrancar, `PRAGMA table_info(ventas)` confirmó `metodo_pago` con
   `notnull=1`. Al levantar el servidor, el log mostró exactamente el
   mensaje de reconstrucción de tabla esperado y "Tabla 'ventas'
   reconstruida correctamente...". Después: `PRAGMA table_info(ventas)`
   confirmó `metodo_pago` con `notnull=0`; `SELECT * FROM ventas`/`SELECT *
   FROM venta_items` confirmaron que la fila histórica no perdió ningún
   dato (mismos `id`/`mesa_id`/`metodo_pago`/`estado`/`total`/`creado_en`,
   mismo item asociado). Vía API: `GET /ventas/1` devolvió la venta
   histórica completa y legible; `POST /ventas/abrir` sobre esa misma mesa
   funcionó (insertó `metodo_pago=NULL` sin error). **Idempotencia:**
   reiniciar el servidor una segunda vez sobre esa misma base ya migrada no
   mostró ningún log de migración y arrancó normal.
3. **Base "ancestral" simulada con `sqlite3` puro (esquema pre-BE-020: sin
   columna `estado` en absoluto, `metodo_pago` `NOT NULL`), puerto 8197:**
   al arrancar, el log mostró **ambas** migraciones en cadena en el orden
   correcto (`_agregar_columna_estado_ventas` primero, agregando `estado`
   vía `ALTER TABLE`; luego `_permitir_metodo_pago_nulo_ventas`,
   reconstruyendo la tabla ya con `estado` incluido). `SELECT * FROM
   ventas` confirmó la fila histórica intacta (`estado='activa'` por el
   default de la primera migración). Vía API: `GET /ventas/1` y `POST
   /ventas/abrir` funcionaron correctamente sobre el dato migrado.

Servidores y bases de datos temporales (`fresh.db`, `legacy.db`,
`ancient.db`) detenidos/eliminados del scratchpad de la sesión al terminar;
no se dejaron procesos corriendo fuera de los tres puertos de prueba, y
esos tres se confirmaron detenidos (`netstat` sin listeners activos en
8197-8199 al finalizar).

**Cómo probarlo:** `uvicorn app.main:app --port 8123` con
`DATABASE_URL`/`SHEETS_SYNC_ENABLED=false` apuntando a una SQLite propia,
usuario vía `python -m app.scripts.crear_usuario`. Ejemplo:
`POST /ventas/abrir` con body `{"mesa_id": 1}` y header
`Authorization: Bearer <token>` -> `201` con la venta abierta.

## Revisión

**Veredicto: `done`**

Código revisado (`app/models/venta.py`, `app/schemas/venta.py`,
`app/routers/ventas.py`, `app/db/migrations.py`) coincide exactamente con lo
descrito en las notas de implementación. Verificado end-to-end con un
servidor `uvicorn` propio (puerto 8300) sobre una SQLite temporal en el
scratchpad de la sesión (nunca se tocó `backend/brainfreeze.db`, confirmado
con `git status`):

- `POST /ventas/abrir` con mesa existente sin pedido previo -> `201`,
  `estado: "abierta"`, `metodo_pago: null`, `items: []`, `total: 0`; `GET
  /mesas` refleja la mesa `ocupada` de inmediato.
- Repetir sobre la misma mesa -> `409`. Mesa inexistente -> `404`. Sin
  `Authorization` -> `401`.
- `_permitir_metodo_pago_nulo_ventas` en `migrations.py`: lógica de
  reconstrucción de tabla revisada línea por línea — el `CREATE TABLE`
  nuevo reproduce fielmente las columnas/constraints del modelo
  (`mesa_id` FK, `metodo_pago` nullable, `estado` con el `CheckConstraint`
  de 3 valores), la migración corre dentro de un único `engine.begin()`
  (atómica), y el orden en `run_lightweight_migrations`
  (`_agregar_columna_estado_ventas` antes de
  `_permitir_metodo_pago_nulo_ventas`) es correcto. No se re-ejecutó la
  migración contra una base legacy real (el usuario ya lo verificó
  personalmente contra la base de desarrollo, 11 ventas/11 items
  intactos); la revisión aquí fue de lógica/orden/atomicidad del código,
  no una repetición de esa prueba.
- Sin regresión: `POST /ventas` sigue exigiendo `metodo_pago` y crea con
  `estado: "activa"`.

Sin hallazgos.
