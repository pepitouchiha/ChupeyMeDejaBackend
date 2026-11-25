---
id: BE-034
title: Caja — apertura con base, cierre manual y cuadre de efectivo
area: backend
status: done
priority: high
depends_on: [BE-032]
created_by: planner
---

## Objetivo

El negocio siempre deja una **base** de efectivo en la caja. Cada jornada se
abre la caja con esa base y se **cierra manualmente** a la hora en que cierra
el local (no a medianoche). Al cerrar, se cuenta el efectivo y el sistema lo
compara con lo esperado, y se define cuánto se deja de base para la próxima
apertura.

## Alcance

**Incluye:**

- Modelo `CajaSesion` (tabla `caja_sesiones`): `id, abierta_en, cerrada_en
  (nullable), base_inicial (int ≥0), notas_apertura (nullable)`; al cerrar se
  guarda una **foto** de los totales: `ventas_efectivo, ventas_transferencia,
  num_ventas, gastos_desde_caja, efectivo_esperado, efectivo_contado,
  diferencia (contado − esperado), base_siguiente, retiro (contado −
  base_siguiente), notas_cierre`.
- Solo puede haber una sesión abierta a la vez.
- Columna nueva `ventas.caja_sesion_id` (FK nullable; migración ligera con
  `ALTER TABLE ADD COLUMN` en `migrations.py`). Se asigna la sesión abierta
  cuando una venta pasa a `activa` (`POST /ventas` directa y `POST /ventas/{id}/cerrar`).
- **Regla:** `POST /ventas` y `POST /ventas/{id}/cerrar` responden `409 "La caja
  está cerrada. Abre la caja para registrar ventas."` si no hay sesión abierta.
  Abrir pedidos y agregar items **sí** se permite con la caja cerrada.
- Gastos (BE-032): si `pagado_desde_caja=true`, se exige sesión abierta (409
  si no) y se asigna `caja_sesion_id`. Aplica también a entradas de
  inventario y pagos de nómina pagados desde caja.
- Fórmula: `efectivo_esperado = base_inicial + ventas_efectivo (activas de la
  sesión) − gastos_desde_caja (de la sesión)`. Las transferencias se informan
  pero no entran al efectivo esperado.
- Endpoints `/caja`:
  - `GET /caja/actual` → `{abierta: false, base_sugerida}` o la sesión abierta
    con el resumen **en vivo** (mismos campos que la foto de cierre, calculados ahora,
    + `pedidos_abiertos` = cantidad de ventas `abierta`). `base_sugerida` = `base_siguiente`
    de la última sesión cerrada (0 si no hay).
  - `POST /caja/abrir` `{base_inicial ≥ 0, notas?}` → 409 si ya hay una abierta.
  - `POST /caja/cerrar` `{efectivo_contado ≥ 0, base_siguiente ≥ 0, notas?}` → 409
    si no hay sesión abierta; 409 si hay pedidos `abierta` (mensaje: cobrarlos o
    descartarlos antes); 422 si `base_siguiente > efectivo_contado`. Guarda la foto y `cerrada_en`.
  - `GET /caja/sesiones?desde=&hasta=` → historial (más reciente primero).
  - `GET /caja/sesiones/{id}` → sesión + lista de ventas y gastos de esa sesión.
- Cancelar una venta de una sesión ya cerrada está permitido pero no modifica
  la foto de esa sesión (documentarlo); si la sesión sigue abierta, el resumen en vivo la excluye.
- `VentaOut` agrega `caja_sesion_id`.

**No incluye:** varias cajas/terminales, arqueo por denominaciones, UI (FE-045).

## Criterios de aceptación

- [ ] Con la caja cerrada: venta directa y cobrar pedido → 409; abrir pedido y agregar items → OK.
- [ ] Abrir con base 100.000, vender 50.000 en efectivo y 30.000 por transferencia, gasto de 20.000 desde caja → `efectivo_esperado = 130.000`.
- [ ] Cerrar con `efectivo_contado=125.000` deja `diferencia = −5.000`; con `base_siguiente=100.000`, `retiro=25.000`.
- [ ] Tras cerrar, `GET /caja/actual` devuelve `abierta:false` y `base_sugerida=100.000`.
- [ ] Abrir dos veces → 409; cerrar sin sesión → 409; cerrar con pedidos abiertos → 409.
- [ ] Gasto `pagado_desde_caja` con caja cerrada → 409.
- [ ] Una venta cancelada no cuenta en el resumen en vivo.
- [ ] Una base existente recibe la columna `caja_sesion_id` sin perder datos.

## Notas de implementación

**Archivos nuevos:** `app/models/caja.py` (`CajaSesion`), `app/schemas/caja.py`, `app/services/caja.py` (sesión abierta, resumen, regla de caja, base sugerida), `app/routers/caja.py`.
**Modificados:** `models/venta.py` y `schemas/venta.py` (`caja_sesion_id`), `routers/ventas.py`, `routers/gastos.py`, `services/inventario.py`, `models/gasto.py`, `db/base_all.py`, `db/migrations.py`, `main.py`.

**Decisiones**
- `POST /ventas` y `POST /ventas/{id}/cerrar` exigen sesión abierta (409 con el mensaje exacto de la tarea) y guardan `ventas.caja_sesion_id`. `PUT /ventas/{id}` no cambia la sesión de una venta. Abrir pedidos y agregar items no consultan la caja.
- Regla `pagado_desde_caja` centralizada en `services/caja.asignar_caja_si_corresponde`: la usan `POST /gastos`, `PATCH /gastos/{id}` (solo si cambia el flag: al activarlo exige sesión y la asigna; al desactivarlo limpia `caja_sesion_id`), entradas de inventario (`registrar_entrada`, con chequeo previo para no dejar stock/movimiento a medias) y pagos de nómina (BE-033). Mensaje 409 para gastos: "La caja está cerrada. Abre la caja para registrar pagos desde caja."
- Resumen en vivo = ventas `activa` de la sesión (por `metodo_pago`) y gastos con `pagado_desde_caja` y `caja_sesion_id` de la sesión. Al cerrar se guarda la foto; una sesión cerrada siempre devuelve la foto. Cancelar una venta de una sesión ya cerrada está permitido y NO altera la foto (probado); en sesión abierta el resumen en vivo la excluye. Igualmente, editar o borrar un gasto de una sesión cerrada no modifica su foto.
- `GET /caja/actual` devuelve un objeto plano: `{abierta:false, base_sugerida}` o, con caja abierta, `abierta:true, base_sugerida, id, abierta_en, base_inicial, notas_apertura, ventas_efectivo, ventas_transferencia, num_ventas, gastos_desde_caja, efectivo_esperado, pedidos_abiertos` (los no aplicables salen `null`). `POST /caja/abrir` (201) devuelve esa misma forma. `POST /caja/cerrar` devuelve `CajaSesionOut` con la foto completa. `GET /caja/sesiones/{id}` = sesión + `ventas` (todas las de la sesión, incluidas canceladas, con su `estado`) + `gastos`.
- Orden de validaciones en cerrar: 409 sin sesión, 409 pedidos `abierta`, 422 `base_siguiente > efectivo_contado`. `pedidos_abiertos` cuenta todas las ventas `abierta` (no solo de la sesión).
- Fechas de sesión en hora local (como el resto de la API); `desde/hasta` filtran por `abierta_en` (día local).
- "Solo una sesión abierta" se garantiza en la aplicación (SQLite sin concurrencia real de escritura); no hay índice único parcial.
- `GastoOut` se reutiliza vía `gasto_a_out` (renombrada de `_a_out` en `routers/gastos.py`, ahora pública).
- **FK de BE-032:** `gastos.caja_sesion_id -> caja_sesiones.id` y `gastos.trabajador_id -> trabajadores.id` quedan declaradas en el modelo, así que las bases creadas desde cero las tienen a nivel de motor (verificado con `pragma foreign_key_list`). En una base con `gastos` preexistente la columna queda SIN FK de motor (SQLite no permite agregarla sin reconstruir la tabla; no lo hice por no arriesgar datos). La integridad la garantiza la app, misma limitación ya aceptada para los CHECK.
- Migración: `_agregar_columna_caja_sesion_ventas` en `migrations.py`, al final de `run_lightweight_migrations` (después de la reconstrucción de `ventas` de BE-025). `ALTER TABLE ventas ADD COLUMN caja_sesion_id INTEGER REFERENCES caja_sesiones (id)`; idempotente. Las ventas históricas quedan con `caja_sesion_id = NULL`.
- Sin cambios en dependencias ni requirements.

**Cómo se probó** (`scratchpad/test_be034.py`, base temporal `scratchpad/test_be034.db`, TestClient con `require_auth` anulado): 71 comprobaciones OK, 0 fallos. Cubre todos los criterios: caja cerrada (venta directa 409, cobrar pedido 409 sin descontar stock, abrir pedido y agregar items OK, gasto/entrada/pago desde caja 409 sin dejar movimientos); base 100.000 + venta efectivo 50.000 + transferencia 30.000 + gasto 20.000 desde caja => `efectivo_esperado=130.000`; cerrar con contado 125.000 => `diferencia=-5.000`, `retiro=25.000` con base_siguiente 100.000; tras cerrar `abierta:false, base_sugerida=100000`; abrir dos veces / cerrar sin sesión / cerrar con pedidos abiertos => 409; 422 por base_siguiente > contado; venta cancelada excluida del resumen en vivo; foto intacta tras cancelar venta de sesión cerrada; historial y filtros; detalle con ventas y gastos. También verifica que BE-031 sigue funcionando con caja abierta (descuento de stock en venta directa y al cobrar un pedido). Migración: copia de una base previa a BE-034 (7 ventas) => columna agregada, 7 filas intactas, FK presente, segunda corrida sin efecto. La base real `backend/chupeymedeja.db` (respaldo en `scratchpad/brainfreeze_backup_be034.db`) migró al arrancar, se crearon `caja_sesiones`/`trabajadores` y el usuario admin sigue. Nota: `scratchpad/test_be031.py` ya no pasa tal cual (las ventas ahora requieren caja abierta); es esperado.

**Cómo probar a mano:** `uvicorn app.main:app` y luego `POST /caja/abrir {"base_inicial":100000}`, vender, `GET /caja/actual`, `POST /caja/cerrar {"efectivo_contado":125000,"base_siguiente":100000}`.

## Revisión

**Veredicto: done.**

Verificado leyendo `services/caja.py`, `routers/caja.py`, `routers/ventas.py`, `routers/gastos.py`, `services/inventario.py` y `db/migrations.py`, y ejecutando `scratchpad/test_be034.py` (71 OK, 0 FAIL) más una corrida propia (`scratchpad/review_be034.py`, base `review_be034.db`) con casos extra.

- Fórmula y foto: 100.000 + 50.000 efectivo - 20.000 gasto = 130.000 (transferencia excluida); contado 135.000 vs esperado 140.000 da diferencia -5.000 y retiro con base_siguiente 100.000 correcto; `base_sugerida` = 100.000 tras cerrar.
- Sesión correcta: `caja_sesion_id` se asigna solo al pasar a activa (`routers/ventas.py:133`, `:461`); una sesión 2 arranca en cero; cancelar una venta de la sesión 1 estando abierta la 2 no altera la foto ni la sesión 2; cancelada en sesión abierta se excluye.
- 409: venta directa y cobro con caja cerrada (mensaje exacto, sin descontar stock); abrir pedido/agregar items permitido; cerrar con pedidos abiertos; abrir dos veces; cerrar sin sesión; gasto, entrada de inventario, pago de nómina y PATCH del flag con caja cerrada responden 409 sin dejar gasto, movimiento ni stock modificado. 422 si base_siguiente > contado.
- Migración: `ALTER TABLE ADD COLUMN` idempotente, al final de `run_lightweight_migrations` (después de `create_all`); probada por el implementador con copia de base previa sin pérdida de filas.

Observaciones menores, no bloqueantes:
- `routers/gastos.py:104-106`: reactivar `pagado_desde_caja` en un gasto de una sesión ya cerrada lo reasigna a la sesión abierta actual (la foto vieja no cambia). Comportamiento aceptable pero conviene tenerlo presente.
- No hay linter (ruff/mypy) instalado en el venv, no se pudo correr análisis estático.
