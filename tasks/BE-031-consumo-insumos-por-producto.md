---
id: BE-031
title: Consumo de insumos por producto y descuento automático de stock al vender
area: backend
status: done
priority: high
depends_on: [BE-030]
created_by: planner
---

## Objetivo

Que el inventario se mantenga solo: cada producto del menú declara qué
insumos consume por unidad vendida (ej. "Granizado 16oz" = 1 vaso 16oz + 1
tapa 16oz + 1 pitillo; "Cerveza Águila" = 1 Águila; "Michelada" = 1 cerveza
+ 1 vaso 12oz). Al quedar una venta como `activa`, se descuenta el stock; si se
cancela, se devuelve.

## Alcance

**Incluye:**

- Modelo nuevo `ProductoInsumo` (tabla `producto_insumos`): `id, producto_id (FK),
  insumo_id (FK), cantidad (float > 0)`, único por `(producto_id, insumo_id)`.
- `ProductoOut` agrega `insumos: [{insumo_id, nombre, unidad, cantidad}]`.
- `PUT /productos/{id}/insumos` body `[{insumo_id, cantidad}]` → reemplaza la
  lista completa (lista vacía = el producto no consume nada). Valida que los
  insumos existan (404/422 con mensaje claro), `cantidad > 0`, sin
  `insumo_id` repetidos (422). Devuelve `ProductoOut`.
- Servicio `app/services/inventario_service.py`:
  - `descontar_por_venta(db, venta)`: por cada item, por cada insumo de la
    receta **vigente**: crea movimiento `venta` con `cantidad = −(item.cantidad × receta.cantidad)`
    y `venta_id`, y actualiza el stock. Agrupar por insumo dentro de la misma venta (un movimiento por insumo).
  - `revertir_venta(db, venta)`: suma los movimientos `venta` + `reverso_venta`
    existentes de esa `venta_id` por insumo y crea un `reverso_venta` que los
    deja en cero. Se basa en lo realmente descontado, NO en la receta actual
    (la receta pudo cambiar después).
  - Ambas corren dentro de la misma transacción que el cambio de la venta.
- Puntos de integración en `app/routers/ventas.py`:
  - `POST /ventas` (venta directa `activa`) → `descontar_por_venta`.
  - `POST /ventas/{id}/cerrar` (abierta → activa) → `descontar_por_venta`.
  - `POST /ventas/{id}/cancelar` de una venta `activa` → `revertir_venta`.
  - `PUT /ventas/{id}` sobre una venta `activa` que cambia items →
    `revertir_venta` y luego `descontar_por_venta` con los items nuevos.
  - Pedidos `abierta` (`/abrir`, `/items`, cambio de cantidad, `/descartar`) **no** tocan stock.
- El stock puede quedar negativo: **nunca** se bloquea una venta por falta de
  stock (el estado queda `Crítico` y se ve en alertas).
- Insumos inactivos con receta siguen descontándose (la receta es la fuente de verdad).
- Borrar un producto borra sus filas de `producto_insumos`.

**No incluye:** UI (FE-044), costeo automático del producto a partir de los insumos.

## Criterios de aceptación

- [ ] Producto con receta {vaso16: 1, tapa16: 1}: venta directa de 3 unidades descuenta 3 y 3, con un movimiento `venta` por insumo ligado a la venta.
- [ ] Abrir pedido y agregar items no cambia el stock; al cerrarlo se descuenta.
- [ ] Descartar un pedido abierto no crea movimientos.
- [ ] Cancelar una venta activa devuelve exactamente lo descontado aunque la receta haya cambiado entre la venta y la cancelación.
- [ ] Editar una venta activa (de 3 a 1 unidad) deja el stock neto como si se hubiera vendido 1.
- [ ] Vender con stock 0 funciona y deja stock negativo.
- [ ] Producto sin receta no genera movimientos.
- [ ] Si falla la venta (ej. 409 por mesa), no queda ningún movimiento a medias.
- [ ] `PUT /productos/{id}/insumos` con insumo repetido → 422; con insumo inexistente → error claro; lista vacía → borra la receta.

## Notas de implementación

**Archivos**
- `app/models/producto.py`: nuevo `ProductoInsumo` (`producto_insumos`, único `(producto_id, insumo_id)`) y relación `Producto.insumos` con `cascade="all, delete-orphan"` (borrar producto borra su receta).
- `app/schemas/producto.py`: `ProductoInsumoIn`, `ProductoInsumoOut`; `ProductoOut.insumos: [{insumo_id, nombre, unidad, cantidad}]`.
- `app/routers/productos.py`: `PUT /productos/{id}/insumos` (reemplaza la receta completa).
- `app/routers/insumos.py`: `DELETE /insumos/{id}` ahora también devuelve 409 si el insumo está en alguna receta (pendiente de BE-030).
- `app/services/inventario.py`: **se extendió el servicio existente** (la tarea pedía `inventario_service.py`, pero ya existía `inventario.py` de BE-030) con `descontar_por_venta` y `revertir_venta`.
- `app/routers/ventas.py`: integración en `POST /ventas`, `/cerrar`, `/cancelar` (solo si estaba `activa`) y `PUT /ventas/{id}` (solo si está `activa`: revertir y descontar con los items nuevos). `/abrir`, `/items`, cambio de cantidad y `/descartar` no tocan stock.
- `app/db/base_all.py`: import de `ProductoInsumo`. Tabla nueva vía `create_all`, sin migración.

**Decisiones**
- Ambas funciones hacen `flush` pero nunca `commit`: viven en la misma transacción que el cambio de la venta (cualquier error previo o fallo del commit deja la BD sin movimientos).
- `descontar_por_venta` agrupa por insumo (suma entre items/productos) -> un movimiento `venta` por insumo, ligado a `venta_id`. Usa las recetas vigentes consultadas por `producto_id`.
- `revertir_venta` suma `venta` + `reverso_venta` por insumo de esa venta y crea un `reverso_venta` por el negativo del neto (omite netos 0); no mira la receta actual, por lo que es idempotente.
- Nunca se bloquea por stock; puede quedar negativo (`Crítico`). Insumos inactivos se descuentan igual.
- `PUT /productos/{id}/insumos`: duplicados -> 422; insumo inexistente -> 404 con la lista de ids; `cantidad <= 0` -> 422; producto inexistente -> 404; lista vacía borra la receta. Se hace `clear()` + `flush()` antes de insertar para no chocar con el único.
- El `PUT /ventas/{id}` sobre una venta `abierta` no toca stock.
- Duda menor: el criterio "falla la venta (ej. 409 por mesa)" no tiene hoy un 409 de mesa en `POST /ventas`; se probó con 404 (producto/mesa inexistentes) y con un fallo simulado de `Session.commit` (500), en ambos casos sin movimientos ni cambios de stock.

**Cómo se probó** (base temporal, mismo script `test_be031.py`, todo OK)
- Receta {vaso16:1, tapa16:1}, venta de 3 -> stock -3/-3, un movimiento `venta` por insumo con `venta_id`.
- Editar 3 -> 1: stock neto como si se vendió 1. Cambiar la receta y cancelar: devuelve exactamente lo descontado (el insumo nuevo de la receta queda en 0 movimientos). Segunda cancelación -> 409 sin movimientos extra.
- Venta con stock 0 -> 201, stock -10, estado `Crítico`. Abrir/agregar/cambiar cantidad/PUT sobre abierta/descartar: sin movimientos; cerrar descuenta (3x2=6). Producto sin receta: sin movimientos. Dos productos con el mismo insumo en una venta: un solo movimiento.
- Fallos: producto/mesa inexistentes (404) y commit forzado a fallar (500): sin movimientos ni cambio de stock.
- `PUT insumos`: repetido 422, inexistente 404, cantidad 0 422, vacía borra, reemplazo conservando un insumo OK. `DELETE` insumo en receta 409; sin receta ni movimientos 204; borrar producto elimina sus filas de `producto_insumos`; insumo inactivo se descuenta.
- Base real `chupeymedeja.db` (backup previo en el scratchpad): arrancada una vez, tablas `gastos` y `producto_insumos` creadas, usuario `admin@chupeymedeja.com` intacto.

## Revisión

**Veredicto: done** (revisor, 2026-11-17)

Verificado por lectura de `services/inventario.py:101-165`, `routers/ventas.py` (crear 138, PUT 258-261, cancelar 293-294, cerrar 462) y `routers/productos.py` (PUT insumos), y con pruebas propias en base temporal:
- Descuento/reverso sin commit propio: todo en la misma transaccion que la venta; abiertas (abrir, items, PUT sobre abierta, descartar) no tocan stock.
- Cancelar tras cambiar la receta devuelve lo realmente descontado (A restaurado, B sin movimientos extra); segunda cancelacion 409 sin movimientos; editar venta cancelada 409.
- Editar activa 2->1 con receta cambiada: revierte lo viejo y descuenta con la receta vigente (stock neto correcto).
- Cerrar descuenta; cancelar tras cerrar revierte; PUT receta: repetido 422, inexistente 404 con ids, cantidad 0 422, lista vacia limpia.
- Nota (no bloqueante): el criterio "409 por mesa" no existe en POST /ventas; la atomicidad queda cubierta por la ausencia de commit intermedio.
