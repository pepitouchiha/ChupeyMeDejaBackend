---
id: BE-027
title: Cerrar (cobrar) o descartar un pedido abierto, y liberar la mesa
area: backend
status: done
priority: high
depends_on: [BE-025, BE-026, BE-012, BE-020, BE-022]
created_by: planner
---

## Objetivo

Con BE-025/BE-026, un pedido puede abrirse y acumular productos a lo largo
del tiempo mientras la mesa permanece ocupada. Esta tarea agrega los dos
finales posibles de ese ciclo de vida, pedidos explícitamente por el dueño
del negocio:

1. **Cerrar mesa / Cobrar**: se pide el método de pago, se calcula el total
   final (ya acumulado por BE-026), se registra como venta cobrada
   (`estado: "activa"`), se sincroniza a Google Sheets, y **se libera la
   mesa** — a diferencia del flujo directo existente (`POST /ventas`), que
   deja la mesa `ocupada` hasta que alguien la libera manualmente
   (`POST /mesas/{id}/liberar`) o hasta que se cancela/edita la venta. Esta
   diferencia es intencional: el botón se llama explícitamente "Cerrar
   mesa", que es la acción terminal de todo el ciclo de la mesa (el cliente
   ya pagó y se retira), mientras que en el flujo directo de mostrador no
   hay ninguna señal explícita de que la mesa quedó disponible.
2. **Descartar pedido abierto**: el cliente se fue sin pedir nada, o la
   mesa se abrió por error. Si el pedido no tiene items, se borra sin dejar
   rastro (nunca llegó a sincronizarse a Sheets, nunca fue una venta real).
   Si el pedido tiene items pero nunca se cobró, se conserva para
   auditoría reutilizando el mismo mecanismo de soft-delete que ya existe
   para ventas cobradas y canceladas (BE-020): pasa a `estado: "cancelada"`
   y se sincroniza a Sheets igual que cualquier venta cancelada (para que
   quede visible, ej., "a las 3pm se abrió la mesa 4, se pidió un café, y
   se canceló sin cobrar"). Esto es deliberadamente **distinto** de
   `POST /ventas/{id}/cancelar` (BE-020), que es exclusivamente para
   ventas ya cobradas (`activa -> cancelada`, con la semántica de "esta
   venta sí ocurrió pero se anula"); descartar un pedido abierto nunca pasó
   por `activa`.

## Alcance

**Incluye**, todo en `backend/app/routers/ventas.py` y
`backend/app/schemas/venta.py`:

- Schema nuevo `VentaCerrar`: `metodo_pago: MetodoPago` (obligatorio).
- `POST /ventas/{venta_id}/cerrar`:
  - 404 si `venta_id` no existe.
  - 409 si `venta.estado != ESTADO_ABIERTA` (mensaje claro, ej. "Solo se
    puede cerrar un pedido abierto" — cubre tanto "ya está cobrada" como
    "ya fue descartada/cancelada").
  - 409 si `venta.items` está vacío (mensaje claro, ej. "No se puede cerrar
    un pedido sin productos") — no se puede cobrar una mesa sin nada
    pedido; para ese caso el flujo correcto es descartar, no cerrar.
  - Recalcula `total` sumando `precio_unitario * cantidad` de los items
    actuales de la venta (defensivo, para que el total cobrado sea siempre
    consistente con los items persistidos, mismo criterio de "recalcular
    en servidor, nunca confiar en el cliente" que ya aplican
    `crear_venta`/`actualizar_venta`).
  - `venta.metodo_pago = payload.metodo_pago.value`.
  - `venta.estado = ESTADO_ACTIVA`.
  - Libera la mesa: si `venta.mesa_id is not None`, busca esa `Mesa` (tolera
    que ya no exista, igual que `cancelar_venta` de BE-020) y la marca
    `ESTADO_LIBRE` **incondicionalmente** (el invariante de "máximo una
    venta abierta por mesa", garantizado por BE-025, hace innecesario el
    chequeo de "otra venta activa en la misma mesa" que sí necesita
    `PUT /ventas/{id}` de BE-021 para reasignaciones de mesa).
  - `db.commit()`, `db.refresh(venta)`.
  - Si `config.SHEETS_SYNC_ENABLED`: arma el mismo diccionario plano que ya
    arma `crear_venta`/`cancelar_venta` (reusar
    `_venta_a_dict_para_sheets`) y encola
    `background_tasks.add_task(sync_venta_to_sheets, venta_dict)` — esta es
    la **primera** sincronización de esta venta (nunca se sincronizó
    mientras estuvo `abierta`), así que `_upsert_row_by_id` la insertará
    como fila nueva en Sheets, ya con `estado: "activa"`.
  - Devuelve `VentaOut` (con `estado: "activa"`, `metodo_pago` asignado,
    `total` recalculado).
- `POST /ventas/{venta_id}/descartar`:
  - 404 si `venta_id` no existe.
  - 409 si `venta.estado != ESTADO_ABIERTA` (mensaje claro, ej. "Solo se
    puede descartar un pedido abierto"; no reemplaza ni se confunde con
    `POST /ventas/{id}/cancelar`, que sigue siendo exclusivo de ventas
    `activa`).
  - Libera la mesa igual que `cerrar` (incondicionalmente, mismo
    invariante).
  - Si `venta.items` está vacío: `db.delete(venta)` (hard-delete real, sin
    dejar fila en `ventas` ni en `venta_items`; nunca se sincronizó a
    Sheets así que no hay nada que limpiar ahí tampoco).
  - Si `venta.items` no está vacío: `venta.estado = ESTADO_CANCELADA`
    (soft-delete, igual criterio que BE-020); si
    `config.SHEETS_SYNC_ENABLED`, sincroniza igual que `cancelar_venta`
    (misma construcción de diccionario y `background_tasks.add_task`) para
    que quede el rastro de auditoría en Sheets.
  - `db.commit()`.
  - Devuelve `204 No Content` si se borró (hard-delete, no hay `Venta` que
    serializar), o `200` con `VentaOut` (`estado: "cancelada"`) si se
    conservó — documentar claramente en el docstring del endpoint cuál
    devuelve cada caso, dado que el `response_model` no puede ser el mismo
    para ambas ramas (evaluar `response_model=None` con
    `Response(status_code=...)` manual, o dos rutas — decisión de
    implementación, sin over-engineering).

**No incluye (fuera de alcance):**

- Cambiar `POST /ventas/{id}/cancelar` (BE-020) — sigue siendo exclusivo de
  ventas `activa`; no se le agrega soporte para `abierta`.
- Cambiar `PUT /ventas/{id}` (BE-021) — sigue bloqueando solo `cancelada`;
  no se extiende para bloquear también `abierta` porque un pedido abierto
  nunca debería llegar a ese endpoint (los flujos de edición de un pedido
  abierto son exclusivamente los de BE-026).
- Verificar reportes/margen/Sheets/conteo de mesas de forma integral — eso
  es BE-028 (aunque esta tarea sí dispara la sincronización a Sheets al
  cerrar/descartar-con-items, siguiendo el patrón ya existente).

## Criterios de aceptación

- [ ] `POST /ventas/{id}/cerrar` sobre un pedido `abierta` con items
      responde `200`, con `estado: "activa"`, `metodo_pago` igual al
      enviado, `total` recalculado correctamente sobre los items
      acumulados.
- [ ] `POST /ventas/{id}/cerrar` libera la mesa asociada (`GET /mesas`
      inmediatamente después muestra `estado: "libre"`).
- [ ] `POST /ventas/{id}/cerrar` sobre un pedido sin items responde `409`,
      sin cobrar nada ni tocar la mesa.
- [ ] `POST /ventas/{id}/cerrar` sobre una venta `activa` o `cancelada`
      responde `409`.
- [ ] `POST /ventas/{id}/cerrar` dispara la sincronización a Sheets (con
      `SHEETS_SYNC_ENABLED=true` en un entorno de prueba, o verificado por
      lectura de código que se encola `background_tasks.add_task`), y esa
      es la primera vez que esa venta aparece en la hoja de Sheets (no
      apareció mientras estaba `abierta`).
- [ ] `POST /ventas/{id}/descartar` sobre un pedido `abierta` sin items
      responde `204`, y un `GET /ventas/{id}` posterior responde `404` (la
      fila fue realmente borrada, no soft-deleted).
- [ ] `POST /ventas/{id}/descartar` sobre un pedido `abierta` con items
      responde `200` con `estado: "cancelada"`, y un `GET /ventas/{id}`
      posterior sigue devolviendo la venta (conservada para auditoría).
- [ ] `POST /ventas/{id}/descartar` (con o sin items) libera la mesa
      asociada, verificado con `GET /mesas`.
- [ ] `POST /ventas/{id}/descartar` sobre una venta `activa` o `cancelada`
      responde `409` (no reemplaza a `POST /ventas/{id}/cancelar`).
- [ ] `POST /ventas/{id}/descartar` con items dispara sincronización a
      Sheets (mismo patrón de verificación que `cerrar`).
- [ ] Ambos endpoints con `venta_id` inexistente responden `404`.
- [ ] Ambos endpoints sin header `Authorization` responden `401`.

## Notas de implementación

Implementado tal como está descrito en la tarea, sin desviaciones.

**Archivos tocados:**

- `backend/app/schemas/venta.py`: schema nuevo `VentaCerrar` (`metodo_pago:
  MetodoPago`, obligatorio).
- `backend/app/routers/ventas.py`:
  - `POST /ventas/{venta_id}/cerrar`: 404 si no existe la venta; 409
    (`"Solo se puede cerrar un pedido abierto"`) si `venta.estado !=
    ESTADO_ABIERTA` (cubre tanto `activa` como `cancelada`); 409 (`"No se
    puede cerrar un pedido sin productos"`) si `venta.items` está vacío.
    Recalcula `total` en servidor sumando `precio_unitario * cantidad` de
    los items actuales (defensivo, nunca confía en un total no persistido
    porque este endpoint no recibe ninguno del cliente). Asigna
    `venta.metodo_pago` y `venta.estado = ESTADO_ACTIVA`. Libera la mesa
    **incondicionalmente** si `venta.mesa_id is not None` (tolera que ya no
    exista, igual que `cancelar_venta` de BE-020) — sin el chequeo de
    "otra venta activa en la misma mesa" de `PUT /ventas/{id}` (BE-021),
    porque el invariante de BE-025 ("máximo una venta `abierta` por mesa")
    lo hace innecesario aquí, tal como especifica el alcance. Si
    `config.SHEETS_SYNC_ENABLED`: arma el diccionario con
    `_venta_a_dict_para_sheets` (reutilizada, sin duplicar) y encola
    `background_tasks.add_task(sync_venta_to_sheets, venta_dict)` — es la
    primera sincronización de esa venta.
  - `POST /ventas/{venta_id}/descartar` (`response_model=None`, ya que las
    dos ramas devuelven cosas distintas — documentado en el docstring del
    endpoint): 404 si no existe la venta; 409 (`"Solo se puede descartar un
    pedido abierto"`) si `venta.estado != ESTADO_ABIERTA` (no reemplaza a
    `POST /ventas/{id}/cancelar` de BE-020, que sigue siendo exclusivo de
    ventas `activa`). Libera la mesa incondicionalmente, igual que
    `cerrar`. Si `venta.items` está vacío: `db.delete(venta)` (hard-delete
    real, aprovechando el `cascade="all, delete-orphan"` para que también
    se borren sus `VentaItem` — aunque en este caso no hay ninguno) y
    devuelve `Response(status_code=204)` sin cuerpo — nunca se sincronizó a
    Sheets, así que no hay nada que limpiar ahí. Si tiene items: pasa a
    `ESTADO_CANCELADA` (mismo criterio de soft-delete que BE-020), y si
    `SHEETS_SYNC_ENABLED` sincroniza igual que `cancelar_venta` (mismo
    patrón de armado de diccionario y `background_tasks.add_task`);
    devuelve `200` con `VentaOut.model_validate(venta)` (construido
    explícitamente porque `response_model=None` no serializa
    automáticamente el ORM object).

**No se tocó** `POST /ventas/{id}/cancelar` (BE-020) ni `PUT /ventas/{id}`
(BE-021) — ninguno de los dos fue extendido para tratar `abierta`, tal como
especifica el alcance.

**Cómo se probó:** mismo servidor `uvicorn` temporal en el puerto `8199`
(scratchpad, SQLite propia, `SHEETS_SYNC_ENABLED=false`) reutilizado de la
sesión de BE-025/BE-026, con el mismo script Python (`requests`)
encadenado. Casos verificados, todos exitosos:

- Cerrar un pedido abierto con items (`total` acumulado `18000`) con
  `{"metodo_pago": "transferencia"}` -> `200`, `estado: "activa"`,
  `metodo_pago: "transferencia"`, `total: 18000` (recalculado en servidor a
  partir de los items persistidos). `GET /mesas` inmediatamente después
  confirma la mesa `libre`.
- `GET /reportes/hoy` antes y después de cerrar: el total aumentó
  exactamente en `18000` (la venta abierta no se contaba mientras estuvo
  abierta; al cerrarse sí se sumó) — mismo patrón verificado también en
  `GET /reportes/mensual` (total, num_ventas, ticket_promedio, ytd_total)
  en la sesión de pruebas de BE-028 (ver esa tarea).
- Cerrar de nuevo esa misma venta (ya `activa`) -> `409`. Cerrar
  `venta_id` inexistente -> `404`. Abrir un pedido vacío (sin items) e
  intentar cerrarlo -> `409` (`"No se puede cerrar un pedido sin
  productos"`), sin cobrar nada ni tocar la mesa.
- Descartar un pedido abierto **sin** items -> `204`, y `GET
  /ventas/{id}` posterior -> `404` (fila realmente borrada, no
  soft-deleted); `GET /mesas` confirma la mesa liberada.
- Abrir un pedido nuevo, agregarle 1 item, y descartarlo -> `200`,
  `estado: "cancelada"`; `GET /ventas/{id}` posterior sigue devolviendo la
  venta (conservada); `GET /mesas` confirma la mesa liberada; `GET
  /reportes/hoy` no cambió (la venta cancelada no se cuenta, igual que
  cualquier otra cancelada desde BE-023).
- Descartar sobre una venta `activa` -> `409`; descartar esa misma venta ya
  `cancelada` de nuevo -> `409`; descartar `venta_id` inexistente -> `404`.
- Ambos endpoints (`cerrar`/`descartar`/`items`/`DELETE items`) sin header
  `Authorization` -> `401` en los 4.
- Verificado por lectura de código (no solo funcionalmente) que
  `cerrar_venta` y `descartar_venta` (rama con items) son, junto con
  `crear_venta`, `actualizar_venta` y `cancelar_venta`, las **únicas** 5
  invocaciones de `sync_venta_to_sheets` en `ventas.py` — la rama de
  hard-delete de `descartar` no invoca nada (nunca se sincronizó a
  Sheets).

Servidor y bases de datos temporales detenidos/eliminados del scratchpad de
la sesión al finalizar (`netstat` confirmó sin listeners activos en los
puertos de prueba); no se tocó `backend/chupeymedeja.db` real en ningún
momento (confirmado con `git status`).

## Revisión

**Veredicto: `done`**

Flujo completo verificado end-to-end (servidor `uvicorn` propio en puerto
8300, SQLite temporal, `SHEETS_SYNC_ENABLED=false`, nunca se tocó
`backend/chupeymedeja.db`):

- Abrir mesa -> agregar 2 cafés + 1 postre + 1 jugo -> quitar jugo (total
  `18000`) -> `POST /ventas/{id}/cerrar {"metodo_pago":"efectivo"}` ->
  `200`, `estado: "activa"`, `total: 18000` recalculado correctamente,
  `metodo_pago` asignado; `GET /mesas` confirma la mesa `libre` de
  inmediato. Repetir `cerrar` -> `409`.
- Cerrar un pedido sin items -> `409` ("No se puede cerrar un pedido sin
  productos"), sin tocar la mesa.
- Descartar sin items -> `204`; `GET /ventas/{id}` posterior -> `404`
  (hard-delete real). Mesa liberada.
- Descartar con items -> `200`, `estado: "cancelada"`; `GET /ventas/{id}`
  posterior sigue devolviendo la venta (conservada). Mesa liberada.
- `GET /reportes/hoy` y `/reportes/mensual` (`total`, `num_ventas`,
  `ytd_total`) confirmados con aritmética exacta: sin cambio mientras el
  pedido estuvo `abierta`, +18000 exactos tras `cerrar`.
- Ambos endpoints sin `Authorization` -> `401`; `venta_id` inexistente ->
  `404` en ambos.
- El código de `cerrar_venta`/`descartar_venta` coincide exactamente con
  lo documentado (liberación incondicional de mesa, reutilización de
  `_venta_a_dict_para_sheets`, `response_model=None` con
  `Response(204)`/`VentaOut.model_validate` documentado en el docstring).

Sin hallazgos.
