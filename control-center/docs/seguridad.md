# Seguridad

## Acceso
- Backend y frontend solo en `127.0.0.1`. Fuera, solo por Tailscale Serve (tailnet only), nunca Funnel.
- Autenticación propia: usuario creado en el PC (`uv run python -m app.cli set-password <usuario>`), Argon2id, mínimo 12 caracteres, bloqueo de 15 min tras 5 fallos, mismo tiempo de respuesta con usuario inexistente.
- Cookie `cc_session` opaca (en la base solo su SHA-256), HttpOnly, Secure, SameSite=Strict, 7 días.
- Peticiones con efecto: cabecera `X-CSRF-Token` + `Origin` en la lista `CC_ALLOWED_ORIGINS`. WebSocket: `Origin` + cookie.
- Cabeceras: `X-Frame-Options: DENY`, `nosniff`, `no-referrer`, `no-store`. Errores sin trazas.

## Host Agent
- Proceso del usuario normal (se niega a arrancar como root), socket Unix con permisos 600 en una carpeta 700, token de 32+ caracteres comparado en tiempo constante.
- Solo comandos fijos sin shell y con timeout. Unidades limitadas a `jarvis-*` (regex), contenedores a `jarvis` y `jarvis-vc-*`.
- Auditoría en `data/control-center/hostagent-audit.jsonl` (incluidas las denegaciones).

## Secretos
- `data/control-center/secrets.env` (600) y no en `secrets/`: esa carpeta la monta el contenedor de Jarvis (para Google), y el token del Host Agent no debe estar a su alcance.
- `CC_HOSTAGENT_TOKEN` en `data/control-center/secrets.env` (600, fuera de git). Nada de secretos en el frontend.
- El backend no lee `secrets/`, `.env` ni las credenciales de Claude.

## Capacidades de agentes y sesiones
`read` < `propose` < `execute`. Todo nace como borrador y sin `execute`. Activar un subagente de Jarvis enseña el archivo y pide confirmación. Ningún agente puede editar su definición (no ve el panel y `agent/.claude` está en solo lectura para Jarvis).

## Sesiones independientes
Contenedor efímero por turno (`--read-only`, `cap_drop ALL`, 1 GB / 1 CPU), sin Bash ni intérpretes (con red y una terminal se podría sacar el token), token solo por entorno. Vault solo en lectura y solo si se concede.

## Ordenadores virtuales
Ver `ordenadores-virtuales.md`: usuario sin privilegios, raíz de solo lectura, sin capacidades, sin red por defecto, sin puertos, sin secretos; contenedores (no VMs). Los agentes solo los tocan por una pasarela por turno limitada a su ordenador.

## Alertas
Las críticas se avisan por Telegram a través del Host Agent (`bin/telegram-send.sh`): el backend nunca ve el token del bot.

## Pruebas de seguridad automatizadas
Acceso sin sesión (401), CSRF y Origin (403), WebSocket con origen ajeno o sin cookie, bloqueo por fuerza bruta, rutas arbitrarias en el lector de transcripciones, unidades y contenedores fuera de la lista en el Host Agent, auditoría de denegaciones. `cd backend && uv run pytest`.
