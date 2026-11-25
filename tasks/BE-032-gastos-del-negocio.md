---
id: BE-032
title: Gastos del negocio (incluye compras de inventario)
area: backend
status: done
priority: high
depends_on: [BE-030]
created_by: planner
---

## Objetivo

Registrar todo lo que sale de plata del negocio para poder calcular lo
**invertido** y la **ganancia neta** (BE-035): compras de inventario, insumos
de preparación que no se inventarian (bolsas de granizado, jarabes, hielo,
leche condensada…), nómina, arriendo, servicios y otros. `Gasto` es la única
fuente de verdad del dinero invertido: las compras de inventario (BE-030) y
los pagos a trabajadores (BE-033) **crean** un gasto vinculado.

## Alcance

**Incluye:**

- Modelo `Gasto` (tabla `gastos`): `id, fecha (date, día local del gasto,
  default hoy_local()), categoria (compra_inventario | insumos_preparacion |
  nomina | arriendo | servicios | mantenimiento | otros), descripcion
  (str 1..255), monto (int > 0), pagado_desde_caja (bool), caja_sesion_id (FK
  nullable — se llena en BE-034), movimiento_inventario_id (FK nullable),
  trabajador_id (FK nullable — BE-033), creado_en`.
- Endpoints `/gastos` (con `require_auth`):
  - `GET /gastos?desde=&hasta=&categoria=` (por `fecha`, más reciente primero).
  - `POST /gastos` `{fecha?, categoria, descripcion, monto, pagado_desde_caja?}`.
    No acepta `categoria=nomina` (eso va por BE-033) → 422 con mensaje.
  - `PATCH /gastos/{id}` (`fecha, categoria, descripcion, monto, pagado_desde_caja`).
  - `DELETE /gastos/{id}` → 204. Borrar un gasto vinculado a una entrada de
    inventario NO toca el stock (solo quita el registro contable); documentarlo.
  - `GET /gastos/categorias` → lista fija `[{valor, etiqueta}]` para el frontend.
- Completar el punto de extensión de BE-030: `POST /insumos/{id}/entradas`
  con `registrar_gasto=true` y `costo_total > 0` crea un `Gasto`
  `compra_inventario` con descripción `"Compra: <cantidad> <unidad> de <nombre>"`,
  `movimiento_inventario_id` y `pagado_desde_caja` del request, en la misma transacción.
- `GastoOut` incluye todos los campos + `origen` derivado (`manual | inventario | nomina`).

**No incluye:** relación con la sesión de caja (BE-034 agrega la regla de
`pagado_desde_caja`), reportes (BE-035), UI (FE-046).

## Criterios de aceptación

- [ ] CRUD completo de gastos manuales; `monto ≤ 0` o `descripcion` vacía → 422.
- [ ] Filtro por rango de fechas y por categoría funciona y respeta el día local.
- [ ] Una entrada de inventario con costo crea exactamente un gasto `compra_inventario` vinculado; con `registrar_gasto=false` o sin costo, ninguno.
- [ ] `POST /gastos` con `categoria=nomina` → 422.
- [ ] Borrar un gasto de inventario no cambia el stock del insumo.

## Notas de implementación

**Archivos**
- `app/models/gasto.py` (nuevo): `Gasto` (`gastos`), constantes de categoría, CheckConstraint de categoría, `fecha` con default `hoy_local()`, propiedad `origen` (`inventario` si hay `movimiento_inventario_id`; `nomina` si hay `trabajador_id` o categoría nomina; si no `manual`).
- `app/schemas/gasto.py` (nuevo): `GastoCreate/Update/Out`, `CategoriaGastoOut`, enums y etiquetas. `categoria=nomina` se rechaza con validador (422 con mensaje) en POST y PATCH.
- `app/routers/gastos.py` (nuevo, `require_auth`): `GET /gastos?desde&hasta&categoria`, `POST`, `PATCH /{id}`, `DELETE /{id}` (204), `GET /gastos/categorias`.
- `app/services/inventario.py`: `registrar_gasto_de_entrada` completado (crea el `Gasto` en la misma transacción, sin commit).
- `app/main.py`, `app/db/base_all.py`: registro del router y del modelo.

**Decisiones**
- `caja_sesion_id` y `trabajador_id` son `Integer` nullable **sin FK** (las tablas de caja/trabajadores no existen aún; una FK a tabla inexistente rompe `create_all`). BE-033/BE-034 pueden añadir la FK. Sin lógica de caja.
- Solo se crea gasto si `costo_total > 0` (el monto del gasto debe ser > 0); `costo_total=0` no crea gasto aunque `registrar_gasto=true`.
- Descripción: `"Compra: {cantidad:g} {unidad} de {nombre}"` (ej. `Compra: 24 botella de Cerveza`).
- `fecha` filtra por la columna `date` directamente (inclusiva); el default usa el día local del negocio. `creado_en` se devuelve en hora local como en movimientos.
- `DELETE /gastos/{id}` solo quita el registro contable; no toca stock ni el movimiento (documentado en el docstring).
- Tabla nueva: la crea `create_all`, no requiere migración.

**Cómo se probó** (base temporal, auth sobreescrita; script `test_be031.py` en el scratchpad cubre BE-031 y BE-032, 52 comprobaciones OK)
- CRUD, monto 0/negativo y descripción vacía -> 422; nomina -> 422 (POST y PATCH); filtros por rango/categoría y orden descendente; `/gastos/categorias` (7).
- Entrada `cantidad=24, costo_total=48000` -> 1 gasto `compra_inventario` vinculado al movimiento; con `registrar_gasto=false`, sin costo o costo 0 -> ninguno; `pagado_desde_caja` se copia; entradas inválidas (404/422) no crean gasto.
- Borrar el gasto de inventario no cambia stock ni cantidad de movimientos.
- Ejemplo: `POST /gastos {"categoria":"servicios","descripcion":"Luz","monto":80000}`.

## Revisión

**Veredicto: done** (revisor, 2026-11-17)

Verificado por lectura de `models/gasto.py`, `schemas/gasto.py`, `routers/gastos.py`, `services/inventario.py:48-92` y pruebas propias en base temporal:
- CRUD OK; monto 0/decimal, descripcion vacia/blanca (POST y PATCH) -> 422; nomina -> 422 en POST y PATCH; categoria invalida en filtro -> 422.
- Filtros por desde/hasta (inclusivos) y categoria; orden fecha desc, id desc.
- Entrada con costo + registrar_gasto crea exactamente un gasto `compra_inventario` vinculado (origen `inventario`, descripcion "Compra: 5 ..."), en la misma transaccion (flush sin commit); DELETE del gasto devuelve 204 y no cambia el stock; 404 en inexistente.
- Observaciones menores (no bloqueantes): PATCH permite editar monto/categoria de un gasto vinculado a inventario sin tocar el movimiento (aceptable por diseno); `caja_sesion_id`/`trabajador_id` sin FK, documentado.
