---
id: BE-030
title: Rediseño de inventario — insumos por tipo y registro de movimientos
area: backend
status: done
priority: high
depends_on: [BE-004]
created_by: planner
---

## Objetivo

El negocio solo quiere inventariar lo que se cuenta fácil por unidad: **vasos
de cada onzaje (con sus tapas/pitillos), bebidas embotelladas, cervezas,
licores/tragos e implementos** (cucharas, servilletas, bolsas para llevar…).
Los granizados en sí NO se inventarian (se preparan combinando sabores en
distintos onzajes). Las bolsas de granizado, jarabes, hielo, etc. se registran
como **gasto** (BE-032), no como inventario.

Hoy `Insumo` (BE-004) depende de `categorias` (que son categorías de
**productos** del menú) y el stock solo se cambia con `ajustar-stock` sin
dejar rastro. Esta tarea rediseña el insumo y agrega un historial de
movimientos, base para el descuento automático por venta (BE-031) y para las
compras que cuentan como inversión (BE-032/BE-035).

## Alcance

**Incluye:**

- Modelo `Insumo` (`app/models/insumo.py`):
  - Reemplazar `categoria_id` por `tipo` (`vaso | bebida | licor | implemento | otro`,
    `CheckConstraint` + enum Pydantic). Deja de depender de `categorias`.
  - Nuevos campos: `unidad` (str ≤20, default `"unidad"`, ej. "unidad",
    "botella", "lata", "paquete"), `costo_unitario` (int COP, nullable — se
    actualiza con el costo de la última entrada), `activo` (bool, default true).
  - `stock` y `stock_minimo` se mantienen (float). `calcular_estado` se mantiene.
- Modelo nuevo `MovimientoInventario` (tabla `inventario_movimientos`):
  `id, insumo_id (FK), tipo (entrada | ajuste | venta | reverso_venta),
  cantidad (float, con signo: + suma, − resta), stock_resultante (float),
  costo_total (int nullable, solo entradas), venta_id (FK nullable),
  nota (str ≤255 nullable), creado_en (UTC naive, como Venta)`.
- Migración en `app/db/migrations.py`: si la tabla `insumos` existe con el
  esquema viejo (`categoria_id`), recrearla con el patrón "copiar a tabla
  nueva, migrar filas, renombrar" ya usado en
  `_permitir_metodo_pago_nulo_ventas`, mapeando las filas existentes a
  `tipo='otro'`, `unidad='unidad'`, `activo=1`. Idempotente.
- Endpoints (`app/routers/insumos.py`, todos con `require_auth`):
  - `GET /insumos?tipo=&solo_alertas=&incluir_inactivos=false` → `InsumoOut[]`.
  - `POST /insumos` `{nombre, tipo, unidad?, stock?, stock_minimo?, costo_unitario?}`.
    Si `stock > 0` se registra un movimiento `ajuste` inicial con nota "Stock inicial".
  - `PATCH/PUT /insumos/{id}` `{nombre?, tipo?, unidad?, stock_minimo?, costo_unitario?, activo?}`
    (no cambia `stock`).
  - `POST /insumos/{id}/entradas` `{cantidad > 0, costo_total ≥ 0 | null, nota?, registrar_gasto: bool = true, pagado_desde_caja: bool = false}`
    → suma stock, crea movimiento `entrada`; si `costo_total` y `cantidad`,
    actualiza `costo_unitario = round(costo_total / cantidad)`. La creación del
    `Gasto` vinculado (`registrar_gasto`, `pagado_desde_caja`) se cablea en
    BE-032: en esta tarea dejar los campos en el schema y un punto de
    extensión claro (función de servicio) que BE-032 complete.
  - `POST /insumos/{id}/ajustar-stock` se mantiene (delta con signo, ≠0) y
    ahora acepta `nota?` y registra movimiento `ajuste`.
  - `POST /insumos/{id}/conteo` `{stock_contado ≥ 0, nota?}` → fija el stock al
    valor contado y registra un movimiento `ajuste` con el delta (si delta = 0,
    no crea movimiento y devuelve el insumo igual).
  - `GET /insumos/{id}/movimientos?desde=&hasta=` → `MovimientoOut[]` del más
    reciente al más antiguo (fechas filtradas por día local con los helpers de
    `app/core/timezone.py`).
  - `DELETE /insumos/{id}`: si tiene movimientos o recetas (BE-031) → `409`
    sugiriendo desactivarlo (`activo=false`); si no, borra.
- `InsumoOut`: `id, nombre, tipo, unidad, stock, stock_minimo, costo_unitario, activo, estado`.
- `GET /reportes/alertas-stock` sigue funcionando con el nuevo modelo (solo activos).
- Quitar la sincronización de insumos con Google Sheets si depende de
  `categoria_id`, o adaptarla al nuevo esquema (sigue apagada por config).

**No incluye:** descuento por ventas (BE-031), creación del gasto (BE-032),
frontend (FE-043).

## Criterios de aceptación

- [ ] Una base nueva crea `insumos` con `tipo/unidad/costo_unitario/activo` y sin `categoria_id`.
- [ ] Una base existente con el esquema viejo se migra al arrancar sin perder filas; arrancar dos veces no falla.
- [ ] `POST /insumos/{id}/entradas` con `cantidad=50, costo_total=25000` deja stock +50, `costo_unitario=500` y un movimiento `entrada` con `stock_resultante` correcto.
- [ ] `cantidad ≤ 0` en entradas → 422; `tipo` fuera del enum → 422; insumo inexistente → 404.
- [ ] `POST /insumos/{id}/conteo` con un valor distinto al stock crea un movimiento `ajuste` con el delta exacto; con el mismo valor no crea movimiento.
- [ ] Todo cambio de stock (crear con stock, entrada, ajuste, conteo) deja exactamente un movimiento.
- [ ] `DELETE` de un insumo con movimientos → 409; sin movimientos → 204.
- [ ] `GET /insumos` no devuelve inactivos salvo `incluir_inactivos=true`.

## Notas de implementación

**Archivos**
- `app/models/insumo.py`: `Insumo` con `tipo/unidad/costo_unitario/activo` (sin `categoria_id`) y nuevo `MovimientoInventario` (`inventario_movimientos`); constantes `TIPOS_INSUMO`, `MOV_*`; CheckConstraints en ambos `tipo`.
- `app/schemas/insumo.py`: enums `TipoInsumo`/`TipoMovimiento`, `InsumoCreate/Update/Out`, `AjusteStock` (+`nota`), `EntradaInsumo`, `ConteoInsumo`, `MovimientoOut`.
- `app/services/inventario.py` (nuevo): `registrar_movimiento` (aplica delta al stock y crea el movimiento, sin commit), `registrar_entrada`, `registrar_ajuste` y el punto de extensión `registrar_gasto_de_entrada` (hoy no-op; BE-032 lo completa; se invoca solo si `registrar_gasto` y hay `costo_total`).
- `app/routers/insumos.py`: reescrito con los endpoints pedidos (`GET` con `tipo/solo_alertas/incluir_inactivos`, `POST`, `PUT/PATCH`, `/entradas`, `/ajustar-stock`, `/conteo`, `/movimientos?desde&hasta`, `DELETE`).
- `app/db/migrations.py`: `_migrar_insumos_a_tipo` (idempotente). Crea tabla nueva, copia filas (tipo='otro', unidad='unidad', activo=1), borra la vieja y renombra la nueva (orden elegido para que el FK de `inventario_movimientos` no se reescriba a un nombre temporal).
- `app/db/base_all.py`: import de `MovimientoInventario` (edición mínima).
- `app/routers/categorias.py`: quitado el conteo de insumos al borrar categoría (ya no hay relación).
- `app/services/sheets_service.py`: sync de insumos adaptado (columna "Tipo" en lugar de "Categoría"). Sigue apagada por config; una hoja ya existente conservaría el encabezado viejo.

**Decisiones**
- `PUT` y `PATCH` comparten handler; `costo_unitario` se puede poner a `null` enviándolo explícitamente.
- Entrada sin `costo_total` no toca `costo_unitario`.
- Conteo: fija `stock` exacto al valor contado (sin arrastre de float); delta=0 no crea movimiento.
- `creado_en` de movimientos se devuelve en hora local del negocio (igual que ventas).
- Crear insumo con `stock>0` deja 1 movimiento `ajuste` "Stock inicial" (stock y movimiento en la misma transacción).
- DELETE: solo verifica movimientos; el chequeo de recetas (BE-031) se agrega cuando exista esa tabla.
- `GET /reportes/alertas-stock` reutiliza `listar_insumos`, por lo que solo devuelve activos.

**Cómo se probó** (base temporal, auth sobreescrita; `httpx` instalado fuera del proyecto, en el scratchpad, solo para TestClient)
- Migración: base con esquema viejo (2 insumos con `categoria_id`) arrancada 2 veces: filas preservadas con tipo 'otro', sin error; `PRAGMA foreign_key_check` vacío.
- 31 comprobaciones sobre la API, todas OK: entrada 50 por 25000 -> stock +50, `costo_unitario=500`, movimiento con `stock_resultante` correcto; 422 con cantidad<=0 y tipo inválido; 404; conteo con delta exacto (-2.5) y sin movimiento si es igual; DELETE 409 con movimientos / 204 sin; filtros de inactivos, tipo, fechas y alertas.
- Base real `chupeymedeja.db`: arrancada una vez, migrada (`insumos` nueva, `inventario_movimientos` creada), usuario admin@chupeymedeja.com intacto.

## Revisión

**Veredicto: done.**

Verificado con base temporal (esquema viejo con `categoria_id`, 2 insumos), arrancando dos veces:
- Migración: filas preservadas (tipo `otro`, unidad `unidad`, activo), segundo arranque sin error.
- Entrada 50 / 25000: stock 10 -> 60, `costo_unitario=500`, un movimiento `entrada` con `stock_resultante=60`.
- 422 con `cantidad=0` y `tipo` inválido; 404 en insumo inexistente; ajuste que deja stock negativo -> 400.
- Conteo con el mismo valor no crea movimiento; DELETE con movimientos -> 409, sin movimientos -> 204.
- Filtro de inactivos, `/movimientos?desde&hasta` y `/reportes/alertas-stock` responden bien.
- Stock y movimiento se guardan en una sola transacción (`registrar_movimiento` no hace commit).

Observaciones menores, no bloqueantes:
- `routers/insumos.py:198-203` valida `nuevo_stock < 0` con floats, y puede dar falsos negativos por redondeo. Es un caso raro.
- `registrar_gasto_de_entrada` es un no-op a propósito, como pide la tarea, y BE-032 lo completa.
- El chequeo de recetas en DELETE queda para BE-031, como está documentado.
