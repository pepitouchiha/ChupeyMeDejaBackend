# Publicar Chupe y Me Deja en internet

Tres servicios, todos con plan gratuito:

| Pieza | Servicio | Qué hace |
|---|---|---|
| Base de datos | **Supabase** | PostgreSQL con respaldo en la nube |
| Backend (API) | **Render** | Corre FastAPI |
| Frontend (la app) | **Netlify** | Sirve la página que se abre en el celular o el PC |

Orden: **Supabase → Render → Netlify → volver a Render (CORS) → crear tu cuenta de super admin**.

Necesitas los dos repositorios (`backend/` y `frontend/`) subidos a GitHub.

---

## 1. Supabase (base de datos)

1. Entra a <https://supabase.com>, crea una cuenta y un proyecto nuevo.
   - **Region:** `East US (North Virginia)`, la más cercana a Colombia.
   - **Database password:** genera una fuerte y **guárdala**.
2. Cuando el proyecto esté listo, pulsa **Connect** (arriba).
3. En **Connection string**, elige **Session pooler** (no *Direct connection*:
   Render no tiene IPv6 y esa no le funciona).
4. Copia la cadena. Se ve así:
   ```
   postgresql://postgres.abcdefgh:[YOUR-PASSWORD]@aws-0-us-east-1.pooler.supabase.com:5432/postgres
   ```
5. Reemplaza `[YOUR-PASSWORD]` por la contraseña del paso 1. Esta es tu `DATABASE_URL`.

No hace falta crear tablas: el backend las crea la primera vez que arranca.

> Supabase pausa los proyectos gratuitos tras 7 días sin uso. El ping del
> paso 5 lo mantiene activo.

## 2. Render (backend)

1. Entra a <https://render.com> con tu cuenta de GitHub.
2. **New → Blueprint** y elige el repositorio del **backend**. Render lee `render.yaml`.
3. Te pide dos variables:
   - `DATABASE_URL`: la cadena de Supabase del paso anterior.
   - `CORS_ORIGINS`: por ahora pon `https://example.com`; la cambias en el paso 4.
4. `JWT_SECRET_KEY` se genera sola. No la compartas.
5. Pulsa **Apply** y espera a que termine (unos 3 minutos).
6. Copia la URL del servicio, ej. `https://chupeymedeja-api.onrender.com`.
7. Ábrela agregando `/health`. Debe responder:
   ```json
   {"status":"ok","database":"ok"}
   ```

## 3. Netlify (frontend)

1. Entra a <https://netlify.com> con tu cuenta de GitHub.
2. **Add new site → Import an existing project** y elige el repositorio del **frontend**.
   Netlify lee `netlify.toml`; no cambies el comando ni la carpeta.
3. En **Environment variables** agrega:
   - `VITE_API_URL` = la URL de Render, **sin `/` al final**.
4. **Deploy**. Al terminar te da una URL como `https://algo-123.netlify.app`.
5. *(Opcional)* En **Site configuration → Change site name** ponle un nombre
   como `chupeymedeja` → `https://chupeymedeja.netlify.app`.

> `VITE_API_URL` se incluye al compilar. Si la cambias, haz **Deploys →
> Trigger deploy** para que se aplique.

## 4. Conectar frontend y backend (CORS)

En Render → tu servicio → **Environment**, cambia `CORS_ORIGINS` por la URL
exacta de Netlify (sin `/` al final) y guarda. Render se reinicia solo.

```
CORS_ORIGINS=https://chupeymedeja.netlify.app
```

Si usas dominio propio, agrégalo separado por coma.

## 5. Evitar que Render se duerma

El plan gratuito de Render apaga el backend tras 15 minutos sin uso, y el
primer ingreso después tarda unos 50 segundos. Para evitarlo:

1. Crea una cuenta en <https://cron-job.org> (gratis).
2. Crea un cron job:
   - **URL:** `https://<tu-backend>.onrender.com/health`
   - **Cada:** 10 minutos.

El plan gratuito de Render da 750 horas al mes: alcanza para un servicio
encendido todo el mes.

## 6. Crear tu cuenta de super admin

La app **no tiene registro público**: nadie puede crear una cuenta desde la
página. Tu cuenta de super admin se crea desde tu PC con un comando, apuntando
a la base de Supabase. Desde la carpeta `backend/`:

```powershell
$env:DATABASE_URL = "<la cadena de Supabase del paso 1>"
.\.venv\Scripts\python -m app.scripts.crear_superadmin tu@correo.com --nombre "Tu nombre" --sede "Asunción|Copacabana" --sede "Machado|Copacabana"
Remove-Item Env:DATABASE_URL
```

Te pide la contraseña sin mostrarla (mínimo 8 caracteres, con letras y
números). Ese mismo comando sirve para recuperar el acceso si la olvidas.

## 7. Crear las cuentas del negocio

Entra a la URL de Netlify con tu cuenta y abre **Usuarios** en el menú.

| Cuenta | Quién la crea | Qué puede hacer |
|---|---|---|
| **Super admin** (tú) | El comando del paso 6 | Todo. Crea sedes, dueños y administradores. |
| **Dueño** | Solo tú | Ve y opera ambas sedes. Crea cajeros en cualquier sede. |
| **Administrador** | Solo tú | Maneja todo en su sede. Crea cajeros de su sede. |
| **Cajero** | Tú, el dueño o el administrador de su sede | Vende, atiende mesas y maneja la caja. |

Arriba del menú está el selector de **Sede**. Elige una sede y carga su
menú, insumos y mesas; luego repite con la otra (o pídeselo a cada administrador).

## 8. En los celulares

Abre la URL en el navegador del celular y usa **Agregar a pantalla de inicio**
(Chrome: menú ⋮; Safari: botón Compartir). Queda como un ícono más.

## Seguridad: lo que ya está

- Contraseñas guardadas con bcrypt; mínimo 8 caracteres con letras y números.
- Sesiones con JWT de 12 horas. Cambiar la contraseña o desactivar una cuenta
  cierra sus sesiones abiertas.
- Bloqueo de 15 minutos tras 5 intentos de login fallidos.
- Cada sede solo ve sus datos; un empleado no puede ver otra sede.
- En producción el backend se niega a arrancar sin un secreto JWT propio, y
  no publica la documentación de la API.
- CORS solo acepta el dominio de Netlify.

## Si algo falla

| Síntoma | Causa probable |
|---|---|
| La app dice "No hay conexión con el servidor" | `VITE_API_URL` mal escrita, o falta redeploy en Netlify tras cambiarla. |
| En la consola del navegador aparece un error de CORS | `CORS_ORIGINS` en Render no coincide exacto con la URL de Netlify (revisa `https` y que no termine en `/`). |
| `/health` falla o Render no arranca | Revisa los **Logs** en Render. Si es la base, revisa `DATABASE_URL` (*Session pooler*, contraseña correcta). |
| El primer ingreso del día tarda casi un minuto | Render estaba dormido: configura el ping del paso 5. |
| Olvidaste tu contraseña de super admin | Repite el comando del paso 6 con tu mismo correo. |
| Alguien del personal olvidó su contraseña | Quien creó la cuenta se la restablece en **Usuarios**. |
