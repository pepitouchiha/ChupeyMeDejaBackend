---
id: BE-022
title: Reflejar cancelación y edición de ventas en Google Sheets (upsert por ID, no solo-append)
area: backend
status: done
priority: medium
depends_on: [BE-012, BE-020, BE-021]
created_by: planner
---

## Objetivo

BE-012 documentó explícitamente en `sheets_service.py` que la hoja `Ventas`
("`Ventas_Diarias`") es "un log de solo-append (una fila nueva por cada
venta, nunca se sobrescribe una fila existente)", a diferencia de
Categorías/Productos/Insumos, que sí se actualizan in place por ID
(`_upsert_row_by_id`). Con BE-020/BE-021 una venta ya puede cambiar de
estado (cancelada) o de contenido (items/mesa/método de pago/total editados)
**después** de creada — ese supuesto de "solo-append" ya no es correcto.
Esta tarea cambia la sincronización de ventas para que se comporte como el
resto de entidades: una fila por venta, identificada por `ID Venta`,
actualizada in place cuando la venta se edita o se cancela — nunca se borra
la fila (soft-delete también en el backup, consistente con la decisión de
soft-delete en SQLite).

## Alcance

**Incluye:**

- `backend/app/services/sheets_service.py`:
  - Actualizar el docstring del módulo: ya no describir a `Ventas` como
    "log de solo-append"; documentar que ahora usa el mismo mecanismo de
    upsert-por-ID que Categorías/Productos/Insumos, porque una venta puede
    cambiar de estado o de contenido después de creada.
  - `_HEADERS_VENTAS`: agregar `"Estado"` al final de la lista (después de
    `"Productos"`).
  - `sync_venta_to_sheets(venta: dict[str, Any])`:
    - Agregar el valor de `venta.get("estado")` como última columna de
      `row_values`.
    - Reemplazar el `worksheet.append_row(row_values)` directo por
      `_upsert_row_by_id(worksheet, _HEADERS_VENTAS, venta.get("id"),
      row_values)` (misma función ya usada por
      `sync_categoria_to_sheets`/`sync_producto_to_sheets`/
      `sync_insumo_to_sheets`) — esto ya cubre ambos casos sin lógica
      nueva: si la venta es nueva (`id` no encontrado en la columna A),
      `_upsert_row_by_id` hace `append_row`; si ya existe (venta editada o
      cancelada), actualiza esa misma fila in place.
- `backend/app/routers/ventas.py`:
  - `crear_venta`: agregar `"estado": venta.estado` al diccionario que ya
    arma para `sync_venta_to_sheets` (hoy no lo incluye porque `estado` no
    existía antes de BE-020).
  - `cancelar_venta` (endpoint de BE-020): agregar `background_tasks:
    BackgroundTasks` a su firma; si `config.SHEETS_SYNC_ENABLED`, armar el
    mismo tipo de diccionario plano que ya arma `crear_venta` (id,
    creado_en, metodo_pago, mesa_id, total, estado, items resumidos con
    nombre de producto resuelto — reutilizar el mismo patrón, evaluando si
    conviene extraer un helper común `_venta_a_dict_para_sheets(venta,
    productos_por_id)` para no duplicar esa construcción entre
    `crear_venta`, `cancelar_venta` y `actualizar_venta`) y encolar
    `background_tasks.add_task(sync_venta_to_sheets, venta_dict)`.
  - `actualizar_venta` (endpoint `PUT /ventas/{id}` de BE-021): mismo
    tratamiento — agregar `background_tasks: BackgroundTasks`, construir el
    diccionario con los items/total/estado ya actualizados, y encolar la
    sincronización si `SHEETS_SYNC_ENABLED`.
  - Con `SHEETS_SYNC_ENABLED=false` (default), ninguno de los 3 endpoints
    debe evaluar la rama de armar el diccionario ni encolar la tarea —
    mismo criterio ya establecido por BE-012.

**No incluye (fuera de alcance):**

- Cambiar el formato de `items_resumen` (sigue siendo el mismo string
  `"Producto xN ($precio)"` unido por `"; "` que ya arma
  `sync_venta_to_sheets`).
- Cambiar `_upsert_row_by_id` ni el mecanismo de `_ensure_headers`/caché de
  worksheet — se reutilizan tal cual.
- Sincronización retroactiva de ventas ya existentes en la hoja de Sheets
  desde antes de esta tarea (mismo criterio que BE-012 dejó para la
  migración inicial).
- Probar contra un Google Sheet real (el usuario sigue sin
  `credentials.json` real según el estado documentado en BE-012/BE-019 —
  verificar el estado actual antes de asumir; si para cuando se implemente
  esta tarea el usuario ya completó el setup real de BE-019, sí debe
  probarse end-to-end contra el spreadsheet real y documentarlo).

## Criterios de aceptación

- [ ] El docstring de `sheets_service.py` ya no afirma que `Ventas` es
      "solo-append"; describe el mecanismo de upsert-por-ID y por qué
      cambió (ventas editables/cancelables).
- [ ] `_HEADERS_VENTAS` termina en `"Estado"`.
- [ ] Con `gspread` mockeado (sin red real): sincronizar una venta **nueva**
      (su `id` no está todavía en la columna A de la hoja simulada) invoca
      `append_row` (vía el fallback de `_upsert_row_by_id`), igual
      comportamiento visible que antes de esta tarea para altas nuevas.
- [ ] Con `gspread` mockeado: sincronizar una venta **cancelada** cuyo `id`
      ya existe en la hoja simulada invoca `worksheet.update(...)` sobre la
      fila encontrada (no `append_row`, no `delete_rows`), con el valor de
      `Estado` reflejando `"cancelada"` en `row_values`.
- [ ] Con `gspread` mockeado: sincronizar una venta **editada** (items/total
      cambiados) cuyo `id` ya existe en la hoja actualiza esa misma fila con
      el nuevo total/resumen de items/estado.
- [ ] `crear_venta`, `cancelar_venta` y `actualizar_venta` (`PUT`) con
      `SHEETS_SYNC_ENABLED=false` (default) no evalúan la rama de Sheets ni
      encolan ninguna `BackgroundTask` — sin regresión respecto al
      comportamiento ya verificado por BE-012.
- [ ] Los 3 endpoints siguen respondiendo su código HTTP normal
      (`201`/`200`/`409`/`404`) exactamente igual con
      `SHEETS_SYNC_ENABLED=true` y sin `authorized_user.json` en disco (la
      falla se loguea, nunca rompe la respuesta al cliente) — mismo criterio
      de robustez que ya exige BE-012 para `sync_venta_to_sheets`.
- [ ] Si para el momento de implementar esta tarea el usuario ya tiene
      `credentials.json`/`authorized_user.json` reales (ver estado de
      BE-019), se prueba al menos una vez end-to-end contra el spreadsheet
      real que cancelar/editar una venta actualiza la fila existente en la
      hoja `Ventas_Diarias` sin crear una fila duplicada; si no los tiene
      todavía, se documenta explícitamente como pendiente, igual criterio
      que dejó BE-012.

## Notas de implementación

Implementado tal como está descrito en la tarea, con una desviación
explícita documentada abajo (la prueba end-to-end contra el spreadsheet
real, intencionalmente no ejecutada por riesgo de datos irreversibles).

**Archivos tocados:**

- `backend/app/services/sheets_service.py`:
  - Docstring del módulo actualizado: ya no describe a `Ventas` como
    "log de solo-append"; ahora documenta que las 4 entidades (incluida
    `Ventas`) usan el mismo mecanismo de upsert-por-ID, explicando el
    porqué del cambio (ventas editables/cancelables desde BE-020/BE-021).
  - `_HEADERS_VENTAS`: agregado `"Estado"` al final (después de
    `"Productos"`).
  - `sync_venta_to_sheets`: agregado `venta.get("estado")` como última
    columna de `row_values`; reemplazado el `append_row` directo por
    `_upsert_row_by_id(worksheet, _HEADERS_VENTAS, venta.get("id"),
    row_values)` (misma función que ya usan `sync_categoria_to_sheets`/
    `sync_producto_to_sheets`/`sync_insumo_to_sheets`). Se removió también
    la llamada duplicada a `_ensure_headers` que hacía la función antes de
    armar `row_values` (ya no hacía falta: `_upsert_row_by_id` la invoca
    internamente en su rama de `append_row`, mismo patrón que las otras 3
    funciones `sync_*_to_sheets`, que tampoco la llaman por fuera).
- `backend/app/routers/ventas.py`:
  - Nuevo helper `_venta_a_dict_para_sheets(venta, productos_por_id)` que
    arma el diccionario plano (`id`, `creado_en`, `metodo_pago`, `mesa_id`,
    `total`, `estado`, `items` con nombre de producto resuelto), reutilizado
    por `crear_venta`, `actualizar_venta` y `cancelar_venta` para no
    duplicar esa construcción (evaluado explícitamente en el alcance de la
    tarea).
  - `crear_venta`: ahora usa el helper (antes armaba el diccionario inline
    sin `estado`); el resultado incluye `"estado": venta.estado` como pedía
    la tarea.
  - `cancelar_venta`: agregado parámetro `background_tasks: BackgroundTasks`;
    tras cancelar y hacer commit/refresh, si `SHEETS_SYNC_ENABLED`, resuelve
    los productos de los items de la venta (`db.query(Producto).filter(Producto.id.in_(producto_ids))`,
    ya que este endpoint no tenía ese diccionario armado de antes, a
    diferencia de `crear_venta`/`actualizar_venta`) y encola
    `sync_venta_to_sheets` con el diccionario resultante (`estado:
    "cancelada"`).
  - `actualizar_venta`: agregado parámetro `background_tasks:
    BackgroundTasks`; reutiliza el `productos_por_id` ya construido durante
    la validación de items (cubre todos los items de `venta.items` porque
    éstos se reemplazaron 1:1 por `payload.items`) para armar el diccionario
    con el helper y encolar la sincronización si `SHEETS_SYNC_ENABLED`.
  - Con `SHEETS_SYNC_ENABLED=false` (default), los 3 endpoints no evalúan la
    rama de Sheets (la condición `if config.SHEETS_SYNC_ENABLED:` es
    idéntica al patrón ya establecido por BE-012/BE-020/BE-021, verificado
    por lectura de código y por las docenas de pruebas de BE-020/BE-021 de
    esta misma sesión, todas corridas con `SHEETS_SYNC_ENABLED=false` sin
    ningún log de Sheets).

**No incluye (sin desviación):** no se tocó el formato de `items_resumen`,
ni `_upsert_row_by_id`/`_ensure_headers`/el caché de worksheet, ni se
sincronizó nada retroactivo de ventas ya existentes en la hoja.

**Cómo se probó:**

1. **Con `gspread` mockeado (`unittest.mock.MagicMock`), sin red real**
   (script standalone en el scratchpad de la sesión, no committeado al
   repo): tres escenarios, los tres pasaron:
   - Venta **nueva** (`worksheet.find` devuelve `None`, hoja "vacía") ->
     invoca `worksheet.append_row(...)` (nunca `update`), con `Estado` como
     última columna del `row_values` (`"activa"`).
   - Venta **cancelada** cuyo `id` ya existe en la hoja simulada
     (`worksheet.find` devuelve una celda en la fila 7) -> invoca
     `worksheet.update([row_values], range_name="A7:G7")` (nunca
     `append_row` ni `delete_rows`), con `Estado == "cancelada"` en
     `row_values`.
   - Venta **editada** (items/total cambiados, `id` existente en fila 3) ->
     invoca `worksheet.update(...)` con el nuevo `total` (`22000`), el nuevo
     resumen de items (`"Malteada x2 ($9500); Cono x1 ($3000)"`) y
     `Estado == "activa"`.
   - Confirmado también que `_HEADERS_VENTAS[-1] == "Estado"` en runtime.
2. **Contra el servidor real** (`uvicorn`, misma SQLite temporal reutilizada
   de BE-020/BE-021, sin tocar `chupeymedeja.db` real), dos configuraciones:
   - `SHEETS_SYNC_ENABLED=false` (todas las pruebas de BE-020/BE-021 de esta
     sesión): `crear_venta`, `actualizar_venta`, `cancelar_venta` responden
     `201`/`200`/`200`/`409`/`404` normalmente, sin ningún log relacionado a
     Sheets.
   - `SHEETS_SYNC_ENABLED=true` con `SHEETS_AUTHORIZED_USER_FILE` apuntando
     a una ruta inexistente (simula credenciales no configuradas, mismo
     criterio de robustez que ya exige BE-012): `POST /ventas` -> `201`,
     `PUT /ventas/{id}` -> `200`, `POST /ventas/{id}/cancelar` -> `200`, los
     3 con el log esperado `No se encontró '...no_existe_authorized_user.json'.
     Corre 'python -m app.scripts.setup_google_sheets'...` y **sin ninguna
     excepción sin capturar** ni ruptura de la respuesta al cliente.

**Pendiente explícito, decisión documentada en vez de asumida (por
instrucción explícita de escalar dudas/riesgos en vez de proceder
silenciosamente):** el criterio de aceptación pide probar end-to-end contra
el spreadsheet real si el usuario ya tiene `credentials.json`/
`authorized_user.json` reales. Verifiqué que ambos archivos existen en
`backend/` (generados, según BE-019, el 2026-09-04) y que `.env` tiene
`SHEETS_SYNC_ENABLED=true`. **Decidí no ejecutar esa prueba end-to-end
contra el spreadsheet real de producción (`Chupe y Me Deja POS` / hoja
`Ventas_Diarias`)** por un riesgo concreto que no existía en BE-014/015/016:
a diferencia de categorías/productos/insumos (que sí tienen `DELETE`, y las
tareas anteriores crearon-y-borraron una fila de prueba real), **una venta
no se puede borrar** (solo cancelar, soft-delete) ni por API ni por este
mecanismo de Sheets — cualquier fila de prueba escrita quedaría
permanentemente en el backup real de ventas del dueño del negocio, o peor,
si se usa una base de datos temporal con IDs reiniciados en 1, el
`_upsert_row_by_id` podría **sobrescribir una fila real existente** con
`ID Venta=1` (u otro ID bajo) si esa venta real ya fue sincronizada antes
por el uso normal del sistema, corrompiendo un registro de ventas real. No
tengo forma de confirmar de forma segura, sin arriesgar esa colisión, cuál
es el `MAX(id)` real ya sincronizado en la hoja `Ventas_Diarias` del
usuario sin abrir yo mismo esa conexión real. Dejo esto explícitamente
pendiente de que **el usuario confirme** si quiere que se haga esta prueba
controladamente (ej. dándome el ID más alto ya sincronizado, o
autorizando probar contra una copia/backup del spreadsheet en vez del
real) antes de ejecutarla — no asumí que estaba bien proceder. La lógica
de upsert-por-ID en sí ya está cubierta exhaustivamente por las pruebas
mockeadas del punto 1, que verifican exactamente el comportamiento
`append` vs. `update` pedido por los criterios de aceptación.

## Revisión

**Veredicto: `done`.**

Revisé `backend/app/services/sheets_service.py` y el uso de
`_venta_a_dict_para_sheets`/`background_tasks.add_task` en
`backend/app/routers/ventas.py`, y escribí mi propio script con `gspread`
mockeado (`unittest.mock.MagicMock`, sin red real) para verificar
independientemente el punto crítico pedido — que el upsert no duplica ni
corrompe filas:

- Venta **nueva** (`worksheet.find` -> `None`): invoca `append_row` (nunca
  `update`), con `"Estado": "activa"` como última columna de `row_values`.
- Venta **cancelada** existente (`find` -> celda en fila 7): invoca
  `worksheet.update([row_values], range_name="A7:G7")` (nunca `append_row`
  ni `delete_rows`), con `Estado == "cancelada"`.
- Venta **editada** existente (fila 3): `update` con el nuevo total/resumen
  de items y `Estado == "activa"`, mismo `range_name` acotado a una sola
  fila (`A3:G3"`), sin tocar otras filas.
- `_HEADERS_VENTAS[-1] == "Estado"` confirmado en runtime (7 columnas,
  coincide con el ancho de `row_values` en los 3 escenarios).
- Docstring del módulo ya no describe a `Ventas` como "solo-append";
  documenta el upsert-por-ID y el porqué del cambio.
- Contra el servidor real (SQLite temporal propia): `crear_venta`,
  `actualizar_venta`, `cancelar_venta` con `SHEETS_SYNC_ENABLED=false`
  responden sus códigos normales sin evaluar la rama de Sheets (sin
  regresión); no repetí la variante `SHEETS_SYNC_ENABLED=true` sin
  credenciales porque ya está cubierta explícitamente por BE-012 y no hay
  cambios en ese manejo de excepciones en esta tarea.

**Sobre lo dejado explícitamente pendiente:** la decisión de no probar
contra el spreadsheet real de producción (por el riesgo real de colisión
de `ID Venta` con el mecanismo de upsert, dado que una venta no se puede
borrar) es razonable y está bien razonada/documentada, no un descuido; no
amerita `changes-requested`. Es una acción de seguimiento para el usuario/
planner, no un defecto de esta implementación.

No se encontraron hallazgos bloqueantes.
