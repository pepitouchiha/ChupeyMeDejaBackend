---
id: BE-024
title: Corregir manejo de zona horaria en reportes y filtros de fecha de ventas (bug real de dashboard)
area: backend
status: done
priority: high
depends_on: [BE-007, BE-020, BE-023]
created_by: planner
---

## Objetivo

Bug real confirmado por el usuario en producción/desarrollo: hizo una venta y
el dashboard no mostró "ventas de hoy" ni "ganancias de hoy" ni "total
vendido hoy". Causa raíz confirmada consultando la base de datos de
desarrollo directamente: `Venta.creado_en` (`app/models/venta.py:35-37`) se
guarda con `datetime.now(timezone.utc)`, pero SQLAlchemy/SQLite descartan el
`tzinfo` al persistir en una columna `DateTime` genérica, quedando un
timestamp **naive-UTC** en la base. Sin embargo `reporte_hoy` y
`reporte_mensual` (`app/routers/reportes.py`) y `listar_ventas`
(`app/routers/ventas.py`, filtros `desde`/`hasta`) calculan "hoy"/rangos con
`date.today()` — **hora local del servidor** (Colombia, UTC-5, sin horario
de verano) — y comparan ese rango directamente contra `creado_en` sin
convertir, tratándolo implícitamente como si ya estuviera en hora local.

Ejemplo real verificado en esta sesión: una venta hecha a las 19:42 hora
local (Colombia) quedó guardada como `2026-09-06 00:42:23` (ya "mañana" en
términos UTC). `reporte_hoy` de ese mismo día filtra por
`[2026-09-05 00:00:00, 2026-09-05 23:59:59]` (naive, sin conversión) — la
venta cae fuera de ese rango y desaparece de "hoy" pese a haberse hecho hoy.
Cualquier venta después de aprox. las 7:00pm hora local sufre este problema.
Ya estaba documentado como limitación conocida y no bloqueante en la sección
`## Revisión` de `BE-007` ("Observación menor... Lo dejo anotado por si el
planner decide estandarizar el manejo de timezone en una tarea aparte") —
esta es esa tarea.

Se debe corregir de raíz y de forma **consistente** en todos los lugares
afectados, no como parche puntual solo en `/reportes/hoy`.

## Alcance

**Incluye:**

- `backend/app/core/config.py`: agregar una zona horaria de negocio fija,
  ej. `BUSINESS_TIMEZONE = ZoneInfo("America/Bogota")` (de `zoneinfo`,
  librería estándar — preferible a un offset numérico "mágico" tipo
  `timedelta(hours=-5)` porque es auto-documentado; Colombia no tiene
  horario de verano, así que el offset es fijo, pero usar `ZoneInfo` no
  cuesta nada extra y es más robusto/explícito).
- Un lugar central (puede ser un módulo nuevo, ej.
  `backend/app/core/timezone.py`, o funciones en `config.py` — decisión del
  implementador) con helpers reutilizables para:
  - Calcular los límites de "hoy" en hora local y convertirlos a los
    naive-UTC equivalentes que se comparan contra `Venta.creado_en` (mismo
    truco que ya usa el modelo: construir el instante local con `tzinfo`,
    convertir a UTC con `.astimezone(timezone.utc)`, y descartar el
    `tzinfo` con `.replace(tzinfo=None)` antes de comparar contra la
    columna naive).
  - Lo mismo para límites de mes/año (usados por `reporte_mensual` y
    `ytd_total`/`ytd_margen`).
  - Convertir un `creado_en` naive-UTC ya leído de la base a su hora local
    (para mostrar, ej., la hora correcta en `por_hora`).
- `backend/app/routers/reportes.py`:
  - `reporte_hoy`: calcular "hoy" (`date` a devolver en `fecha` y los
    límites de la query) en hora **local**, convertir esos límites a UTC
    para filtrar `Venta.creado_en`. El desglose `por_hora` debe agrupar por
    la **hora local** de cada venta (hoy usa `venta.creado_en.hour`
    directamente sobre el valor UTC — ese es otro síntoma visible del mismo
    bug: una venta de las 7pm local aparecería en el bucket de la hora 0 de
    UTC, no en el bucket 19).
  - `reporte_mensual`: la agrupación por mes vía `func.strftime("%Y"/"%m",
    Venta.creado_en)` agrupa directamente sobre el valor UTC de la columna
    — para una venta cerca de medianoche local que cruza a un mes/año UTC
    distinto, quedaría en el mes/año incorrecto. Ajustar para que la
    agrupación (ya sea trasladando el filtro/cálculo a hora local antes de
    llamar a `strftime`, o ajustando el valor comparado) refleje el mes
    calendario **local**. El cálculo de `ytd_total`/`ytd_margen`
    (`inicio_anio_actual = datetime.combine(date(hoy.year, 1, 1),
    time.min)`) debe partir del 1 de enero **local**, convertido a UTC.
  - `_calcular_margen`/`_margen_por_mes`/`_margen_query`: no cambian su
    lógica de negocio (siguen filtrando por `ESTADO_ACTIVA`, BE-023), solo
    reciben límites ya corregidos a UTC desde las funciones que los llaman.
- `backend/app/routers/ventas.py`:
  - `listar_ventas`: los filtros `desde`/`hasta` (`date`) deben interpretarse
    como límites del día en hora **local** y convertirse a UTC antes de
    comparar contra `Venta.creado_en`, mismo criterio que `reporte_hoy`. Esto
    afecta también a la pantalla de Órdenes del frontend (FE-028), que
    consume este mismo endpoint con esos filtros.
- Verificado y **decidido incluir en esta tarea** (mismo origen del bug, bajo
  costo de arreglar): `backend/app/services/sheets_service.py`,
  `sync_venta_to_sheets` escribe `venta.get("creado_en")` (que viene de
  `venta.creado_en.isoformat()` en `_venta_a_dict_para_sheets`,
  `app/routers/ventas.py`) tal cual — un string ISO naive-UTC — directamente
  en la hoja de cálculo de Google Sheets usada para contabilidad. Convertir
  ese valor a hora local antes de armar el dict que se pasa a
  `sync_venta_to_sheets`, para que la hoja de cálculo (pensada para el
  negocio, en Colombia) muestre la hora real en que ocurrió la venta, no UTC.

**No incluye (fuera de alcance):**

- Migrar datos existentes: los timestamps ya guardados en `creado_en` siguen
  siendo correctos en UTC — solo cambia **cómo se interpretan al
  filtrar/agrupar/mostrar**, no se reescribe ningún dato.
- Cambiar el tipo de columna de `Venta.creado_en` a `DateTime(timezone=True)`
  ni almacenar el offset junto con el dato — se mantiene el modelo de
  almacenamiento actual (naive-UTC), solo se corrige la capa de
  consulta/presentación.
- Cambiar el campo `creado_en` expuesto en `VentaOut`
  (`app/schemas/venta.py`) ni cómo lo consume/formatea el frontend (ej. la
  columna de fecha/hora en la pantalla de Órdenes, FE-028) — eso es un
  contrato de API y una decisión de frontend aparte; si el frontend necesita
  que `creado_en` venga con offset explícito o ya convertido a hora local
  para mostrarlo directamente, es una tarea nueva del planner, no se
  improvisa aquí.
- Hacer la zona horaria de negocio configurable por el usuario final (multi-
  tienda, multi-timezone) — un valor fijo en `config.py` es suficiente para
  el alcance actual (un solo local en Colombia).

## Criterios de aceptación

- [ ] Caso equivalente al bug reportado: insertar (o crear vía `POST
      /ventas` con el reloj del sistema ajustado, o insertando directamente
      en SQLite) una venta cuyo `creado_en` UTC corresponda a una hora local
      de Colombia después de las 7pm de un día local dado (cruza medianoche
      UTC, ej. `creado_en` naive-UTC `2026-09-06 00:42:23` para una venta
      hecha a las 19:42 hora local del 2026-09-05). `GET /reportes/hoy`
      pedido durante el 2026-09-05 hora local debe incluir esa venta en
      `total`/`num_ventas`, con `fecha` = `2026-09-05`.
- [ ] La misma venta del criterio anterior aparece en el bucket `hora: 19` de
      `por_hora` (hora local), no en el bucket `hora: 0`.
- [ ] Caso borde de límite: una venta creada exactamente a las 00:00:00 hora
      local cae en el día local correcto (no en el día anterior); una venta
      creada a las 23:59:59 hora local también cae en el día local correcto
      (no en el día siguiente).
- [ ] `GET /reportes/mensual`: una venta creada en hora local cercana a fin
      de mes que, interpretada en UTC, caería en el mes/año siguiente, se
      agrupa en el mes/año **local** correcto (verificado con un caso
      numérico concreto, no solo por lectura de código).
- [ ] `ytd_total` y `ytd_margen` se calculan desde el 1 de enero **local**
      del año en curso — una venta de la noche del 31 de diciembre hora
      local que en UTC ya sería 1 de enero no debe excluirse del año
      anterior ni incluirse de más en el nuevo (verificar con un caso
      concreto).
- [ ] `GET /ventas?desde=&hasta=`: con el mismo caso del primer criterio
      (venta de las 19:42 hora local del 2026-09-05), pedir
      `?desde=2026-09-05&hasta=2026-09-05` la incluye; pedir
      `?desde=2026-09-06&hasta=2026-09-06` NO la incluye.
- [ ] Regresión: ventas creadas en horas que no cruzan medianoche UTC (ej.
      hora local de la mañana/mediodía en Colombia) se siguen contando en el
      mismo día/mes/hora que antes de esta tarea (sin sobre-corrección ni
      desplazamiento doble).
- [ ] `_margen_query`/`ESTADO_ACTIVA` (BE-023) y el filtro `estado` de
      `listar_ventas` (BE-020) siguen funcionando exactamente igual que antes
      — esta tarea no reintroduce ventas canceladas en los totales ni cambia
      el comportamiento de `?estado=`.
- [ ] `sync_venta_to_sheets` recibe y escribe el `creado_en` de una venta
      convertido a hora local de Colombia (verificable comparando el valor
      que se le pasa a la función contra la hora local esperada para un
      `creado_en` UTC conocido que cruce medianoche).
- [ ] No se modifica ningún dato ya persistido en `creado_en` (no hay
      script de migración de datos; solo cambia la lógica de
      consulta/agrupación/presentación).
- [ ] `GET /reportes/hoy`, `GET /reportes/mensual` y `GET /ventas` sin header
      `Authorization` siguen devolviendo `401` (sin regresión).

## Notas de implementación

**Archivos tocados:**

- `backend/app/core/config.py`: agregada `BUSINESS_TIMEZONE = ZoneInfo("America/Bogota")`.
- `backend/app/core/timezone.py` (nuevo): helpers centralizados —
  `hoy_local()`, `inicio_dia_local_a_utc_naive(dia)`,
  `fin_dia_local_a_utc_naive(dia)`, `limites_dia_local(dia)`,
  `utc_naive_a_local(valor)` y `columna_creado_en_local(columna)` (expresión
  SQL `func.datetime(columna, '<offset> minutes')` para agrupar por
  mes/año **local** con `strftime` sin traer todas las filas a Python). El
  offset del modifier de SQLite se deriva de `BUSINESS_TIMEZONE.utcoffset()`
  en vez de hardcodear `"-5 hours"`, para que quede conectado a la constante
  de config.
- `backend/app/routers/reportes.py`: `reporte_hoy` usa `hoy_local()` +
  `limites_dia_local()` para calcular `fecha`/rango de la query, y
  `utc_naive_a_local(venta.creado_en).hour` para el bucket de `por_hora`
  (antes usaba `venta.creado_en.hour` directo sobre UTC). `reporte_mensual`
  agrupa por mes/año usando `columna_creado_en_local()` en el `strftime`
  tanto en la query principal como en `_margen_por_mes`; `inicio_anio_actual`
  ahora sale de `inicio_dia_local_a_utc_naive(date(hoy.year, 1, 1))` con
  `hoy = hoy_local()`. `_margen_query`/`_calcular_margen`/`ESTADO_ACTIVA`
  (BE-023) no cambiaron su lógica, solo reciben límites ya corregidos.
- `backend/app/routers/ventas.py`: `listar_ventas` convierte `desde`/`hasta`
  con `inicio_dia_local_a_utc_naive`/`fin_dia_local_a_utc_naive` antes de
  filtrar; no se tocó el filtro `estado`/exclusión de canceladas (BE-020/
  BE-023, que vive en otro nivel). `_venta_a_dict_para_sheets` ahora escribe
  `utc_naive_a_local(venta.creado_en).isoformat()` en vez del valor UTC
  crudo, así `sync_venta_to_sheets` recibe la hora local de Colombia.
- `backend/requirements.txt`: agregado `tzdata==2026.3` — **desviación
  necesaria del alcance original**: `zoneinfo.ZoneInfo("America/Bogota")` se
  probó en el venv real del proyecto (`.venv`) y falló con
  `ZoneInfoNotFoundError` porque Windows no trae datos IANA de zona horaria
  y no había paquete `tzdata` instalado (solo existía uno global fuera del
  venv, instalado por otro proyecto ajeno). Sin esto, el servidor con
  `--reload` se habría roto al recargar `config.py`. Se instaló `tzdata` en
  `.venv` y se agregó a `requirements.txt` para que sea reproducible; se
  verificó que el servidor real en `:8000` siguió respondiendo 200 después
  del cambio. Aviso explícito porque la tarea decía "sin dependencias
  nuevas" asumiendo que `zoneinfo` no las necesitaría — en Linux/mac
  normalmente no hace falta (usan tzdata del sistema), pero en Windows sí.

**Verificación del caso del bug (BD SQLite temporal, no se tocó
`brainfreeze.db`):** script standalone que crea una BD en
`%TEMP%\be024_test.db`, inserta ventas con `creado_en` naive-UTC directo
(sin pasar por reloj del sistema) y llama las funciones de los routers
directamente:

- Venta con `creado_en = 2026-09-06 00:42:23` (=19:42 hora Bogotá del
  2026-09-05): `reporte_hoy()` simulando `hoy_local() = 2026-09-05` la
  incluye (`fecha=2026-09-05`, `total`/`num_ventas` correctos) y cae en el
  bucket `hora=19` de `por_hora` (no `hora=0`).
- Bordes: venta a las 00:00:00 local (`05:00:00` UTC) cae en bucket `hora=0`
  del día correcto; venta a las 23:59:59 local (`04:59:59` UTC del día
  siguiente) cae en bucket `hora=23` del día correcto (no se corre al día
  siguiente).
- `GET /ventas?desde=2026-09-05&hasta=2026-09-05` incluye la venta de las
  19:42 local; `?desde=2026-09-06&hasta=2026-09-06` no la incluye.
- `reporte_mensual`: venta con `creado_en = 2026-09-01 04:30:00` UTC
  (=2026-08-31 23:30 hora local) se agrupó en **agosto 2026** (mes local),
  no septiembre (mes UTC).
- `ytd_total`/`ytd_margen` (simulando `hoy_local() = 2026-01-05`): venta con
  `creado_en = 2026-01-01 04:00:00` UTC (=2025-12-31 23:00 hora local)
  queda excluida del YTD 2026 (`inicio_dia_local_a_utc_naive(2026-01-01)` =
  `2026-01-01 05:00:00` UTC, posterior al `creado_en` de esa venta).
- Regresión: ventas de mediodía local (sin cruzar medianoche UTC) se
  siguen contando en el mismo día/mes/hora que antes.
- Venta cancelada de "hoy" sigue excluida de `reporte_hoy`/`reporte_mensual`
  (BE-023 intacto); `GET /ventas` sin `?estado=` sigue devolviendo también
  las canceladas (comportamiento de BE-020 sin cambios).
- `_venta_a_dict_para_sheets` para la venta de las 19:42 local devuelve
  `"2026-09-05T19:42:23-05:00"` (antes hubiera sido el string UTC crudo
  `"2026-09-06T00:42:23"`).
- `GET /reportes/hoy`, `GET /reportes/mensual`, `GET /ventas` sin header
  `Authorization` (levantando uvicorn temporal en `:8123` contra otra BD
  temporal) siguen devolviendo `401`.

**Cómo reproducir:** el script de verificación es ad-hoc (no quedó en el
repo, viviría en `scratchpad`, fuera del proyecto). Para repetir manualmente
via API: crear una venta un día después de las 7pm hora Bogotá (o insertar
directo en una BD SQLite temporal un registro con `creado_en` UTC que cruce
medianoche) y pedir `GET /reportes/hoy` — debe aparecer en `total`/
`num_ventas` con la hora correcta en `por_hora`.

**No incluido (fuera de alcance, como decía la tarea):** no se migró ningún
dato de `creado_en` ya persistido; no se cambió el tipo de columna ni el
contrato de `VentaOut.creado_en` (sigue naive-UTC tal cual lo devuelve la
API; el frontend sigue recibiendo el mismo formato que antes).

## Revisión

**Veredicto: `done`**

Código revisado (`app/core/config.py`, `app/core/timezone.py`, `app/routers/reportes.py`,
`app/routers/ventas.py`, `requirements.txt`) y verificado con pruebas reales contra una
BD SQLite temporal (`%TEMP%\...\scratchpad\be024_test.db`, no se tocó `brainfreeze.db`),
importando y ejecutando directamente las funciones de los routers (sin levantar
servidor) con `hoy_local` parcheado para simular distintos "hoy":

- Caso crítico del bug: venta `creado_en=2026-09-06 00:42:23` UTC (19:42 Bogotá del
  09-05). Con `hoy_local()` simulado a `2026-09-05`, `reporte_hoy()` la incluye
  (`fecha=2026-09-05`, contribuye a `total`/`num_ventas`) y cae en el bucket
  `hora=19` de `por_hora` (no `hora=0`). Confirmado.
- Bordes 00:00:00 y 23:59:59 local: caen en el día local correcto (buckets `hora=0`
  y `hora=23` respectivamente), sin correrse al día siguiente/anterior.
- `reporte_mensual`: venta `creado_en=2026-09-01 04:30:00` UTC (=2026-08-31 23:30
  local) se agrupó en **agosto 2026**, no septiembre — verificado con datos reales,
  no solo lectura de código.
- Límite de año: venta `creado_en=2026-01-01 04:00:00` UTC (=2025-12-31 23:00 local)
  se agrupó en **diciembre 2025**, confirmando que `ytd_total`/`ytd_margen` (que parten
  de `inicio_dia_local_a_utc_naive(1 de enero local)`) no la incluyen de más en 2026.
- `GET /ventas?desde=2026-09-05&hasta=2026-09-05` incluye la venta de las 19:42 local;
  `?desde=2026-09-06&hasta=2026-09-06` no la incluye.
- Regresión: venta de mediodía local (sin cruzar medianoche UTC) se sigue contando
  igual que antes.
- BE-023 intacto: venta cancelada de "hoy" queda excluida de `reporte_hoy` (`total`
  solo suma las 4 ventas activas de ese día, no la 5ª cancelada). BE-020 intacto:
  `listar_ventas(estado=EstadoVenta.cancelada)` y `estado=EstadoVenta.activa` filtran
  correctamente; sin filtro `estado`, siguen apareciendo también las canceladas.
- `_venta_a_dict_para_sheets` para la venta de las 19:42 local devuelve
  `"2026-09-05T19:42:23-05:00"` (hora local con offset), no el string UTC crudo.
- `dependencies=[Depends(require_auth)]` a nivel de router se mantiene sin cambios en
  `reportes.py`/`ventas.py` — sin regresión en el 401 sin `Authorization`.
- `tzdata` verificado instalado y funcional en `.venv` (`ZoneInfo("America/Bogota")`
  resuelve sin error); la desviación de alcance (dependencia nueva) está bien
  justificada y documentada.
- No se modificó ningún dato persistido; no se tocó el contrato de `VentaOut.creado_en`.

No se corrieron `ruff`/`mypy` porque no hay configuración ni esas herramientas
instaladas en el proyecto (no hay `pyproject.toml`/`ruff.toml`/`mypy.ini`, tampoco
están en el venv) — no es una regresión de esta tarea.

Sin hallazgos. Los 12 criterios de aceptación se cumplen.
