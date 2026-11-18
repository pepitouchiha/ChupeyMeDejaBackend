---
id: BE-021
title: Editar una venta existente (items, mesa, método de pago) y obtener una venta por id
area: backend
status: done
priority: high
depends_on: [BE-020]
created_by: planner
---

## Objetivo

El dueño del negocio pidió poder "corregir" un pedido ya registrado (agregar
un producto olvidado, quitar uno que sobró, cambiar la cantidad, cambiar de
mesa o de método de pago) sin tener que cancelarlo y crear uno nuevo. Hoy
`POST /ventas` es la única forma de escribir una venta y no existe ningún
endpoint de edición. Esta tarea agrega `PUT /ventas/{venta_id}` (reemplazo
completo de los items + mesa + método de pago, mismo espíritu que
`POST /ventas`) y `GET /ventas/{venta_id}` (detalle de una venta puntual,
que hoy no existe — solo existe el listado).

## Alcance

**Incluye:**

- `backend/app/schemas/venta.py`: `VentaUpdate` con la misma forma que
  `VentaCreate` (`items: list[VentaItemCreate]`, `metodo_pago: MetodoPago`,
  `mesa_id: int | None = None`), con el mismo validador de "al menos un
  item" que ya tiene `VentaCreate` (puede heredar de una base común o
  duplicar el validador — decisión del implementador, sin over-engineering).
- `backend/app/routers/ventas.py`:
  - `GET /ventas/{venta_id}` (nuevo): 404 si no existe, si no `VentaOut`
    completo (con sus items). Usar `joinedload(Venta.items)` igual que
    `listar_ventas`, para no traer los items con lazy-load fila por fila.
  - `PUT /ventas/{venta_id}` (nuevo):
    - 404 si `venta_id` no existe.
    - 409 si `venta.estado == ESTADO_CANCELADA` ("No se puede editar una
      venta cancelada"), sin ningún cambio.
    - Validar que exista la mesa nueva (si `payload.mesa_id` no es `None`) y
      que existan **todos** los productos referenciados en `payload.items`
      (mismo patrón de validación completa-antes-de-mutar que ya usa
      `crear_venta`: dedupe por `producto_id`, 404 con mensaje claro si
      falta alguno, **sin dejar cambios parciales** si algo falla).
    - Reemplazar por completo los items de la venta: quitar los
      `VentaItem` existentes y crear los nuevos a partir de
      `payload.items`, con `precio_unitario` tomado del precio **actual**
      del producto en el momento de la edición (no se preserva el precio
      congelado original de cada item — es una edición nueva, con precios
      vigentes al momento de editar; documentar esto explícitamente como
      decisión consciente, mismo tipo de nota que ya dejó BE-018 para
      "costo actual vs. histórico"). Aprovechar que la relación
      `Venta.items` tiene `cascade="all, delete-orphan"` (ya configurada
      desde BE-006): reasignar `venta.items` a la lista nueva de
      `VentaItem` es suficiente para que SQLAlchemy borre los huérfanos
      viejos al hacer `commit`.
    - Recalcular `total` 100% en el servidor a partir de los productos y
      cantidades del payload (igual criterio que `crear_venta`: cualquier
      total que mande el cliente se ignora porque el schema no lo expone).
    - Reasignación de mesa (comparar `mesa_id` **antes** de aplicar el
      cambio, contra el valor que tenía `venta.mesa_id` al entrar al
      endpoint):
      - Si la mesa nueva es distinta de la mesa vieja (incluye el caso de
        pasar a `None`, o de `None` a una mesa): marcar la mesa **nueva**
        (si no es `None`) como `ESTADO_OCUPADA`.
      - Para la mesa **vieja** (si no era `None` y cambió): antes de
        liberarla, verificar si **alguna otra** venta con
        `estado == ESTADO_ACTIVA` (excluyendo la venta que se está editando)
        sigue referenciando esa misma mesa; si no hay ninguna otra, marcarla
        `ESTADO_LIBRE`; si hay otra venta activa usándola, no tocar su
        estado (sigue ocupada, correctamente, porque otra orden activa
        todavía la usa). Implementar como una función/query auxiliar
        explícita (ej. `_mesa_tiene_otra_venta_activa(db, mesa_id,
        excluir_venta_id)`), no como una suposición implícita.
      - Si la mesa nueva es la misma que la vieja (ambas `None`, o ambas el
        mismo id): no tocar el estado de ninguna mesa.
    - `venta.metodo_pago = payload.metodo_pago.value`.
    - `db.commit()`, `db.refresh(venta)`, devuelve `VentaOut` actualizado.
    - No dispara sincronización a Google Sheets en esta tarea (ver BE-022).

**No incluye (fuera de alcance):**

- Cambiar el `estado` de la venta a través de este endpoint (`PUT` no
  acepta `estado` en el payload; cancelar sigue siendo exclusivamente
  `POST /ventas/{id}/cancelar` de BE-020).
- Preservar `precio_unitario` histórico de los items que no cambiaron —
  toda la lista de items se reemplaza con precios vigentes al momento de
  la edición, tal como se describe arriba (no hay "edición parcial de un
  solo item" que preserve el resto intacto).
- Reflejar la edición en Google Sheets — eso es BE-022.
- Excluir ediciones de los reportes/margen — no aplica (una venta editada
  sigue activa y se sigue contando normalmente; solo las canceladas se
  excluyen, ver BE-023).
- Descuento de inventario de insumos por edición — sigue sin implementarse,
  mismo alcance no cubierto que ya documentó BE-006 para la creación.

## Criterios de aceptación

- [ ] `GET /ventas/{id}` con un id inexistente responde `404`; con un id
      existente responde `200` con la venta completa (incluidos sus items).
- [ ] `PUT /ventas/{id}` recalcula `total` en el servidor a partir de
      `payload.items` y los precios **actuales** de los productos,
      ignorando cualquier total que mande el cliente.
- [ ] `PUT /ventas/{id}` reemplaza correctamente los items: agregar un
      producto nuevo, quitar uno existente, y cambiar la cantidad de otro,
      se reflejan exactamente en el `GET /ventas/{id}` posterior (ni items
      viejos residuales, ni duplicados).
- [ ] `PUT /ventas/{id}` sobre una venta cancelada responde `409`, sin
      ningún cambio en items/mesa/total/estado.
- [ ] `PUT /ventas/{id}` con `producto_id` o `mesa_id` inexistente en el
      payload responde `404`, y los items/mesa/total originales de la venta
      quedan exactamente igual que antes del intento (sin cambios
      parciales).
- [ ] `PUT /ventas/{id}` cambiando `mesa_id` de A a B: mesa A queda
      `libre` (si ninguna otra venta activa la usa) y mesa B queda
      `ocupada` — verificado con `GET /mesas` antes/después.
- [ ] `PUT /ventas/{id}` cambiando `mesa_id` de A a B, cuando **otra** venta
      activa distinta también tiene `mesa_id = A`: mesa A permanece
      `ocupada` (no se libera incorrectamente) tras la edición.
- [ ] `PUT /ventas/{id}` cambiando `mesa_id` de un valor a `null` libera la
      mesa vieja (con el mismo cuidado de "otra venta activa" del criterio
      anterior).
- [ ] `PUT /ventas/{id}` con el mismo `mesa_id` que ya tenía (sin cambio) no
      altera el estado de ninguna mesa.
- [ ] El `precio_unitario` de los items tras editar corresponde al precio
      **actual** del producto al momento de la edición (documentado como
      decisión consciente, no un descuido) — verificado cambiando el precio
      de un producto entre la creación original de la venta y su edición.
- [ ] `GET /ventas/{id}` y `PUT /ventas/{id}` sin header `Authorization`
      responden `401`.

## Notas de implementación

Implementado tal como está descrito en la tarea, sin desviaciones.

**Archivos tocados:**

- `backend/app/schemas/venta.py`: se extrajo `_VentaItemsBase` (con
  `items`/`metodo_pago`/`mesa_id` y el validador `validar_items` de "al
  menos un item") de la que heredan tanto `VentaCreate` como `VentaUpdate`
  (ambos idénticos en forma, sin duplicar el validador; decisión de
  implementador permitida explícitamente por el alcance de la tarea).
- `backend/app/routers/ventas.py`:
  - `_mesa_tiene_otra_venta_activa(db, mesa_id, excluir_venta_id)`: función
    auxiliar explícita (no una suposición implícita) que consulta si existe
    alguna otra `Venta` con `estado == ESTADO_ACTIVA` y ese `mesa_id`,
    excluyendo la venta que se está editando.
  - `GET /ventas/{venta_id}` (nuevo): `db.query(Venta).options(joinedload(Venta.items)).filter(Venta.id == venta_id).first()`
    (mismo patrón de `joinedload` que `listar_ventas`, para no traer items
    con lazy-load fila por fila); 404 si no existe.
  - `PUT /ventas/{venta_id}` (nuevo): 404 si no existe la venta; 409 (`"No
    se puede editar una venta cancelada"`) si `venta.estado ==
    ESTADO_CANCELADA`, sin ningún cambio. Todas las validaciones (mesa nueva
    si `payload.mesa_id is not None`, y **todos** los productos referenciados
    en `payload.items`, deduplicados por `producto_id` igual que
    `crear_venta`) ocurren **antes** de mutar cualquier estado — si algo
    falla (404 de mesa o de producto), no queda ningún cambio parcial
    (verificado explícitamente, ver abajo). Reemplazo completo de items:
    `venta.items = nuevos_items` (aprovechando el
    `cascade="all, delete-orphan"` ya configurado en el modelo desde
    BE-006, que borra los `VentaItem` huérfanos viejos al hacer `commit`),
    con `precio_unitario` tomado del `producto.precio` **actual** en el
    momento de la edición (no se preserva el precio congelado original,
    documentado como decisión consciente igual que pidió la tarea). `total`
    recalculado 100% en servidor a partir de `payload.items` y los precios
    actuales — cualquier total que mande el cliente se ignora porque
    `VentaUpdate` no lo expone. Reasignación de mesa: se captura
    `mesa_vieja_id = venta.mesa_id` **antes** de mutar nada; si
    `payload.mesa_id != mesa_vieja_id`, la mesa nueva (si no es `None`) se
    marca `ESTADO_OCUPADA`, y la mesa vieja (si no era `None`) se libera
    solo si `_mesa_tiene_otra_venta_activa` devuelve `False` (si otra venta
    activa distinta sigue usándola, no se toca su estado). Si la mesa nueva
    es igual a la vieja (incluye ambas `None`), no se toca ninguna mesa.
    `venta.metodo_pago = payload.metodo_pago.value`. No dispara
    sincronización a Google Sheets (eso es BE-022).

**No se tocó** el `estado` de la venta a través de este endpoint (`VentaUpdate`
no expone ese campo); tampoco se preservó `precio_unitario` histórico de
items sin cambios, ni se descuenta inventario de insumos — todo consistente
con el alcance explícito de la tarea.

**Cómo se probó:** igual metodología que BE-020 (sin `httpx`/`TestClient`,
servidor real `uvicorn` sobre la misma SQLite temporal ya usada por BE-020,
con `SHEETS_SYNC_ENABLED=false`). Casos verificados con `curl`, todos
exitosos:

- `GET /ventas/999` (inexistente) -> `404`; `GET /ventas/{id existente}` ->
  `200` con la venta completa (incluidos items).
- Creadas dos ventas activas nuevas sobre la misma mesa (`mesa_id=1`):
  editar la primera (`PUT`) cambiando su mesa a otra mesa (`mesa_id=2`) y
  sus items (agregar un producto, cambiar cantidad de otro) -> `total`
  recalculado correctamente en servidor (`2x8000 + 1x3000 = 19000`),
  `GET /ventas/{id}` posterior refleja exactamente los items nuevos (sin
  residuales ni duplicados, IDs de `VentaItem` nuevos). `GET /mesas`
  confirma: mesa vieja (mesa 1) sigue `ocupada` porque la **segunda** venta
  activa aún la usa; mesa nueva (mesa 2) pasa a `ocupada`.
- Editar la segunda venta (todavía en mesa 1) cambiando `mesa_id` a `null`:
  mesa 1 pasa a `libre` (ya ninguna venta activa la usa) — verificado con
  `GET /mesas` antes/después.
- Editar esa misma venta de nuevo con el mismo `mesa_id: null` (sin cambio):
  `GET /mesas` no se altera.
- `PUT` sobre una venta cancelada -> `409` (`"No se puede editar una venta
  cancelada"`), y `GET /ventas/{id}` posterior confirma que items/mesa/total
  /estado quedaron exactamente iguales.
- `PUT` con `producto_id` inexistente (`999`) -> `404`; `PUT` con `mesa_id`
  inexistente (`999`) -> `404`; en ambos casos, `GET /ventas/{id}` posterior
  confirma que items/mesa/total originales no cambiaron (sin cambios
  parciales) y `GET /mesas` tampoco cambió.
- Se subió el precio de un producto (`PATCH /productos/{id}` de `8000` a
  `9500`) y se editó (`PUT`) una venta que ya tenía ese producto: el
  `precio_unitario` del item resultante refleja `9500` (precio actual), no
  el `8000` original, y el `total` se recalculó en consecuencia
  (`2x9500 + 1x3000 = 22000`) — decisión consciente documentada en el
  alcance de la tarea, verificada end-to-end.
- `GET /ventas/{id}` y `PUT /ventas/{id}` sin header `Authorization` -> `401`
  en ambos.

Servidor y base de datos temporal reutilizados de la sesión de BE-020 y
detenidos/eliminados al finalizar la verificación de BE-023 (ver notas de
esa tarea), sin dejar procesos ni artefactos fuera del scratchpad de la
sesión.

## Revisión

**Veredicto: `done`.**

Revisé `backend/app/routers/ventas.py` completo (no solo el diff) y
reproduje end-to-end, con un servidor real y una SQLite temporal propia
(no reutilicé la del implementador), el escenario más delicado de la
tarea: la liberación/ocupación de mesa cuando hay varias ventas activas
compitiendo por la misma mesa.

- **Reasignación de mesa con otra venta activa en la mesa vieja:** creé dos
  ventas activas en `mesa_id=1`. Al editar la primera (`PUT`, cambiando
  items y `mesa_id` a `2`), el `total` se recalculó correctamente en
  servidor (`2×8000 + 1×3000 = 19000`, ignorando cualquier total del
  cliente) y `GET /mesas` confirmó: mesa 1 sigue `ocupada` (la segunda
  venta activa la sigue usando) y mesa 2 pasa a `ocupada`. Los items
  quedaron reemplazados exactamente (IDs nuevos, sin residuales ni
  duplicados, verificado con `GET /ventas/{id}`).
- Editar la segunda venta (única activa que quedaba en mesa 1) a
  `mesa_id: null` sí liberó la mesa 1 (`GET /mesas` -> `libre`). Repetir la
  misma edición sin cambio de mesa no alteró ningún estado de mesa.
- `PUT` sobre una venta cancelada -> `409` sin cambios.
- `PUT` con `producto_id` inexistente y con `mesa_id` inexistente -> `404`
  en ambos, y confirmé con `GET /ventas/{id}` que la orden queda
  exactamente igual que antes del intento en los dos casos (sin cambios
  parciales) — la validación de mesa y de todos los productos ocurre
  antes de mutar cualquier estado, tal como pide el alcance.
- `GET /ventas/{id}` -> `404` con id inexistente, `200` con items incluidos
  con id existente (`joinedload`, sin N+1 evidente).
- `precio_unitario` tras editar usa el precio **actual** del producto (no
  el congelado original) — decisión documentada correctamente en el código
  y en el alcance.
- `401` sin `Authorization` en `GET`/`PUT /ventas/{id}`, sin regresión.

No se encontraron hallazgos bloqueantes. La extracción de `_VentaItemsBase`
compartida entre `VentaCreate`/`VentaUpdate` y el helper
`_mesa_tiene_otra_venta_activa` son razonables y no agregan complejidad
injustificada.
