---
id: BE-036
title: Configuración del negocio para comandas y facturas impresas
area: backend
status: done
priority: high
depends_on: []
created_by: planner
---

## Objetivo

Las comandas y facturas (FE-049) se imprimen desde el navegador en una
impresora térmica de 80mm y necesitan los datos del negocio en el
encabezado/pie. Esta tarea guarda esos datos y las preferencias de impresión.

## Alcance

**Incluye:**

- Modelo `ConfiguracionNegocio` (tabla `configuracion_negocio`, una sola fila
  `id=1`, creada con valores por defecto si no existe): `nombre_negocio
  (default "ChupeyMeDeja"), nit (nullable), direccion, telefono, mensaje_pie
  (default "¡Gracias por su compra!"), imprimir_comanda_auto (bool, default
  true), imprimir_factura_auto (bool, default false), ancho_papel_mm (58 | 80, default 80)`.
- `GET /configuracion/negocio` y `PUT /configuracion/negocio` (con `require_auth`, validaciones de longitud).
- `VentaOut` agrega (si no los tiene) lo necesario para imprimir sin más
  llamadas: `mesa_nombre` (nullable) y, en cada item, `nombre_producto`.
  Verificar qué ya devuelve hoy antes de agregar.

**No incluye:** facturación electrónica DIAN (el ticket es un recibo / factura de venta simple), UI (FE-049).

## Criterios de aceptación

- [ ] `GET` en una base nueva devuelve los valores por defecto sin error.
- [ ] `PUT` persiste y un `GET` posterior lo refleja; `ancho_papel_mm` distinto de 58/80 → 422.
- [ ] `GET /ventas/{id}` trae nombre de mesa y nombre de cada producto.

## Notas de implementación

**Archivos nuevos:** `app/models/configuracion_negocio.py`, `app/schemas/configuracion_negocio.py`, `app/routers/configuracion.py`.
**Editados:** `app/db/base_all.py` y `app/main.py` (registro), `app/models/venta.py` (relaciones `viewonly` `Venta.mesa` y `VentaItem.producto` + propiedades `mesa_nombre` / `nombre_producto`), `app/schemas/venta.py`.

Decisiones:
- Sin migración: la tabla es nueva y `create_all` la crea al arrancar. La fila `id=1` se crea con defaults de forma perezosa en el primer GET/PUT (no en el arranque).
- `PUT` reemplaza todos los campos (semántica PUT). Los campos opcionales de texto se recortan y "" pasa a `null`. `nombre_negocio` obligatorio (1-100). Límites: nit 30, direccion 200, telefono 30, mensaje_pie 200. `ancho_papel_mm` es `Literal[58, 80]` (422 si no) y además hay CHECK en BD.
- `VentaOut` no tenía `mesa_nombre` ni `nombre_producto`; se agregaron (`VentaOut.mesa_nombre: str | None`, `VentaItemOut.nombre_producto: str`). Aplica a todos los endpoints que devuelven `VentaOut`. Lazy load por item (N+1 menor, aceptable en SQLite/dev).

Pruebas (TestClient sobre BD temporal, httpx instalado solo en el scratchpad, no en el venv):
- GET sin token -> 401; GET en BD nueva -> defaults (ChupeyMeDeja, 80mm, comanda auto true, factura auto false, mensaje "¡Gracias por su compra!").
- PUT válido -> 200 y GET posterior refleja los cambios; `ancho_papel_mm=70` -> 422; nombre de 101 chars -> 422.
- `POST /ventas` con mesa y `GET /ventas/{id}` -> `mesa_nombre: "Mesa 7"`, item con `nombre_producto: "Malteada"`; venta sin mesa -> `mesa_nombre: null`; `GET /ventas` lista bien.

Ejemplo: `PUT /configuracion/negocio` `{"nombre_negocio":"Mi Local","nit":"900-1","direccion":"Calle 1","telefono":null,"mensaje_pie":"Chao","imprimir_comanda_auto":false,"imprimir_factura_auto":true,"ancho_papel_mm":58}`

## Revisión

**Veredicto: done.**

Verificado con base temporal:
- `GET /configuracion/negocio` en base nueva devuelve los defaults (ChupeyMeDeja, 80mm, comanda auto true, factura auto false, mensaje de pie por defecto) y crea la fila `id=1`.
- `PUT` persiste. Un nombre en blanco da 422. Un `nit` de solo espacios se normaliza a `null`. `ancho_papel_mm` es `Literal[58, 80]` y además tiene CHECK en la base.
- `VentaOut.mesa_nombre` y `VentaItemOut.nombre_producto` salen de relaciones `viewonly` y funcionan con `from_attributes`. El código es coherente con `Mesa.nombre_o_numero`.
- Los routers `configuracion` e `insumos` están registrados en `main.py` y el arranque funciona.

Observaciones menores, no bloqueantes:
- `PUT` reemplaza todos los campos. Si el cliente omite `mensaje_pie`, queda en `null` y no vuelve al default. Es coherente con la semántica PUT y está documentado.
- La carga perezosa de `producto` por item es un N+1 menor y se acepta en SQLite.
