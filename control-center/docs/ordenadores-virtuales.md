# Ordenadores virtuales

**Son contenedores Docker endurecidos, no máquinas virtuales.** Comparten el kernel con el PC: un fallo grave del kernel o de Docker podría permitir escapar. Para el uso previsto (agentes que ejecutan código o navegan) se considera suficiente con estas capas; si algún día hace falta más, el paso siguiente sería gVisor (`--runtime=runsc`) o una VM con Firecracker.

## Perfiles (`virtual-computers/images/Dockerfile`)
| Perfil | Imagen | Incluye |
|---|---|---|
| Terminal | `jarvis-vc:terminal` (≈420 MB) | Debian, bash, git, Python 3, Node, curl, jq… |
| Browser | `jarvis-vc:desktop` (≈1,4 GB) | + Xvfb, x11vnc, Chromium (ventana única) y Playwright (Python, con el Chromium del sistema) |
| Desktop | `jarvis-vc:desktop` | + fluxbox, xterm y gestor de archivos |
| Campus | `jarvis-vc:canvas` + `jarvis-vc:egress` | Browser con la sesión del campus, sin red propia y con un proxy de solo lectura aparte (ver abajo) |

Construir o actualizar: `docker build --target terminal -t jarvis-vc:terminal virtual-computers/images` y lo mismo con `--target desktop -t jarvis-vc:desktop` y `--target canvas -t jarvis-vc:canvas`. El proxy: `docker build -t jarvis-vc:egress virtual-computers/egress`. Para un perfil nuevo: otra etapa en el Dockerfile, su nombre en `host-agent/vms.py` (`PROFILES`) y en la validación del backend.

## Aislamiento de cada ordenador
- Usuario `vc` (uid 1001) sin sudo; raíz de **solo lectura**; `/tmp` en tmpfs; su home en un volumen propio (`jarvis-vc-<id>`).
- `--cap-drop ALL`, `no-new-privileges`, seccomp por defecto de Docker, `--pids-limit 512`, CPU y RAM limitadas (sin swap extra).
- **Sin red** (`--network none`) salvo que se active internet. Nunca el socket de Docker, `$HOME`, `.env` ni `secrets/`.
- **Ningún puerto publicado.** El panel entra con `docker exec` (terminal) y `docker exec socat` al VNC local del contenedor (escritorio). El VNC no tiene contraseña porque solo se alcanza desde dentro del contenedor.
- Chromium corre con `--no-sandbox`: su sandbox necesita privilegios que se han quitado; el aislamiento lo da el contenedor.
- Disco: el driver local de Docker no limita volúmenes; el backend lo mide cada minuto y **para** el ordenador si pasa de su límite.

## Ciclo de vida y políticas
- Persistencia: **efímero** (se elimina al pararlo), **persistente** o **con caducidad** (se elimina al vencer). Los que pide un agente caducan a las 2 h.
- Como mucho 3 en marcha a la vez. Eliminar borra contenedor y volumen.
- Todo queda en la auditoría del panel y en la del Host Agent (`data/control-center/hostagent-audit.jsonl`); los cambios de estado son eventos en tiempo real.

## Agentes
Un agente o conversación con la capacidad «ordenador virtual» recibe un servidor MCP (`virtual-computers/mcp/vc_mcp.py`, solo librería estándar) con `vc_info`, `vc_request`, `vc_exec`, `vc_read_file`, `vc_write_file`, `vc_screenshot` y `vc_destroy`. Habla con un socket que el Host Agent abre **solo durante ese turno** y que **solo puede tocar el ordenador de esa sesión**: uno como máximo, perfil fijado al crear la sesión, sin internet y con límites fijos. El agente no ve Docker, el panel ni el token de Claude (que sigue en el contenedor de la sesión, que no tiene Bash). `execute` = estas herramientas; nunca comandos en la sesión ni en el PC.

Probado de verdad (31/10): el agente pidió su ordenador, ejecutó Python, comprobó que no tenía red, escribió y leyó un archivo y lo destruyó.

## Campus: navegador con la sesión del campus (02/11)
Para que un agente (el `tutor`) lea el aula con la sesión del usuario.

- **Sin red propia** (`--network none`). Su única salida es el socket Unix de un **proxy aparte** (`jarvis-vc-<id>-egress`, mitmproxy, endurecido igual), en un volumen que el ordenador monta en solo lectura. El agente no ve ese contenedor ni puede cambiar sus reglas; dentro del ordenador, `socat` expone el socket en `127.0.0.1:3128` y Chromium lo usa por política gestionada (raíz de solo lectura).
- **El proxy solo filtra dominios** (`virtual-computers/egress/filtro.py`): los dominios del campus (config `estudios.plataforma`, más las CDN de Canvas si la plataforma es Canvas). Todos los métodos están permitidos. Cada petición queda en su registro (pestaña **Accesos**).
- **La regla «solo leer» está en el prompt del agente, no en el código** (decisión del usuario, 02/11): una primera versión bloqueaba todo lo que no fuera lectura con un modo inicio de sesión aparte, pero impedía iniciar sesión con normalidad. El agente técnicamente puede enviar o subir cosas a el campus; sus instrucciones se lo prohíben.
- Inicio de sesión: el usuario entra en el campus desde la pestaña **Escritorio** (noVNC). La sesión se guarda en el volumen (Chromium restaura las cookies de sesión). Sin gestor de contraseñas; `file://` bloqueado; Chromium se relanza solo si se cierra.
- **Ordenador fijo del agente:** persistente y uno por agente (`owner_agent`). Las sesiones de ese agente lo usan siempre; no puede destruirlo ni pedir otro, y si está parado la pasarela lo arranca (primero el proxy). Otro agente no puede usarlo (se comprueba la etiqueta de dueño).
- **Herramientas** (todos los perfiles con pantalla): `vc_open_url`, `vc_page_text` (texto y enlaces por CDP; el puerto 9222 solo existe dentro del contenedor), `vc_click`, `vc_type`, `vc_key` y `vc_scroll` (xdotool, con validación; devuelven una captura).
- **Límites conocidos:** el agente puede leer todo lo que el usuario ve en el campus y, si desobedece o un contenido lo manipula, actuar en el campus en su nombre. Lo leído son datos, no instrucciones.
