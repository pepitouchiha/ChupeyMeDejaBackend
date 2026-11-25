---
id: BE-033
title: Trabajadores y registro de pagos (nómina)
area: backend
status: done
priority: medium
depends_on: [BE-032]
created_by: planner
---

## Objetivo

Llevar la lista de trabajadores y lo que se les paga, para que la nómina
cuente como gasto en la contabilidad. No hay login por trabajador: se sigue
entrando con el único usuario admin (decisión del dueño).

## Alcance

**Incluye:**

- Modelo `Trabajador` (tabla `trabajadores`): `id, nombre (1..150), cargo
  (str ≤80 nullable, ej. "Cajero", "Mesero", "Preparador"), telefono (≤30
  nullable), documento (≤30 nullable), tipo_pago (mensual | quincenal |
  semanal | diario | por_turno), monto_pago (int ≥ 0, valor acordado por
  periodo/turno), activo (bool, default true), fecha_ingreso (date nullable), creado_en`.
- Endpoints `/trabajadores`:
  - `GET /trabajadores?incluir_inactivos=false`, `GET /trabajadores/{id}`,
    `POST`, `PATCH/PUT /trabajadores/{id}`.
  - `DELETE /trabajadores/{id}`: si tiene pagos → 409 sugiriendo desactivar; si no → 204.
  - `POST /trabajadores/{id}/pagos` `{monto > 0, fecha?, descripcion?, pagado_desde_caja: bool = false}`
    → crea un `Gasto` `categoria=nomina`, `trabajador_id`, descripción default
    `"Pago a <nombre>"`. Devuelve `GastoOut`. Trabajador inactivo → 409.
  - `GET /trabajadores/{id}/pagos?desde=&hasta=` → `GastoOut[]` de ese trabajador.
- `TrabajadorOut` incluye `total_pagado_mes_actual` (suma de pagos con `fecha`
  en el mes local actual).
- Editar/borrar un pago se hace con `PATCH/DELETE /gastos/{id}` (BE-032); en
  `PATCH` no se permite cambiar `categoria` de un gasto de nómina ni quitarle el trabajador (422).

**No incluye:** liquidación automática de nómina, prestaciones, turnos/horarios, UI (FE-047).

## Criterios de aceptación

- [ ] CRUD de trabajadores con validaciones (nombre vacío → 422, tipo_pago fuera del enum → 422).
- [ ] Registrar un pago crea un gasto `nomina` visible en `GET /gastos` y en `GET /trabajadores/{id}/pagos`.
- [ ] `total_pagado_mes_actual` solo suma pagos del mes local actual.
- [ ] Borrar un trabajador con pagos → 409; desactivarlo lo saca del listado por defecto.
- [ ] Pago a trabajador inactivo → 409.

## Notas de implementación

**Archivos nuevos:** `app/models/trabajador.py`, `app/schemas/trabajador.py`, `app/routers/trabajadores.py`. Registrados en `db/base_all.py` y `main.py`. `Gasto.trabajador_id` ahora tiene FK a `trabajadores.id` (ver limitación para bases preexistentes en BE-034). En `routers/gastos.py`, `PATCH /gastos/{id}` devuelve 422 si se intenta cambiar `categoria` a un gasto con trabajador; la categoría `nomina` ya se rechazaba en el schema al crear o editar a mano, y `GastoUpdate` no permite quitar `trabajador_id`.

**Decisiones**
- `PUT` y `PATCH /trabajadores/{id}` comparten handler con semántica parcial (igual que insumos); `cargo/telefono/documento/fecha_ingreso` se pueden poner en `null`. Textos vacíos o solo espacios en cargo/teléfono/documento se guardan como `null`; nombre vacío => 422.
- `POST /trabajadores/{id}/pagos` responde 201 con `GastoOut` (`categoria=nomina`, `origen=nomina`, descripción default "Pago a <nombre>"). Orden: 404 trabajador, 409 si inactivo, 409 si `pagado_desde_caja` y la caja está cerrada (no se crea el gasto); si hay sesión, se asigna `caja_sesion_id` (BE-034).
- `total_pagado_mes_actual` suma `Gasto.monto` con `trabajador_id` y `fecha` dentro del mes calendario de hoy en hora local (`hoy_local`), sin importar `pagado_desde_caja`.
- `DELETE`: 409 sugiriendo desactivar si tiene pagos; 204 si no. Los pagos de un trabajador inactivo siguen consultables.
- Editar o borrar un pago: `PATCH/DELETE /gastos/{id}` (BE-032).
- Sin autenticación por trabajador ni dependencias nuevas.

**Cómo se probó** (misma corrida de `scratchpad/test_be034.py`, 71 OK / 0 fallos): validaciones 422 (nombre vacío, tipo_pago fuera del enum, monto negativo, pago con monto 0); CRUD y PATCH parcial; el pago crea un gasto nomina visible en `GET /gastos?categoria=nomina` y en `GET /trabajadores/{id}/pagos` (con filtro `desde`); `total_pagado_mes_actual` excluye un pago con fecha del mes anterior; pago desde caja asigna sesión y suma al resumen; pago desde caja cerrada => 409 sin crear gasto; PATCH categoria de pago de nómina => 422, PATCH monto OK; borrar con pagos 409 / sin pagos 204; desactivar lo saca del listado (reaparece con `incluir_inactivos=true`); pago a inactivo 409.

**Ejemplo:** `POST /trabajadores {"nombre":"Ana","cargo":"Cajera","tipo_pago":"quincenal","monto_pago":800000}` y luego `POST /trabajadores/1/pagos {"monto":400000,"pagado_desde_caja":true}`.

## Revisión

**Veredicto: done.**

Verificado leyendo `routers/trabajadores.py`, `schemas/trabajador.py`, `models/trabajador.py`, `routers/gastos.py`, y con las corridas de `test_be034.py` (71 OK) y `review_be034.py`.

- Validaciones: nombre vacío/espacios -> 422 (create y PATCH), `tipo_pago` fuera del enum -> 422, `monto_pago` negativo -> 422, pago con monto 0 -> 422, trabajador inexistente -> 404.
- Pago crea gasto `nomina` (origen nomina, descripción default "Pago a <nombre>") visible en `/gastos` y `/trabajadores/{id}/pagos`; pago a inactivo -> 409; pago desde caja cerrada -> 409 sin crear el gasto (`routers/trabajadores.py:163` asigna sesión antes del `db.add`); con caja abierta suma al resumen.
- `total_pagado_mes_actual` filtra por mes local actual (`trabajadores.py:29-42`), excluye mes anterior.
- DELETE con pagos -> 409, sin pagos -> 204; desactivar lo saca del listado por defecto.
- PATCH de categoría en un pago de nómina -> 422.

Observación menor, no bloqueante: `routers/gastos.py:91` solo bloquea el cambio de categoría si `trabajador_id` no es nulo; un gasto con categoría `nomina` sin trabajador (datos legados) podría recategorizarse. No se puede crear por la API actual.
