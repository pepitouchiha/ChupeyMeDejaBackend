---
id: BE-028
title: Verificar que un pedido "abierta" no se cuente como venta real en reportes, Sheets y bloqueo de borrado de mesas
area: backend
status: done
priority: high
depends_on: [BE-025, BE-007, BE-023, BE-012, BE-022]
created_by: planner
---

## Objetivo

BE-025 introdujo el estado `abierta` bajo la premisa de que los filtros
existentes de reportes (`Venta.estado == ESTADO_ACTIVA`, BE-007/BE-023) ya
excluyen automáticamente cualquier estado que no sea `activa`, sin
necesidad de tocar código. Esta tarea existe para **verificar esa premisa
de forma explícita y end-to-end** (no darla por sentada) en cada lugar del
backend que consulta `Venta`, y corregir cualquier lugar donde no se
cumpla. Es deliberadamente una tarea de verificación/ajuste puntual, no de
reescritura — si todo ya filtra correctamente, el resultado esperado es
"sin cambios de código, solo evidencia de la verificación" en la mayoría de
los puntos.

## Alcance

**Incluye**, revisar y, solo si hace falta, ajustar:

- `backend/app/routers/reportes.py`: confirmar con un caso numérico real
  (crear una venta `abierta` con items de valor conocido, sin cerrarla) que
  `/reportes/hoy` y `/reportes/mensual` (total, num_ventas,
  ticket_promedio, por_hora, margen, margen_incompleto, ytd_total,
  ytd_margen) **no** cambian al crear esa venta abierta, y que si se cierra
  después, recién ahí los totales la reflejan.
- `backend/app/routers/mesas.py`, función `_contar_ventas` (usada por
  `DELETE /mesas/{id}` para bloquear el borrado de una mesa con ventas
  asociadas): hoy cuenta **todas** las ventas de una mesa sin filtrar por
  `estado`. Decisión de producto (documentar, no asumir en silencio): una
  venta `abierta` en una mesa **sí** debe seguir bloqueando el borrado de
  esa mesa (no tiene sentido permitir borrar una mesa con un pedido en
  curso), así que `_contar_ventas` **no** necesita cambiar — verificar esto
  explícitamente con un caso de prueba (crear mesa, abrir pedido, intentar
  `DELETE /mesas/{id}` -> debe seguir respondiendo `409`), en vez de
  asumirlo.
- `backend/app/services/sheets_service.py` y los tres puntos donde se
  invoca `sync_venta_to_sheets` (`crear_venta`, `cerrar` de BE-027,
  `descartar` de BE-027 cuando hay items, `cancelar_venta`,
  `actualizar_venta`): confirmar por lectura de código que **ningún** punto
  del flujo de BE-025/BE-026 (abrir pedido, agregar items, quitar items)
  encola `sync_venta_to_sheets` — un pedido abierto nunca debe aparecer en
  la hoja de Sheets hasta que se cierre o se descarte-con-items.
- `GET /ventas` (listado general, sin filtro `estado`): documentar
  explícitamente (para que lo tengan en cuenta FE-036 y cualquier otra
  pantalla que ya consuma este endpoint sin filtrar, ej. el feed de
  "ventas recientes" del Dashboard de FE-011) que a partir de BE-025 este
  endpoint puede devolver ventas en los **tres** estados mezclados
  (`activa`, `cancelada`, `abierta`) cuando no se pasa `estado` — sin
  cambiar el comportamiento del endpoint (ya documentado así desde BE-020,
  ahora con un tercer valor posible), pero dejando constancia explícita en
  esta tarea de qué pantallas del frontend consumen `GET /ventas` sin
  filtro y necesitan decidir si excluyen `abierta` de su propia vista (no
  es responsabilidad del backend decidir por ellas).

**No incluye (fuera de alcance):**

- Cambiar el contrato de `GET /ventas` para excluir `abierta` por defecto
  (mantiene el mismo comportamiento de "sin filtro, mezcla todo" definido
  desde BE-020) — si el negocio decide después que el default debería
  excluir `abierta`, es una tarea nueva del planner, no se improvisa aquí.
- Cualquier endpoint nuevo — esta tarea es puramente de verificación/ajuste
  quirúrgico sobre código ya existente.

## Criterios de aceptación

- [ ] Caso numérico concreto: crear 1 venta activa (total conocido) + 1
      venta abierta con items de valor conocido (sin cerrar) el mismo día
      -> `GET /reportes/hoy` refleja únicamente el total de la venta activa
      (no suma nada de la abierta).
- [ ] Cerrar esa venta abierta (`POST /ventas/{id}/cerrar` de BE-027) y
      volver a pedir `/reportes/hoy` -> ahora sí incluye su total, sumado
      al de la venta activa original.
- [ ] Mismo patrón verificado en `/reportes/mensual` (total, num_ventas,
      ticket_promedio) y en `ytd_total`/`ytd_margen`.
- [ ] Margen: una venta abierta cuyos items usan un producto con `costo`
      definido no aporta ni resta nada a `margen`/`margen_incompleto` de
      `/reportes/hoy` ni `/reportes/mensual` mientras siga abierta.
- [ ] `DELETE /mesas/{id}` sobre una mesa con una venta `abierta` asociada
      responde `409` (no permite borrar la mesa), verificado explícitamente
      con un caso de prueba real, no solo por lectura de código.
- [ ] Verificado por lectura de código que `POST /ventas/abrir`,
      `POST /ventas/{id}/items` y `DELETE /ventas/{id}/items/{item_id}`
      (BE-025/BE-026) no invocan `sync_venta_to_sheets` en ningún punto.
- [ ] Documentado en notas de implementación qué pantallas/consumidores
      del frontend usan `GET /ventas` sin filtro `estado` hoy (para que
      FE-036 las revise), a partir de una búsqueda real en el código del
      frontend (no una suposición).
- [ ] Si se encuentra algún punto que sí trata `abierta` incorrectamente
      (ej. algún filtro que use `!= ESTADO_CANCELADA` en vez de `==
      ESTADO_ACTIVA`), corregirlo aquí mismo y documentar qué archivo/línea
      se ajustó y por qué.
- [ ] `GET /reportes/hoy`, `GET /reportes/mensual` y `DELETE /mesas/{id}`
      sin header `Authorization` siguen respondiendo `401` (sin
      regresión).

## Notas de implementación

Tarea de verificación: se leyó completo `backend/app/routers/reportes.py`,
`backend/app/routers/mesas.py` y `backend/app/services/sheets_service.py`,
y se reprodujo cada criterio con un servidor `uvicorn` real (no solo por
lectura de código). **No hizo falta ningún cambio de código** — la premisa
de BE-025 se confirmó correcta en los tres puntos revisados:

1. **`backend/app/routers/reportes.py`:** tanto `reporte_hoy` como
   `reporte_mensual` (incluida `_margen_query`/`_calcular_margen`/
   `_margen_por_mes`, y el cálculo de `ytd_total`) filtran explícitamente
   `Venta.estado == ESTADO_ACTIVA` (no `!= ESTADO_CANCELADA`), heredado tal
   cual de BE-007/BE-023 — un tercer estado (`abierta`) queda excluido
   automáticamente sin ningún ajuste. **Verificado con un caso numérico
   real** (servidor temporal, puerto 8199, scratchpad): se le dio `costo`
   a un producto, se abrió un pedido (`POST /ventas/abrir`) en una mesa
   nueva y se le agregó ese producto (`POST /ventas/{id}/items`) — `GET
   /reportes/hoy` y `GET /reportes/mensual` (`total`, `num_ventas`,
   `ticket_promedio`, `ytd_total`, `margen`, `margen_incompleto`) no
   cambiaron mientras el pedido siguió `abierta` (comparado antes/después
   del `POST /ventas/{id}/items`, mismos valores exactos). Al cerrarlo
   (`POST /ventas/{id}/cerrar`), los mismos endpoints reflejaron el total y
   el margen de esa venta sumados a los valores previos (verificado con
   aritmética exacta, no solo "cambió"): `/reportes/hoy` total +6000 (precio
   del item); `/reportes/mensual` total/num_ventas/ticket_promedio y
   `ytd_total` consistentes con la suma esperada; margen pasó de `9000` a
   `13000` (+4000 = (6000 precio - 2000 costo) × 1 unidad) tanto en
   `/reportes/hoy` como reflejado en `/reportes/mensual`.
2. **`backend/app/routers/mesas.py`, `_contar_ventas`:** confirmado por
   lectura que cuenta **todas** las ventas de una mesa sin filtrar por
   `estado` (`Venta.mesa_id == mesa_id`, sin más condición). **Decisión de
   producto explícita (no un descuido):** esto es correcto tal cual está —
   una venta `abierta` en una mesa debe seguir bloqueando `DELETE
   /mesas/{id}` (no tiene sentido de negocio borrar una mesa con un pedido
   en curso), así que **no se modificó** `_contar_ventas`. Verificado con
   un caso de prueba real: mesa nueva, `POST /ventas/abrir` sobre ella,
   `DELETE /mesas/{id}` -> `409` (igual que con una venta `activa`).
3. **`backend/app/services/sheets_service.py` / puntos de invocación de
   `sync_venta_to_sheets` en `ventas.py`:** confirmado por lectura de
   código (`grep sync_venta_to_sheets backend/app/routers/ventas.py`) que
   las **únicas 5** invocaciones son `crear_venta`, `actualizar_venta`,
   `cancelar_venta`, `cerrar_venta` (BE-027) y `descartar_venta` cuando
   tiene items (BE-027) — ninguna de las tres funciones de BE-025/BE-026
   (`abrir_venta`, `agregar_items_venta`, `quitar_item_venta`) la invoca en
   ningún punto. Un pedido abierto (o al que se le agregan/quitan items)
   nunca toca Sheets hasta que se cierra o se descarta-con-items.
4. **`GET /ventas` sin filtro `estado`:** documentado, sin cambiar el
   contrato (fuera de alcance): a partir de esta tarea puede devolver los
   **tres** estados mezclados. Búsqueda real en el código del frontend
   (`grep` sobre `frontend/src`), no una suposición:
   - `frontend/src/composables/useVentas.ts` -> `frontend/src/api/ventas.ts`
     (`listVentas`) es el único wrapper de `GET /ventas` del frontend.
   - `frontend/src/views/DashboardView.vue` (línea 19/25): llama
     `loadVentas()` **sin ningún filtro** (`useVentas().load({})`) para el
     feed de "ventas recientes" del Dashboard (FE-011/FE-008) — a partir de
     BE-025 esta tabla mezclará ventas `abierta` con `activa`/`cancelada`
     si no se ajusta. Existe ya `frontend/tasks/FE-036-excluir-abierta-
     ordenes-dashboard.md` (creada por el planner) que cubre este caso
     puntual — se deja constancia aquí para que ese ticket lo confirme,
     sin tocarlo desde backend.
   - `frontend/src/views/OrdenesView.vue` (líneas 35/58): tiene un filtro
     `estadoFiltro` con opciones, pero su valor por defecto es `''` (sin
     filtro), por lo que la carga inicial de la pantalla de Órdenes
     (FE-028) también mezcla los tres estados hasta que el usuario elija un
     filtro explícito — mismo caso a tener en cuenta por el frontend
     (fuera del alcance de esta tarea de backend decidir su UI).
   - No se encontraron otros consumidores de `GET /ventas` sin filtro en el
     frontend además de estos dos.
5. **Ningún punto incorrecto encontrado:** no había ningún filtro usando
   `!= ESTADO_CANCELADA` en vez de `== ESTADO_ACTIVA` en todo el código
   revisado (`reportes.py`, `mesas.py`, `ventas.py`) — no hizo falta
   ninguna corrección quirúrgica.

**Verificado (sin regresión):** `GET /reportes/hoy`, `GET
/reportes/mensual` y `DELETE /mesas/{id}` sin header `Authorization`
responden `401`.

**Cómo se probó:** mismo servidor `uvicorn` temporal (puerto `8199`,
SQLite propia en el scratchpad de la sesión, `SHEETS_SYNC_ENABLED=false`)
reutilizado de BE-025/BE-026/BE-027, con `curl` para los casos numéricos de
reportes/mesas descritos arriba. Servidor y base de datos temporal
detenidos/eliminados al finalizar; no se tocó `backend/brainfreeze.db`
real (confirmado con `git status`, sin cambios en ese archivo).

## Revisión

**Veredicto: `done`**

Re-verificado con caso numérico propio (servidor `uvicorn` en puerto 8300,
SQLite temporal): venta activa (`total` conocido) + venta abierta con
items (total `18000`, sin cerrar) el mismo día -> `/reportes/hoy` y
`/reportes/mensual` (`total`, `num_ventas`, `ytd_total`) no cambiaron
mientras el pedido siguió `abierta`; al cerrarlo, ambos reflejaron
exactamente `+18000`. `DELETE /mesas/{id}` sobre una mesa con una venta
`abierta` -> `409`, confirmado. Lectura de código de
`reportes.py`/`mesas.py`/`ventas.py` confirma que el filtro
`Venta.estado == ESTADO_ACTIVA` (no `!= ESTADO_CANCELADA`) es consistente
en todos los cálculos agregados, y que ninguna de las funciones de
BE-025/BE-026 invoca `sync_venta_to_sheets`. La lista de consumidores de
`GET /ventas` sin filtro documentada (`DashboardView.vue`,
`OrdenesView.vue`) coincide con lo que confirmé independientemente vía
`grep` sobre `frontend/src`, y corresponde exactamente a lo que
FE-036 efectivamente ajustó.

Sin hallazgos.
