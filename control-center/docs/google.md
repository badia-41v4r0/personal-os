# Permisos de Google desde Configuración

La app de Google está en **modo Prueba**: el permiso (token de refresco) caduca a los 7 días. No se publica la app (Google exigiría página principal y política de privacidad; el usuario no quiere), así que el panel no elimina la caducidad: hace la renovación fácil.

## Flujo (iPhone o Mac, por Tailscale)
1. Configuración → «Permisos de Google» → **Renovar** en la cuenta (o «Renovar las dos»).
2. El panel enseña un enlace de Google. Se abre, se elige la cuenta y se pulsa Continuar.
3. Google redirige a `http://127.0.0.1:8765/?state=…&code=…`, que en el móvil **no carga** (es lo esperado: el cliente OAuth es de escritorio y solo admite bucle local). Se copia esa dirección completa y se pega en el panel → Confirmar.

## Piezas
- `collectors/gcal.py`: `url_autorizacion(cuenta, state)` y `canjear(code, cuenta)`; `auth()` (terminal y `renovar-google.sh`) los usa por dentro.
- `host-agent/google_auth.py` (el único que toca `secrets/`): `status` (edad por `mtime`, nunca el contenido), `auth_url` (state aleatorio, 10 min, un solo uso, una renovación por cuenta) y `exchange` (valida el state y canjea). Rutas `/v1/google/*`, auditadas.
- Backend: `GET /api/v1/system/google`, `POST …/{cuenta}/renovar` y `POST …/{cuenta}/callback` (admin, CSRF, Origin, auditoría `google.renew.start|finish`). `agenda.py` recuerda si una llamada real dio `Caducado` (`caducadas()`), y al renovar limpia la caché.
- Aviso: `reminders.google_pending` — un push al día por cuenta cuando le quedan ≤ 2 días o ya caducó, hasta que se renueve. Si el Host Agent no responde, no se avisa.
- `bin/renovar-google.sh` sigue a las 10:00 (PC con sesión gráfica); su aviso lleva a `/settings/`. Si el token se renovó desde el panel, el script lo ve reciente y no hace nada.

## Límites
- El state vive en memoria del Host Agent: si se reinicia, hay que pulsar Renovar otra vez.
- Si Google no devuelve `refresh_token`, hay que revocar el acceso en la cuenta de Google y repetir.
