---
id: BE-035
title: Reporte de contabilidad — invertido y ganancia neta por periodo
area: backend
status: done
priority: medium
depends_on: [BE-032, BE-033, BE-034]
created_by: planner
---

## Objetivo

Mostrar en Contabilidad, para cualquier rango de fechas, cuánto se vendió,
cuánto se **invirtió** (todo lo gastado) y la **ganancia neta** real.

## Alcance

**Incluye:**

- `GET /reportes/contabilidad?desde=&hasta=` (default: mes local actual; 422 si
  `desde > hasta`) →
  ```
  {
    desde, hasta,
    ventas_total, ventas_efectivo, ventas_transferencia, num_ventas,
    invertido_total,
    invertido_por_categoria: [{categoria, etiqueta, total}],   // todas las categorías, 0 si no hay
    ganancia_neta,                // ventas_total − invertido_total
    margen_productos, margen_incompleto,   // el margen actual (precio − costo) como dato informativo
    valor_inventario_actual,      // Σ stock × costo_unitario de insumos activos con stock > 0 y costo
    por_dia: [{fecha, ventas, invertido, ganancia_neta}]   // todos los días del rango
  }
  ```
- Ventas: solo `activa` (mismo criterio que BE-023), por día local de `creado_en`.
- Invertido: suma de `gastos.monto` por `gastos.fecha` en el rango (incluye compras de inventario y nómina).
- Reutilizar `_margen_query` / helpers de timezone existentes en `reportes.py`.
- Documentar en el docstring que la ganancia neta es **base caja** (ventas −
  gastos del periodo): una compra grande de vasos baja la ganancia del día en
  que se compró, aunque se usen después. El margen de productos se mantiene como referencia.

**No incluye:** exportar a Excel, UI (FE-048).

## Criterios de aceptación

- [ ] Con ventas por 500.000 y gastos por 320.000 en el rango → `ganancia_neta = 180.000`.
- [ ] `invertido_por_categoria` devuelve todas las categorías y suma igual a `invertido_total`.
- [ ] Ventas canceladas y pedidos abiertos no cuentan.
- [ ] `por_dia` incluye días sin movimiento con ceros y suma igual a los totales.
- [ ] Rango inválido → 422.

## Notas de implementación

- `GET /reportes/contabilidad?desde=&hasta=` en `app/routers/reportes.py` (default: del día 1 del mes local a hoy local; `desde > hasta` -> 422). Schemas nuevos en `app/schemas/reporte.py` (`ReporteContabilidadOut`, `InvertidoPorCategoria`, `ContabilidadPorDia`).
- Ventas: solo `estado == activa` (las canceladas y `abierta` quedan fuera), agrupadas por día local de `creado_en` con `columna_creado_en_local`. Invertido: `Gasto.monto` por `Gasto.fecha` en el rango. Categorías/etiquetas tomadas de `ETIQUETAS_CATEGORIA` (gastos), sin duplicar; siempre salen las 7 en ese orden, con 0 si no hay gasto.
- `margen_productos`/`margen_incompleto` reutilizan `_margen_query` filtrado al rango. `valor_inventario_actual` = round(Σ stock × costo_unitario) de insumos activos con stock > 0 y costo definido.
- `por_dia` incluye todos los días del rango (ceros incluidos); `ganancia_neta = ventas - invertido` (base caja, documentado en el docstring).
- Sin dependencias, migraciones ni cambios de modelo.
- Prueba (base temporal, TestClient): abrí caja, 3 ventas (2 efectivo/transferencia activas de 10.000 en días distintos, 1 cancelada), 3 gastos (3.000 hoy; 2.000 y 1.000 hace 2 días). Rango de 4 días -> ventas_total 20.000, num_ventas 2 (la cancelada no cuenta), invertido_total 6.000, ganancia_neta 14.000, 7 categorías cuya suma = 6.000, 4 días en por_dia con sumas iguales a los totales, margen_productos 12.000, valor_inventario_actual 1.000 (excluye sin costo, stock 0 e inactivo). `desde > hasta` -> 422. Sin parámetros -> 2026-11-01..2026-11-18. No probé explícitamente un pedido abierto; queda excluido por el filtro `estado == activa`.

## Revisión

**Veredicto: done.** Verificado con base temporal propia (`review_be035.db`) y TestClient.

- Límites de día local: ventas a 23:59:59 local (día D) y 00:00:00 local (D+1) caen en el día correcto; una venta a 00:00:00 local de D queda en D y una a 23:59:59 de D-1 queda fuera del rango. Rango por día usa `inicio_dia_local_a_utc_naive`/`fin_dia_local_a_utc_naive` y agrupación con `columna_creado_en_local`.
- Pedido abierto (con 3 ítems agregados, total 3.000) y venta cancelada: no cuentan (ventas_total/num_ventas correctos).
- `por_dia` incluye todos los días del rango y suma igual a los totales; `invertido_por_categoria` devuelve las 7 categorías y suma `invertido_total`; ganancia_neta = ventas - invertido.
- `desde > hasta` -> 422; fecha inválida -> 422; sin token -> 401; sin parámetros -> 2026-11-01..2026-11-18 (mes local actual hasta hoy).
- Tipado/schemas correctos, sin SQL crudo, reutiliza `_margen_query` y helpers de timezone, docstring documenta base caja.

Observaciones menores (no bloquean):
- `reportes.py:343-344,371`: si existiera un gasto con categoría fuera de `ETIQUETAS_CATEGORIA` (dato legado), `invertido_total` lo incluiría pero `invertido_por_categoria` no, y no cuadrarían. Hoy el schema de gastos lo impide.
- Limitación preexistente (también en `/reportes/diario`): SQLite redondea `.9995+` s al segundo siguiente en `datetime()`, así que una venta a 23:59:59.9996 local se agruparía en el día siguiente. Irrelevante en la práctica.
- Sin tope de longitud de rango (`por_dia` crece con el rango); aceptable para uso interno.
