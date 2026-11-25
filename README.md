# Chupe y Me Deja — Backend

API REST del punto de venta de **Chupe y Me Deja** (granizados y bebidas), con
dos sedes en Copacabana: Asunción y Machado. Maneja menú, inventario, mesas,
caja, ventas, gastos, personal y contabilidad, **separados por sede**.

**FastAPI + SQLAlchemy 2.0 + PostgreSQL (Supabase)**, autenticación con **JWT**.
En desarrollo local puede usar SQLite sin instalar nada más.

La guía para publicarlo en internet está en [`DESPLIEGUE.md`](DESPLIEGUE.md).

## Cómo funcionan las sedes (multi-tenant)

- Cada sede es un *tenant*: tiene sus propias categorías, productos, insumos,
  mesas, caja, ventas, gastos, trabajadores y configuración de impresión.
- Todas las tablas de negocio heredan `SedeScoped` (`app/models/sede.py`) y
  tienen columna `sede_id`.
- `app/db/tenancy.py` agrega `WHERE sede_id = <sede activa>` a **todas** las
  consultas del ORM y asigna `sede_id` al crear registros. Si una consulta toca
  datos de sede sin sede activa, falla en vez de devolver datos de todas.
- La sede activa la fija `require_sede` (`app/core/security.py`):
  - **Administrador y cajero:** siempre su sede; no pueden pedir otra.
  - **Super admin y dueño:** eligen la sede con el encabezado `X-Sede-Id`.

## Usuarios y roles

| Rol | Qué puede hacer | Quién crea la cuenta |
|---|---|---|
| `superadmin` | Todo. Crea sedes y cuentas de dueño, administrador y cajero. | Solo el comando `crear_superadmin` |
| `dueno` | Opera todas las sedes. Crea cajeros en cualquier sede. | Super admin |
| `administrador` | Todo dentro de su sede: menú, inventario, gastos, trabajadores, contabilidad, configuración, editar o cancelar ventas. Crea cajeros de su sede. | Super admin |
| `cajero` | Operar su sede: vender, mesas, abrir y cerrar caja, ver órdenes y registrar gastos. | Super admin, dueño o administrador de su sede |

- **Sin registro público:** no existe ningún endpoint para crear cuentas sin
  sesión. El super admin se crea con `python -m app.scripts.crear_superadmin`
  y nadie puede crear, editar ni eliminar un super admin desde la app.
- **Login:** `POST /auth/login` devuelve el JWT, el usuario y sus sedes.
  Se bloquea 15 minutos tras 5 intentos fallidos desde la misma IP y correo.
- **Revocación:** cambiar la contraseña, desactivar la cuenta o cambiarle el
  rol o la sede invalida los tokens anteriores (`token_version`).

## Estructura

```
app/
  main.py          app FastAPI, CORS, cabeceras de seguridad, routers
  core/            config (.env), security (JWT, roles, sede activa), timezone
  db/              session, base, tenancy (filtro por sede)
  models/          modelos SQLAlchemy (Sede, Usuario, Venta, Producto, ...)
  schemas/         schemas Pydantic
  routers/         endpoints (auth, usuarios/sedes, ventas, caja, ...)
  services/        caja, inventario, sedes
  scripts/         crear_superadmin (cuenta inicial / recuperar acceso), seed_productos (datos de ejemplo)
tests/             pruebas de aislamiento por sede, roles y autenticación
render.yaml        despliegue en Render
```

## Desarrollo local

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements-dev.txt
copy .env.example .env
.\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

Sin `DATABASE_URL`, usa SQLite en `backend/chupeymedeja.db`. Las tablas se
crean solas al arrancar. Crea tu cuenta de super admin y las sedes:

```powershell
.\.venv\Scripts\python -m app.scripts.crear_superadmin tu@correo.com --nombre "Tu nombre" --sede "Asunción|Copacabana" --sede "Machado|Copacabana"
```

Pruebas:

```powershell
.\.venv\Scripts\python -m pytest -q
```

Para correrlas contra PostgreSQL, define `TEST_DATABASE_URL` con una base
vacía y desechable.

## Variables de entorno

| Variable | Descripción |
|---|---|
| `ENVIRONMENT` | `development` (por defecto) o `production`. En producción exige `DATABASE_URL` y un `JWT_SECRET_KEY` propio de 32+ caracteres, y oculta `/docs`. |
| `DATABASE_URL` | Cadena de conexión. En producción, la de Supabase (*Session pooler*). |
| `CORS_ORIGINS` | Orígenes permitidos separados por coma, ej. `https://chupeymedeja.netlify.app`. |
| `JWT_SECRET_KEY` | Secreto para firmar los tokens. |
| `JWT_EXPIRE_MINUTES` | Duración de la sesión (por defecto 720 = 12 horas). |
| `LOGIN_MAX_INTENTOS`, `LOGIN_BLOQUEO_MINUTOS` | Límite de intentos de login (por defecto 5 y 15). |
| `BUSINESS_TIMEZONE` | Zona horaria del negocio (por defecto `America/Bogota`). |

## Recuperar el acceso

- **Super admin:** vuelve a correr `crear_superadmin` con tu correo (y
  `DATABASE_URL` apuntando a producción); pone la nueva contraseña y cierra
  las sesiones anteriores.
- **Dueños y administradores:** el super admin les restablece la contraseña en **Usuarios**.
- **Cajeros:** el super admin, el dueño o el administrador de su sede.

## Cambios de esquema

Las tablas se crean con `create_all` al arrancar. Eso **crea tablas nuevas pero
no modifica tablas existentes**. Si más adelante se agrega una columna a una
tabla que ya tiene datos en Supabase, hay que aplicar el cambio con SQL o
incorporar Alembic.
