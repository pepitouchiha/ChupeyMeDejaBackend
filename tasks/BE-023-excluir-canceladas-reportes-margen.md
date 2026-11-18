---
id: BE-023
title: Excluir ventas canceladas de /reportes/hoy, /reportes/mensual y del cálculo de margen
area: backend
status: done
priority: high
depends_on: [BE-007, BE-018, BE-020]
created_by: planner
---

## Objetivo

Con BE-020, una `Venta` puede quedar marcada `cancelada` mediante soft-delete
pero sigue existiendo en la tabla `ventas`. Sin esta tarea, una venta
cancelada seguiría sumando en `/reportes/hoy`, `/reportes/mensual` (total,
num_ventas, ticket_promedio, ytd_total) y en el margen (`/reportes/hoy` y
`/reportes/mensual`, BE-018) exactamente igual que una venta activa — lo
cual es incorrecto: el dueño canceló esa orden precisamente porque no debe
contar como venta real. Esta tarea excluye las ventas `cancelada` de todos
los cálculos agregados de reportes, sin tocar `GET /ventas` (que sí debe
seguir devolviendo canceladas cuando no se filtra por `estado`, según
BE-020 — ese endpoint es para gestión/historial, no para reportes).

## Alcance

**Incluye**, todo en `backend/app/routers/reportes.py`:

- `reporte_hoy`: la query que trae `ventas = db.query(Venta)...` (líneas
  ~92-97) debe agregar `.filter(Venta.estado == ESTADO_ACTIVA)` (importar
  `ESTADO_ACTIVA` de `app.models.venta`), de modo que `total`, `num_ventas`
  y cada bucket de `por_hora` solo consideren ventas activas.
- `reporte_mensual`: la query de `filas` (agregación por mes de
  `total`/`num_ventas`, líneas ~129-139) debe agregar el mismo
  `.filter(Venta.estado == ESTADO_ACTIVA)`. La query de `ytd_total` (líneas
  ~161-165) también.
- `_margen_query`: agregar el mismo filtro sobre `Venta.estado ==
  ESTADO_ACTIVA` (el `join` ya existente con `Venta` permite agregar el
  filtro directamente ahí, junto al filtro de fecha que ya aplican
  `_calcular_margen`/`_margen_por_mes` — no hace falta un `join` nuevo,
  ambos filtros conviven sobre la misma tabla `Venta` ya unida). Esto cubre
  automáticamente `margen`/`margen_incompleto` de `/hoy`, `margen` por mes
  en `/mensual`, y `ytd_margen`/`ytd_margen_incompleto` (todos reusan
  `_margen_query`).
- Actualizar el comentario a nivel de módulo que ya documenta la limitación
  de "costo actual vs. histórico" (líneas ~19-24) para mencionar también,
  brevemente, que las ventas canceladas quedan excluidas de todos estos
  cálculos.

**No incluye (fuera de alcance):**

- `GET /reportes/alertas-stock` (no tiene relación con `Venta`).
- Cambiar `GET /ventas` (BE-020 ya define su comportamiento: sin filtro
  `estado`, mezcla activas y canceladas; con filtro, respeta lo pedido).
- Cambiar `_contar_ventas` de `backend/app/routers/mesas.py` (fuera de
  alcance también en BE-020, ver nota ahí).
- Cualquier endpoint nuevo de "ventas canceladas" como métrica separada
  (ej. "cuánto se canceló este mes") — no está pedido; si se necesita, es
  una tarea nueva del planner.

## Criterios de aceptación

- [ ] Crear 2 ventas activas + 1 venta cancelada el mismo día: `GET
      /reportes/hoy` refleja `total`/`num_ventas`/`por_hora` calculados
      **solo** sobre las 2 activas (verificado con un caso numérico
      concreto, no solo por lectura de código).
- [ ] Mismo escenario a nivel mensual: `GET /reportes/mensual` excluye la
      venta cancelada del mes correspondiente (`total`, `num_ventas`,
      `ticket_promedio`) y de `ytd_total` si cae en el año en curso.
- [ ] Margen: una venta cancelada cuyos items tienen `costo` definido no
      debe sumar ni restar nada al `margen`/`margen_incompleto` de
      `/reportes/hoy` ni `/reportes/mensual` (se excluye por completo, no
      se trata como si tuviera costo 0 ni dispara `margen_incompleto` por
      el solo hecho de estar cancelada).
- [ ] `ytd_margen`/`ytd_margen_incompleto` igualmente excluyen ventas
      canceladas, verificado con un caso numérico concreto (mismo nivel de
      verificación que ya hizo BE-018 para `ytd_total`).
- [ ] Cancelar una venta que ya estaba siendo contada en un reporte, y
      volver a pedir el reporte, refleja el cambio inmediatamente (la
      venta desaparece de los totales) sin necesidad de reiniciar el
      servidor ni limpiar ningún caché.
- [ ] Una venta activa (no cancelada) se sigue contando exactamente igual
      que antes de esta tarea — sin regresión en los números para el caso
      sin ventas canceladas de por medio.
- [ ] `GET /reportes/alertas-stock` no fue modificado ni se ve afectado.
- [ ] Verificado por lectura de código que el filtro nuevo no introduce
      N+1 (es un `.filter()` adicional sobre queries ya agregadas
      existentes, sin loops de Python nuevos).
- [ ] `GET /reportes/hoy` y `GET /reportes/mensual` sin header
      `Authorization` siguen devolviendo `401` (sin regresión).

## Notas de implementación

Implementado tal como está descrito en la tarea, sin desviaciones. Único
archivo tocado: `backend/app/routers/reportes.py`.

- Import agregado: `from app.models.venta import ESTADO_ACTIVA, Venta,
  VentaItem` (antes solo importaba `Venta, VentaItem`).
- `_margen_query`: agregado `.filter(Venta.estado == ESTADO_ACTIVA)`
  directamente sobre el `join` ya existente con `Venta` (sin `join` nuevo).
  Esto cubre automáticamente `margen`/`margen_incompleto` de `/hoy`, margen
  por mes de `/mensual` (vía `_margen_por_mes`) y `ytd_margen`/
  `ytd_margen_incompleto` (vía `_calcular_margen`), porque las tres
  reutilizan `_margen_query`.
- `reporte_hoy`: agregado `.filter(Venta.estado == ESTADO_ACTIVA)` a la
  query de `ventas` (además de los filtros de fecha ya existentes), de modo
  que `total`, `num_ventas` y cada bucket de `por_hora` solo consideran
  ventas activas.
- `reporte_mensual`: agregado el mismo filtro a la query de `filas`
  (agregación por mes de `total`/`num_ventas`) y a la query de `ytd_total`.
- Comentario a nivel de módulo (el que ya documentaba la limitación de
  "costo actual vs. histórico" de BE-018) extendido con una nota nueva
  (BE-023) que menciona explícitamente la exclusión de ventas canceladas.
- No se tocó `GET /ventas` ni `_contar_ventas` de `mesas.py` (fuera de
  alcance, como especifica la tarea) ni `/reportes/alertas-stock` (no tiene
  relación con `Venta`, no se modificó).
- Verificado por lectura de código que el filtro nuevo no introduce N+1: es
  un `.filter()` adicional encadenado sobre queries ya agregadas
  (`func.sum`/`func.count`/`func.coalesce`) que ya existían, sin ningún
  loop de Python nuevo agregado por esta tarea (los loops de Python
  preexistentes, como el `for venta in ventas` de `reporte_hoy` que arma
  `por_hora`, ya operan sobre la lista ya filtrada por SQL, sin cambios en
  esa parte).

**Cómo se probó:** end-to-end contra el servidor real (`uvicorn`, misma
SQLite temporal de BE-020/021/022, `SHEETS_SYNC_ENABLED=false`), con casos
numéricos concretos, no solo por lectura de código:

1. Estado de partida (arrastrado de las pruebas de BE-020/021/022, todas
   creadas "hoy"): 2 ventas activas (`id=3` total `22000`, `id=4` total
   `24000`) y 3 canceladas (`id=1,2,5`, totales `16000`/`8000`/`19000`).
   `GET /reportes/hoy` ya mostraba `total: 46000`, `num_ventas: 2` — **sin
   contar ninguna de las 3 canceladas**, confirmando el filtro sobre datos
   reales previos a esta tarea.
2. Seteado `costo` en los dos productos usados (`Producto 1: costo=5000`,
   `Producto 2: costo=1000`) vía `PATCH /productos/{id}`. `GET
   /reportes/hoy` pasó a `margen: 20000, margen_incompleto: false`
   (calculado a mano: venta 3 -> `(9500-5000)*2 + (3000-1000)*1 = 11000`;
   venta 4 -> `(8000-5000)*3 = 9000`; total `20000`; los items de las 3
   ventas canceladas, aunque usan el mismo producto con costo ya definido,
   no suman ni restan nada porque se excluyen por completo, no por
   `costo=0`) — coincide exactamente.
3. Creadas 2 ventas activas nuevas, ambas `producto_id=1, cantidad=1`
   (precio vigente `9500`, margen `4500` c/u): `id=6` y `id=7`. `GET
   /reportes/hoy` antes de cancelar ninguna -> `total: 65000, num_ventas:
   4, margen: 29000` (20000 + 4500 + 4500), coincide.
4. `POST /ventas/7/cancelar` -> `200`. `GET /reportes/hoy` inmediatamente
   después (mismo proceso, sin reiniciar servidor) -> `total: 55500,
   num_ventas: 3, margen: 24500` (20000 + 4500 de la venta 6 que sigue
   activa) — la venta 7 desapareció de los totales al instante, sin
   necesidad de reiniciar el servidor ni limpiar caché.
5. `GET /reportes/mensual?meses=1` en ese mismo estado: mes actual con
   `total: 55500, num_ventas: 3, ticket_promedio: 18500.0, margen: 24500,
   margen_incompleto: false`, y `ytd_total: 55500, ytd_margen: 24500,
   ytd_margen_incompleto: false` (todas las ventas son de hoy, caen en el
   año en curso) — coincide exactamente con los mismos números de `/hoy`,
   confirmando exclusión consistente en ambos endpoints y en `ytd_*`.
6. `GET /reportes/alertas-stock` -> `200`, respuesta sin cambios (no
   relacionado con `Venta`, no afectado).
7. `GET /reportes/hoy` y `GET /reportes/mensual` sin header
   `Authorization` -> `401` en ambos (sin regresión).

Servidor y base de datos temporal detenidos/eliminados al finalizar toda la
verificación de las 4 tareas (BE-020 a BE-023); no se dejó ningún proceso
`uvicorn` corriendo ni artefactos fuera del scratchpad de la sesión, y la
`brainfreeze.db` real del repo no fue tocada en ningún momento (confirmado
con `git status`, sin cambios fuera de los archivos de código/tareas
listados arriba).

## Revisión

**Veredicto: `done`.**

Revisé `backend/app/routers/reportes.py` completo. Reproduje
independientemente (SQLite temporal propia, servidor real) el caso
numérico central: creé 2 productos con `costo` definido, 2 mesas, y en la
misma sesión probé el flujo completo de BE-020/BE-021 (cancelar/editar) y
luego pedí los reportes:

- `GET /reportes/hoy` reflejó **solo** la venta activa que quedó viva tras
  cancelar la otra (`total`, `num_ventas`, `margen` consistentes con el
  cálculo manual sobre esa única venta activa), la venta cancelada
  desapareció de los totales sin reiniciar el servidor.
- `GET /reportes/mensual?meses=1`: mismo total/margen que `/hoy` para el
  mes en curso, y `ytd_total`/`ytd_margen` coincidentes (todas las ventas
  de la sesión son "de hoy").
- `GET /reportes/alertas-stock` no fue tocado ni afectado (confirmado por
  lectura de código, sin relación con `Venta`).
- `401` sin `Authorization` en `/reportes/hoy` y `/reportes/mensual`, sin
  regresión.
- Por lectura de código: el filtro `Venta.estado == ESTADO_ACTIVA` se
  agrega directamente sobre queries agregadas ya existentes
  (`_margen_query`, la query de `ventas` de `/hoy`, la de `filas` y
  `ytd_total` de `/mensual`) — no introduce ningún loop de Python nuevo ni
  N+1.
- El comentario a nivel de módulo documenta correctamente la exclusión de
  canceladas junto a la limitación preexistente de BE-018 (costo actual
  vs. histórico).

No se encontraron hallazgos bloqueantes.
