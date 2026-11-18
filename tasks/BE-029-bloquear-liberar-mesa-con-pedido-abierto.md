---
id: BE-029
title: "Bloquear POST /mesas/{id}/liberar cuando la mesa tiene un pedido abierto"
area: backend
status: done
priority: high
depends_on: [BE-025, BE-027]
created_by: planner
---

## Objetivo

Bug real confirmado por el dueño del negocio y reproducido con `curl` contra
el backend real: `POST /mesas/{id}/liberar` (`backend/app/routers/mesas.py`,
función `liberar_mesa`) hace `mesa.estado = ESTADO_LIBRE` sin ninguna
validación, incluso si esa mesa tiene una `Venta` con `estado ==
"abierta"` asociada (un pedido en curso, BE-025). Esto deja la mesa
visualmente `libre` mientras el pedido abierto sigue existiendo en la base
de datos, atado a esa mesa. Consecuencia reproducida: si después alguien
intenta `POST /ventas/abrir` en esa misma mesa (ahora viéndose libre), el
backend responde `409 "La mesa ya tiene un pedido abierto"` — confuso para
quien opera la caja, porque la UI decía que la mesa estaba libre, y la
mesa queda en un estado inconsistente (`libre` en la tabla `mesas`, pero
con un pedido `abierta` húerfano que nadie puede cerrar/descartar desde
`MesasView.vue` porque esa vista ya no la muestra como candidata a "Ver
pedido").

El botón "Marcar libre" (`POST /mesas/{id}/liberar`) es preexistente, de
antes de BE-025, pensado para liberar una mesa ocupada por una venta
directa de una sola pasada (`POST /ventas` con `mesa_id`, `estado:
"activa"`) que dejó la mesa `ocupada` sin ninguna acción explícita que la
libere. Ese caso de uso legítimo **debe seguir funcionando exactamente
igual que hoy** — el fix es exclusivamente para el caso nuevo introducido
por BE-025 (pedido `abierta`), que tiene sus propios finales explícitos
(`POST /ventas/{id}/cerrar` o `/descartar`, BE-027), ambos ya liberan la
mesa correctamente como parte de su lógica.

## Alcance

**Incluye**, en `backend/app/routers/mesas.py`:

- Helper nuevo (o reutilizar/adaptar `_contar_ventas` con un filtro
  adicional) que determine si una mesa tiene una `Venta` con `estado ==
  ESTADO_ABIERTA` asociada (importar `ESTADO_ABIERTA` de
  `app.models.venta`, mismo patrón que ya usa `ventas.py` para el chequeo
  de unicidad de `POST /ventas/abrir`).
- `liberar_mesa`: antes de asignar `mesa.estado = ESTADO_LIBRE`, si existe
  una `Venta` `abierta` para esa mesa, responder `409` con un mensaje claro
  y accionable (ej. `"No se puede liberar la mesa: tiene un pedido abierto.
  Usa 'Cobrar' o 'Descartar' desde el panel del pedido."`) — sin modificar
  la mesa ni la venta.
- Sin cambios en el caso de una mesa `ocupada` sin ningún pedido `abierta`
  (ej. por una venta directa `activa` preexistente, o simplemente marcada
  `ocupada` manualmente): `liberar_mesa` debe seguir liberándola
  exactamente igual que hoy, sin ningún `409` nuevo — no se está agregando
  ninguna restricción al caso de uso original de este endpoint.

**No incluye (fuera de alcance):**

- `PUT`/`PATCH /mesas/{id}` (`actualizar_mesa`): verificado por lectura de
  código que solo renombra (`mesa.nombre_o_numero`), sin tocar `estado` ni
  la mesa ni la venta — no necesita ningún ajuste, ya lo confirmó FE-037
  explícitamente (renombrar es independiente del estado de la mesa).
  Confirmar esto en las notas de implementación, no volver a implementarlo.
- `DELETE /mesas/{id}` (`_contar_ventas`): ya verificado explícitamente por
  BE-028 que cuenta **todas** las ventas de una mesa sin filtrar por
  `estado` (decisión de producto ya tomada: una venta `abierta` en una
  mesa sí debe seguir bloqueando el borrado, con el mensaje genérico ya
  existente `"tiene N venta(s) asociada(s)"`). No se toca ni se le agrega
  un mensaje específico distinto para el caso `abierta` — el mensaje
  genérico ya es correcto para un borrado (acción destructiva e
  infrecuente), a diferencia de "liberar" (acción operativa frecuente que
  sí amerita guiar explícitamente hacia `/cerrar`/`/descartar`).
- Cualquier cambio en `POST /ventas/{id}/cerrar` o `/descartar` (BE-027) —
  sin cambios, siguen siendo el camino correcto para terminar un pedido
  abierto.
- Cualquier cambio en el frontend — cubierto por una tarea de frontend
  aparte (FE-038) que además distingue en la UI, de forma proactiva, el
  motivo de ocupación de una mesa.

## Criterios de aceptación

- [ ] `POST /mesas/{id}/liberar` sobre una mesa con una `Venta` `estado ==
      "abierta"` asociada responde `409`, con un mensaje que mencione
      explícitamente el pedido abierto y guíe a usar cerrar/descartar; la
      mesa permanece `ocupada` y la venta permanece `abierta` (verificado
      con `GET /mesas/{id}` y `GET /ventas/{id}` después del intento
      fallido).
- [ ] `POST /mesas/{id}/liberar` sobre una mesa `ocupada` por una venta
      directa `activa` (sin ningún pedido `abierta`, ej. creada vía `POST
      /ventas` con `mesa_id`) sigue respondiendo `200` y libera la mesa
      exactamente igual que hoy — sin regresión del caso de uso original.
- [ ] `POST /mesas/{id}/liberar` sobre una mesa ya `libre` sigue
      respondiendo `200` sin error (idempotente, comportamiento actual sin
      cambios).
- [ ] `POST /mesas/{id}/liberar` con `mesa_id` inexistente sigue
      respondiendo `404`.
- [ ] `POST /mesas/{id}/liberar` sin header `Authorization` sigue
      respondiendo `401`.
- [ ] Reproducido explícitamente el escenario original del bug reportado
      (abrir pedido -> `liberar` -> ahora `409` en vez de `200` -> intentar
      `POST /ventas/abrir` sobre la misma mesa ya no da el `409` confuso
      porque la mesa nunca se marcó libre incorrectamente) con un caso de
      prueba real (`curl` o script), no solo por lectura de código.
- [ ] Confirmado y documentado en notas de implementación (sin cambiar
      código si no hace falta) que `PUT`/`PATCH /mesas/{id}` no necesita
      ajuste, y que `DELETE /mesas/{id}` ya está cubierto por la decisión
      de producto de BE-028.

## Notas de implementación

Implementado tal como está descrito en la tarea, sin desviaciones.

**Archivos tocados:**

- `backend/app/routers/mesas.py`:
  - Importa `ESTADO_ABIERTA` de `app.models.venta` (junto a `Venta`, ya
    importado).
  - Helper nuevo `_mesa_tiene_pedido_abierto(db, mesa_id)`: mismo patrón
    exacto que `_mesa_tiene_otra_venta_activa` (`ventas.py`) y el chequeo
    inline de unicidad de `POST /ventas/abrir` — `db.query(Venta.id)
    .filter(Venta.mesa_id == mesa_id, Venta.estado ==
    ESTADO_ABIERTA).first() is not None`. Se dejó como helper separado (no
    se reutilizó/adaptó `_contar_ventas`) porque `_contar_ventas` hace un
    `count()` sin filtrar por `estado` y la sigue usando tal cual
    `eliminar_mesa` (BE-028); mezclar ambos casos en una sola función habría
    requerido un parámetro opcional de filtro sin necesidad real, dado que
    solo hay dos consumidores con semánticas distintas.
  - `liberar_mesa`: después del chequeo de `404` y antes de asignar
    `mesa.estado = ESTADO_LIBRE`, si `_mesa_tiene_pedido_abierto(db,
    mesa_id)` es `True`, levanta `409` con detail `"No se puede liberar la
    mesa: tiene un pedido abierto. Usa 'Cobrar' o 'Descartar' desde el
    panel del pedido."` — sin tocar `mesa` ni ninguna `Venta`. El resto del
    endpoint (mesa ya libre, mesa ocupada sin pedido abierto, mesa
    inexistente) queda exactamente igual que antes.

**Confirmado por lectura de código (sin cambios, fuera de alcance según la
tarea):**

- `PUT`/`PATCH /mesas/{id}` (`actualizar_mesa`): solo reasigna
  `mesa.nombre_o_numero`; no toca `mesa.estado` ni ninguna `Venta`. No
  necesita ningún ajuste — confirmado, ya lo había verificado FE-037.
- `DELETE /mesas/{id}` (`_contar_ventas`, usado por `eliminar_mesa`): sigue
  contando **todas** las ventas de la mesa sin filtrar por `estado` (BE-028
  ya tomó la decisión de producto de que una venta `abierta` también debe
  bloquear el borrado con el mensaje genérico existente
  `"tiene N venta(s) asociada(s)"`). No se le agrega ningún mensaje
  específico para el caso `abierta` — el mensaje genérico es correcto para
  una acción destructiva e infrecuente, a diferencia de "liberar".

**Cómo se probó:** servidor `uvicorn` propio en un puerto de scratchpad
(primero `8329`, luego `8330` tras recrear la base para partir de datos
limpios — SQLite en Windows bloquea el archivo mientras el proceso lo tiene
abierto, así que hubo que matar el proceso anterior antes de borrar el
`.db`), con SQLite temporal propia (`SHEETS_SYNC_ENABLED=false`) y un
script Python (`requests`) encadenado. Nunca se tocó
`backend/brainfreeze.db` real ni el servidor real de `:8000` (confirmado
con `git status` al final: no aparece `brainfreeze.db` modificado).

Escenario del bug original reproducido exactamente como lo describe la
tarea:

1. `POST /mesas` -> mesa libre. `POST /ventas/abrir {"mesa_id": <id>}` ->
   `201`, `estado: "abierta"`, mesa pasa a `ocupada`.
2. `POST /mesas/{id}/liberar` -> **`409`**
   (`"No se puede liberar la mesa: tiene un pedido abierto. Usa 'Cobrar' o
   'Descartar' desde el panel del pedido."`), en vez del `200` que daba
   antes del fix.
3. Verificado que la mesa sigue `ocupada` y la venta sigue `abierta`
   después del intento fallido (sin efectos secundarios).
4. `POST /ventas/abrir` de nuevo sobre esa misma mesa -> sigue dando `409`
   (`"La mesa ya tiene un pedido abierto"`), pero ahora es **consistente**
   con el estado real de la mesa (nunca se marcó libre incorrectamente) en
   vez de confuso.

Caso legítimo (sin regresión) verificado en la misma corrida:

- Mesa nueva -> `POST /ventas` (venta directa `activa`, con `mesa_id`,
  cobrada de una sola pasada, sin pasar por `abierta`) -> mesa queda
  `ocupada`. `POST /mesas/{id}/liberar` -> sigue respondiendo **`200`** y
  libera la mesa (`estado: "libre"`) exactamente igual que antes del fix.
- `POST /mesas/{id}/liberar` sobre esa misma mesa ya `libre` -> sigue
  `200` (idempotente, sin cambios).
- `POST /mesas/{id}/liberar` con `mesa_id` inexistente -> `404`.
- `POST /mesas/{id}/liberar` sin header `Authorization` -> `401`.

Servidor y base de datos temporales detenidos/eliminados del scratchpad de
la sesión al finalizar (`netstat` confirmó que no quedan sockets
`LISTENING` en los puertos de prueba, solo conexiones cerradas en
`TIME_WAIT` que se limpian solas).

**Ejemplo de payload/curl para reproducir manualmente:**

```
POST /ventas/abrir {"mesa_id": 1}          -> 201, estado: "abierta"
POST /mesas/1/liberar                       -> 409 (antes del fix: 200)
POST /ventas/{id}/cerrar {"metodo_pago": "efectivo"}  -> 200, libera la mesa
POST /mesas/1/liberar                       -> 200 (ya no hay pedido abierto)
```

## Revisión

**Veredicto: done**

Código revisado en `backend/app/routers/mesas.py`: `_mesa_tiene_pedido_abierto`
usa el mismo patrón parametrizado (sin SQL crudo) que `_mesa_tiene_otra_venta_activa`
en `ventas.py`, `liberar_mesa` levanta `409` antes de tocar `mesa`/`venta`, y el
resto del endpoint (404, idempotencia en mesa libre, 401) queda intacto. `DELETE`
y `PUT/PATCH /mesas/{id}` confirmados sin cambios, correctamente fuera de alcance.

Verificado end-to-end contra el backend real (`:8000`, sin detenerlo), con un
usuario y dos mesas de prueba temporales (limpiados al final, incluido el
usuario y las filas de `ventas`/`mesas`; no se tocaron datos preexistentes):

- Mesa con pedido abierto (`POST /ventas/abrir`) → `POST /mesas/{id}/liberar`
  → `409` con el mensaje esperado; `GET /mesas` y `GET /ventas/{id}` confirman
  que la mesa sigue `ocupada` y la venta sigue `abierta` tras el intento fallido.
- Mesa ocupada por venta directa (`POST /ventas` con `mesa_id`) → `liberar` →
  `200`, sin regresión.
- Mesa ya libre → `liberar` → `200` (idempotente). Mesa inexistente → `404`.
  Sin `Authorization` → `401`.
- `descartar_venta` (sin items) y `cerrar_venta` sobre pedidos abiertos en la
  mesa de prueba siguen liberando la mesa correctamente (BE-027 no roto); antes
  de cerrar/descartar, `liberar` seguía dando `409` como se espera.

No hay linters/tests configurados en el proyecto backend (sin `ruff`/`mypy`/
`pytest` en `requirements.txt` ni carpeta de tests) — nada que correr ahí.
Todos los criterios de aceptación cumplidos.
