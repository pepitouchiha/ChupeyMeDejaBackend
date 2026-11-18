---
id: BE-026
title: Agregar y quitar productos de un pedido abierto en curso
area: backend
status: done
priority: high
depends_on: [BE-025]
created_by: planner
---

## Objetivo

BE-025 permite abrir un pedido vacío (`estado: "abierta"`) para una mesa.
Esta tarea agrega la forma de ir anotando productos en ese pedido a medida
que el cliente los pide a lo largo del tiempo (una bebida ahora, un postre
20 minutos después), y de corregir un producto agregado por error antes de
cerrar la mesa — sin recalcular precios de items ya existentes y sin
exigir método de pago (eso sigue sin definirse hasta BE-027).

Esto es **distinto** de `PUT /ventas/{id}` (BE-021): ese endpoint reemplaza
por completo los items de una venta ya cobrada, con precios recalculados
para *todos* los items al momento de la edición (corrección post-cobro).
Esta tarea, en cambio, **agrega** filas nuevas a una venta todavía sin
cobrar, cada una con el precio vigente en el momento en que se pidió ese
producto — el precio de un item agregado hace 20 minutos no se toca por
agregar uno nuevo ahora.

## Alcance

**Incluye**, todo en `backend/app/routers/ventas.py` y
`backend/app/schemas/venta.py`:

- Schema nuevo `VentaAgregarItems`: `items: list[VentaItemCreate]`, con el
  mismo validador de "al menos un item" que ya usa `_VentaItemsBase`
  (reutilizarlo o duplicarlo, mismo criterio de BE-021).
- `POST /ventas/{venta_id}/items`:
  - 404 si `venta_id` no existe.
  - 409 si `venta.estado != ESTADO_ABIERTA` (mensaje claro, ej. "Solo se
    pueden agregar productos a un pedido abierto") — a diferencia de
    `PUT /ventas/{id}`, que solo bloquea `cancelada`, este endpoint es
    exclusivo del flujo de pedido en curso y rechaza tanto `activa` como
    `cancelada`.
  - Validar que existan **todos** los productos referenciados en
    `payload.items` (mismo patrón dedupe-por-`producto_id` que
    `crear_venta`/`actualizar_venta`; 404 con mensaje claro si falta
    alguno, sin dejar cambios parciales).
  - Crear un `VentaItem` **nuevo** por cada línea de `payload.items` (no
    fusionar cantidades con un item existente del mismo producto, aunque
    ya hubiera uno — cada "agregado" es una fila propia; simplifica la
    lógica y evita ambigüedad sobre qué precio prevalece si el producto
    cambió de precio entre pedidos), con `precio_unitario` tomado del
    `producto.precio` **vigente en este momento** (no se tocan los
    `precio_unitario` de los items ya existentes en la venta).
  - `venta.total += suma(precio_unitario * cantidad de los items nuevos)`
    (no se recalcula el total completo desde cero — se incrementa sobre el
    total ya acumulado, para no alterar accidentalmente el valor de items
    previos si un precio cambió entre medio).
  - No toca `mesa_id` ni `metodo_pago`.
  - `db.commit()`, `db.refresh(venta)`, devuelve `VentaOut` actualizado
    (con todos los items acumulados hasta ahora y el `total` nuevo).
  - No dispara sincronización a Google Sheets (un pedido abierto no es una
    venta real todavía).
- `DELETE /ventas/{venta_id}/items/{item_id}`:
  - 404 si `venta_id` no existe, o si `item_id` no existe, o si el
    `VentaItem` con ese `item_id` no pertenece a `venta_id`.
  - 409 si `venta.estado != ESTADO_ABIERTA` (mismo mensaje/criterio que
    arriba — no se pueden quitar items de una venta ya cobrada por esta
    vía; eso, si hiciera falta, seguiría siendo `PUT /ventas/{id}` de
    BE-021).
  - Elimina ese `VentaItem` puntual y resta su subtotal
    (`precio_unitario * cantidad`) del `total` de la venta.
  - `db.commit()`, `db.refresh(venta)`, devuelve `VentaOut` actualizado.
  - **No** valida "al menos un item restante" — un pedido abierto puede
    quedar en 0 items tras quitar el último (ej. el cliente canceló lo
    único que había pedido); ese caso de "pedido abierto vacío" es
    relevante para el "descartar" de BE-027, no para este endpoint.

**No incluye (fuera de alcance):**

- Cerrar/cobrar el pedido o descartarlo — BE-027.
- Cambiar la cantidad de un item existente sin borrarlo y volver a
  agregarlo (no se pidió un `PATCH` de cantidad; el flujo es
  agregar-nueva-línea / borrar-línea-existente, suficiente para el caso de
  uso descrito).
- Descuento de inventario de insumos — mismo alcance no cubierto que ya
  documentaron BE-006/BE-021.

## Criterios de aceptación

- [ ] `POST /ventas/{id}/items` sobre un pedido `abierta` agrega los items
      nuevos sin alterar `precio_unitario` de los items ya existentes,
      incluso si el precio del producto cambió entre el primer agregado y
      este.
- [ ] `POST /ventas/{id}/items` incrementa `total` correctamente sobre el
      valor previo (verificado con un caso numérico: pedido con total
      inicial > 0, agregar más productos, el total resultante es la suma
      exacta, no un recálculo que ignore items previos).
- [ ] `POST /ventas/{id}/items` sobre una venta `activa` o `cancelada`
      responde `409`, sin ningún cambio en sus items/total.
- [ ] `POST /ventas/{id}/items` con `producto_id` inexistente responde
      `404`, sin dejar ningún item agregado parcialmente.
- [ ] `POST /ventas/{id}/items` con `venta_id` inexistente responde `404`.
- [ ] Agregar dos veces el mismo `producto_id` en llamadas separadas crea
      dos `VentaItem` distintos (no fusiona cantidades), verificado en el
      `GET /ventas/{id}` posterior.
- [ ] `DELETE /ventas/{id}/items/{item_id}` sobre un pedido `abierta` quita
      exactamente ese item y resta su subtotal del `total`, verificado en
      el `GET /ventas/{id}` posterior.
- [ ] `DELETE /ventas/{id}/items/{item_id}` con un `item_id` que pertenece
      a otra venta distinta responde `404` (no se borra por error un item
      de otra orden).
- [ ] `DELETE /ventas/{id}/items/{item_id}` sobre una venta `activa` o
      `cancelada` responde `409`, sin ningún cambio.
- [ ] `DELETE /ventas/{id}/items/{item_id}` que deja la venta en 0 items no
      falla (responde `200` con `items: []`, `total: 0`).
- [ ] Ninguno de los dos endpoints dispara sincronización a Google Sheets
      (verificar por lectura de código, sin `background_tasks.add_task`).
- [ ] Ambos endpoints sin header `Authorization` responden `401`.

## Notas de implementación

Implementado tal como está descrito en la tarea, sin desviaciones.

**Archivos tocados:**

- `backend/app/schemas/venta.py`: schema nuevo `VentaAgregarItems` (`items:
  list[VentaItemCreate]`), con su propio validador `validar_items` de "al
  menos un item" duplicado (no heredado de `_VentaItemsBase`, porque este
  schema no tiene `metodo_pago`/`mesa_id` — decisión de implementador
  explícitamente permitida por la tarea, "reutilizarlo o duplicarlo").
- `backend/app/routers/ventas.py`:
  - `POST /ventas/{venta_id}/items`: 404 si la venta no existe; 409
    (`"Solo se pueden agregar productos a un pedido abierto"`) si
    `venta.estado != ESTADO_ABIERTA` (rechaza tanto `activa` como
    `cancelada`, a diferencia de `PUT /ventas/{id}` que solo bloquea
    `cancelada`). Valida **todos** los `producto_id` referenciados antes de
    mutar nada (mismo patrón dedupe de `crear_venta`/`actualizar_venta`;
    404 con mensaje claro y sin ningún cambio parcial si falta alguno).
    Crea un `VentaItem` **nuevo** por cada línea (nunca fusiona con uno
    existente del mismo producto), con `precio_unitario` = precio vigente
    en este momento; los items existentes no se tocan. `venta.total` se
    **incrementa** sobre el valor previo (`total += suma(precio_unitario *
    cantidad de los items nuevos)`), nunca se recalcula desde cero — así un
    cambio de precio entre pedidos no afecta el subtotal ya cobrado de
    items anteriores. No dispara `sync_venta_to_sheets` en ningún punto.
  - `DELETE /ventas/{venta_id}/items/{item_id}`: 404 si la venta no existe,
    o si el `item_id` no existe, o si el `VentaItem` encontrado no
    pertenece a `venta_id` (`item.venta_id != venta_id`); 409 (mismo
    mensaje/criterio de estado) si `venta.estado != ESTADO_ABIERTA`. Resta
    `precio_unitario * cantidad` del `total` y borra el `VentaItem` puntual
    con `db.delete(item)` (no vía reasignación de `venta.items`, para no
    depender de identidad de objetos en la colección). No valida "al menos
    un item restante" — un pedido puede quedar en `items: []`, `total: 0`
    tras quitar el último, sin fallar. No dispara sincronización a Sheets.

**Cómo se probó:** sin `httpx`/`TestClient` instalado (mismo estado que
documentaron BE-020/BE-021), se levantó un servidor `uvicorn` real en un
puerto propio (`8199`) contra una SQLite temporal nueva en el scratchpad de
la sesión (`SHEETS_SYNC_ENABLED=false`), con un script Python (`requests`)
que ejecutó todos los casos de aceptación en secuencia. Casos verificados,
todos exitosos:

- Abrir un pedido, agregar 2 cafés ($5000 c/u) -> `total: 10000`; agregar 1
  postre ($8000) -> `total: 18000` (incremento correcto sobre el previo, no
  un recálculo). Subir el precio del café a $6000 (`PATCH /productos/{id}`)
  y agregar 1 café más -> `total: 24000`, **3** items en el `GET
  /ventas/{id}` posterior (no se fusionó con el item de café existente),
  con `precio_unitario` distintos preservados (`5000` y `6000` en los dos
  items de café) — confirma que los items previos no se tocan.
  - Agregar con `producto_id` inexistente -> `404`, y el `GET
    /ventas/{id}` posterior confirmó que `total` (24000) e `items` (3) no
    cambiaron (sin cambio parcial).
  - Agregar sobre `venta_id` inexistente -> `404`; agregar sobre una venta
    `activa` existente -> `409`, sin cambios en sus items/total.
  - `DELETE .../items/{item_id}` sobre el item de café a `6000` -> `200`,
    `total: 18000` (resta correcta), `2` items restantes.
  - `DELETE` con un `item_id` que pertenece a la venta `activa` (otra venta
    distinta) -> `404` (no borró nada de la otra orden).
  - `DELETE` sobre un item de la venta `activa` -> `409`.
  - (Cubierto también, de paso, con BE-027 en su propia sesión de prueba):
    `DELETE` que deja la venta en `0` items no falla, responde `200` con
    `items: []`, `total: 0` — verificado al vaciar un pedido antes de
    cerrarlo/descartarlo.
  - Confirmado por lectura de código (no solo por prueba funcional) que
    ni `agregar_items_venta` ni `quitar_item_venta` invocan
    `sync_venta_to_sheets` en ningún punto (`grep` sobre
    `backend/app/routers/ventas.py`: las únicas 5 invocaciones son
    `crear_venta`, `actualizar_venta`, `cancelar_venta`, `cerrar_venta` y
    `descartar_venta` con items — ninguna en los endpoints de esta tarea).
  - Ambos endpoints sin header `Authorization` -> `401`.

Script y servidor temporal eliminados/detenidos al finalizar (ver notas de
BE-025 y BE-027 para el detalle de la limpieza); no se tocó
`backend/brainfreeze.db` real.

## Revisión

**Veredicto: `done`**

Verificado end-to-end (servidor `uvicorn` propio, puerto 8300, SQLite
temporal, sin tocar `brainfreeze.db` real), además de lo ya cubierto en
BE-025/BE-027:

- Agregar 2 cafés + 1 postre incrementa `total` correctamente sobre el
  valor previo (no recalcula desde cero).
- Agregar con `producto_id` inexistente entre líneas válidas -> `404`,
  sin dejar ningún item parcial (`GET /ventas/{id}` posterior confirmó
  `items: []`, `total: 0`).
- `DELETE .../items/{item_id}` con un `item_id` que pertenece a otra venta
  (`activa`) -> `404` (no borra nada de la otra orden).
- `POST .../items` y `DELETE .../items/{id}` sobre una venta `activa` ->
  `409` en ambos, sin cambios.
- `DELETE` que deja la venta en `0` items -> `200`, `items: []`, `total: 0`
  sin fallar.
- Confirmado por lectura de código que ni `agregar_items_venta` ni
  `quitar_item_venta` invocan `sync_venta_to_sheets`.

Coincide exactamente con lo documentado en las notas de implementación.
Sin hallazgos.
