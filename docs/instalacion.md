# Instalación

## Requisitos

| Obligatorio | Para qué |
|---|---|
| Linux con systemd (sesión de usuario) | Servicios y temporizadores |
| Docker y `docker compose`, con tu usuario en el grupo `docker` | Contenedores de los turnos de IA y ordenadores virtuales |
| Python 3.12 o más y [uv](https://docs.astral.sh/uv/) | Backend y recopiladores |
| Node 20 o más | Compilar la web |
| git | Actualizar |
| Una CLI de IA: `claude`, `codex` u `opencode` | El motor (se elige en la bienvenida) |

| Opcional | Para qué |
|---|---|
| Tailscale | Usar el panel desde el móvil sin abrir puertos |
| `gh` (autenticado) | Módulo Proyectos |
| Ollama con `bge-m3` (`CC_EMBED_MODEL=bge-m3`) | Búsqueda semántica en tu memoria |
| GPU NVIDIA | Voz más rápida |
| `yt-dlp` y `ffmpeg` | Módulo Vídeos |
| `sudo loginctl enable-linger $USER` | Que los servicios sigan con la sesión cerrada |

`bin/pos comprobar` revisa todo esto.

## Instalar

```bash
bin/pos instalar [--instancia NOMBRE] [--puerto N] [--usuario NOMBRE] [--sin-ordenadores] [--simular]
```

Qué hace, en orden:
1. Comprueba los requisitos.
2. Elige nombre de instancia (por defecto `pos`), un puerto libre desde el 8770 y tu zona horaria.
3. Crea `.env` y `data/control-center/secrets.env` (permisos 600, fuera de git) con claves aleatorias.
4. Crea la vault (`Jarvis-Vault/`) desde `plantilla/vault/` si no existe. Si ya tienes una vault de Obsidian, puedes
   copiarla o enlazar su contenido dentro.
5. Instala dependencias, compila la web y construye las imágenes de Docker con el nombre de la instancia.
6. Instala los servicios de tu usuario (`<instancia>-cc-backend`, `<instancia>-cc-hostagent` y la copia nocturna).
   Los temporizadores de cada módulo se encienden cuando activas el módulo.
7. Crea tu usuario del panel (te pide la contraseña).

Con `--simular` enseña todo lo anterior sin escribir nada.

**Varias instalaciones en el mismo PC** (por ejemplo, una de pruebas): clona el proyecto en otra carpeta e instálalo
con otro `--instancia`. Cada una tiene sus contenedores, servicios, puertos, base de datos y vault.

## Primer uso

Abre `http://127.0.0.1:<puerto>`. La bienvenida tiene tres pasos:
1. **Tú:** cómo quieres que te llame y tus áreas (agrupan las tareas).
2. **Motor de IA:** ver [motores-de-ia.md](motores-de-ia.md). Con Claude, antes ejecuta `claude setup-token` y pon el
   token en `.env` (`CLAUDE_CODE_OAUTH_TOKEN=`); después `bin/pos actualizar`.
3. **Módulos:** activa solo lo que vayas a usar.

Después, cada apartado te ofrece configurarlo con su asistente la primera vez que lo abres.

## Desde el móvil (Tailscale)

```bash
tailscale serve --bg --https=<puerto> http://127.0.0.1:<puerto>
```

Añade `https://<equipo>.<tailnet>.ts.net:<puerto>` a `CC_ALLOWED_ORIGINS` en `data/control-center/secrets.env`, pon
`CC_COOKIE_SECURE=1` y ejecuta `bin/pos actualizar`. En el iPhone, ábrelo en Safari y «Añadir a pantalla de inicio»
para recibir avisos. Nunca uses Tailscale Funnel ni abras el puerto al router.

## Mantenimiento

| Orden | Qué hace |
|---|---|
| `bin/pos estado` | Servicios y salud del panel |
| `bin/pos comprobar` | Requisitos, permisos de los secretos, imagen y disco |
| `bin/pos actualizar` | Copia de la base, dependencias, web, imagen y reinicio. No toca tus datos |
| `bin/pos desinstalar` | Quita servicios y contenedores. Tus datos se quedan |
| `bin/pos desinstalar --borrar-datos` | Lo anterior y además borra base, vault y archivos (pide confirmación) |

Copias: cada noche, cifradas con `CC_BACKUP_KEY` (en `secrets.env`), en `data/control-center/backups/`. **Guarda esa
clave fuera del PC**: sin ella no se pueden restaurar en otra máquina. Restaurar: `control-center/deployment/restaurar.sh`.

Base de datos: SQLite por defecto. Para PostgreSQL (búsqueda semántica y más concurrencia):
`control-center/deployment/pasar-a-postgres.sh`.
