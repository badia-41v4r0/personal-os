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

## Máquinas locales: VMs de VirtualBox del usuario (25/11/2026)
Algunas asignaturas piden su propio software en una máquina virtual (p. ej. VerilUOC en Fundamentos de computadores).
A diferencia de los ordenadores de arriba, **la máquina es del usuario**: la instala él, tiene internet y él mismo entra
(VirtualBox → Mostrar) cuando un programa pide iniciar sesión. El agente tiene libertad dentro, sin sudo.

- **Qué agente la usa:** `data/control-center/maquinas.json` (o `POS_MAQUINAS`), una entrada por máquina:
  `{"id", "nombre", "vbox" (nombre en VirtualBox), "usuario", "puerto", "clave" (relativa a secrets/), "display", "agentes", "notas"}`.
  Las entradas mal escritas o con la clave fuera de `secrets/` se ignoran.
- **Cómo entra:** el Host Agent, por SSH a `127.0.0.1:<puerto>` (redirección NAT de VirtualBox, solo local) con su clave
  (`secrets/vm/…`, 600) y `known_hosts` propio. Capturas con `VBoxManage controlvm … screenshotpng` (funcionan aunque falle
  el SSH); ratón y teclado con `xdotool` dentro de la VM. Código: `host-agent/maquinas.py`.
- **Herramientas** (en el MCP `vc`, solo si el agente tiene alguna máquina): `vm_list`, `vm_info`, `vm_start`, `vm_stop`,
  `vm_exec`, `vm_read_file`, `vm_write_file`, `vm_open_url`, `vm_page_text`, `vm_copy_in` (desde `/vault` o `/entregables`), `vm_copy_out` (solo a
  `/entregables`, sin pisar), `vm_screenshot`, `vm_click`, `vm_type`, `vm_key` y `vm_scroll`. Todo queda en la auditoría
  (`gateway.vm.*`). El agente nunca ve la clave, `VBoxManage` ni nada del PC fuera de esas carpetas.
- **Preparar una VM (Ubuntu/Debian):** dentro, `sudo apt install openssh-server xdotool`, la clave pública del Host Agent en
  `~/.ssh/authorized_keys` y en `/etc/ssh/sshd_config.d/personal-os.conf` `PasswordAuthentication no` y `PermitRootLogin no`.
  Fuera, `ssh-keygen -t ed25519 -N "" -f secrets/vm/<id>_ed25519` y
  `VBoxManage controlvm <vm> natpf1 "pos-ssh,tcp,127.0.0.1,<puerto>,,22"` (o `modifyvm … --natpf1` con la VM apagada).
  Antes, una instantánea (`VBoxManage snapshot <vm> take antes-personal-os`).
- **Navegador de la VM:** `vm_open_url` y `vm_page_text` usan el Chromium de la VM por CDP (127.0.0.1:9222, solo dentro de
  la VM). El Host Agent manda `host-agent/vm_cdp.py` por SSH (`python3 -`, solo librería estándar): no se instala nada.
  Si Chromium no está abierto lo arranca con el puerto; si el usuario lo abrió sin él, no lo cierra y avisa. El comando
  opcional del asistente copia el lanzador de Chromium o Chrome a `~/.local/share/applications/` con el puerto, así el
  agente usa la misma sesión en la que entra el usuario.
- **Desde el panel (26/11):** Ajustes → Ordenadores → «Máquinas locales». Lista las VMs de VirtualBox, las enciende,
  reanuda o apaga y enseña su pantalla. Su asistente: 1) elegir la VM (instantánea opcional; el Host Agent crea la clave
  y la redirección en un puerto libre desde 2222); 2) comandos para pegar dentro (SSH solo con clave y `xdotool`; el sudo
  lo escribe el usuario en la VM, nunca pasa por el panel), y uno opcional para el navegador; 3) probar con su usuario;
  4) agentes (solo los que tienen «ordenador») y notas. «Dejar de usarla» borra la entrada, la clave y la redirección, y
  no toca la VM. Código: `host-agent/maquinas_admin.py`, `backend/app/maquinas.py` y `apps/web/src/components/cc/maquinas-locales.tsx`.
