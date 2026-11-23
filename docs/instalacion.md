# Instalación

Guía completa. Si ya tienes los requisitos, basta con `bin/pos instalar` (ver el [README](../README.md)).

## Requisitos

Solo Linux. En Windows, dentro de WSL2: ver [Windows con WSL2](#windows-con-wsl2-sin-probar) (sin probar).

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

## Paso a paso (con Docker)

### Qué va en Docker y qué no

| Pieza | Dónde corre | Por qué |
|---|---|---|
| Cada turno de IA (Claude, Codex, OpenCode) | Contenedor efímero `<instancia>:local` | Aísla al modelo: sin tu `$HOME`, sin Docker, sin privilegios |
| Proxy de salida de Codex y OpenCode | Contenedor efímero | Solo deja salir a la API del motor |
| Ordenadores virtuales (terminal, navegador, campus) | Contenedores `<instancia>-vc:*` | Donde los agentes ejecutan código o navegan, sin red ni credenciales |
| PostgreSQL (opcional) | Contenedor `<instancia>-db` | Base de datos con búsqueda semántica |
| Whisper (voz y vídeos, opcional) | Contenedor `<instancia>` | Transcripción local |
| Panel (backend + web) y Host Agent | Servicios de tu usuario (systemd), no en Docker | El Host Agent es quien lanza los contenedores de arriba. Meterlo en Docker obligaría a darle el socket de Docker, que equivale a darle root: el proyecto no lo hace por seguridad |

Por eso hace falta Linux con systemd: no basta con `docker compose up`.

### 1. Instala Docker

Ubuntu, Debian o Fedora (script oficial de Docker):

```bash
curl -fsSL https://get.docker.com | sh
```

Arch:

```bash
sudo pacman -S docker docker-compose
```

En cualquier distribución, después:

```bash
sudo systemctl enable --now docker      # que arranque con el sistema
sudo usermod -aG docker $USER           # usar Docker sin sudo
```

**Cierra sesión y vuelve a entrar** para que valga el grupo. Comprueba que funciona sin `sudo`:

```bash
docker run --rm hello-world
docker compose version
```

> Si usas una VPN que intercepta el tráfico (p. ej. Cloudflare WARP), puede romper las redes nuevas de Docker. Los
> contenedores del proyecto usan la red `bridge` por defecto o ninguna, así que no debería afectar.

### 2. Instala el resto de requisitos

| Requisito | Cómo |
|---|---|
| git | Con el gestor de paquetes (`apt install git`, `dnf install git`, `pacman -S git`) |
| Python 3.12 o más | Viene en Ubuntu 24.04+, Fedora 40+ y Arch. Comprueba con `python3 --version` |
| uv | `curl -LsSf https://astral.sh/uv/install.sh \| sh` (y abre otra terminal) |
| Node 20 o más | Con el gestor de paquetes si te da 20+, o con [nvm](https://github.com/nvm-sh/nvm): `nvm install 22` |

Opcional: `sudo loginctl enable-linger $USER` para que el panel siga funcionando con tu sesión cerrada.

### 3. Instala y conecta el motor de IA

Solo el que vayas a usar (se puede cambiar después):

| Motor | Instalar | Conectar |
|---|---|---|
| Claude Code | `npm install -g @anthropic-ai/claude-code` | `claude setup-token`: el token se pega en el panel (paso 6) |
| Codex | `npm install -g @openai/codex` | `codex login`, y después «Conectar Codex» en el panel |
| OpenRouter | `npm install -g opencode-ai` | Tu clave de openrouter.ai, en el panel |

La imagen de Docker trae las tres CLI. Las del PC solo sirven para iniciar sesión.

### 4. Descarga el proyecto

```bash
git clone https://github.com/badia-41v4r0/personal-os.git
cd personal-os
```

La carpeta donde lo clones es donde vivirán tus datos (`data/`, `Jarvis-Vault/`, `archivos/`).

### 5. Instala

Primero mira qué va a hacer, sin tocar nada:

```bash
bin/pos instalar --simular
```

Y después, de verdad:

```bash
bin/pos instalar
```

Opciones: `--instancia NOMBRE` (por defecto `pos`), `--puerto N` (por defecto el primero libre desde el 8770),
`--usuario NOMBRE` (crea ese usuario y te pide su contraseña en vez de usar `admin`/`admin`) y `--sin-ordenadores` (no construye las imágenes de los
ordenadores virtuales; el tutor no podrá abrir tu campus).

Lo que construye en Docker (la primera vez tarda varios minutos y ocupa varios GB):

| Imagen | Para qué |
|---|---|
| `<instancia>:local` | Turnos de IA, Whisper y el programador |
| `<instancia>-vc:egress` | Proxy de los ordenadores con salida filtrada |
| `<instancia>-vc:terminal`, `:desktop`, `:canvas`, `:aplicaciones` | Ordenadores virtuales (salvo con `--sin-ordenadores`) |

Al final crea el usuario inicial **`admin` / `admin`**.

### 6. Abre el panel

```bash
bin/pos abrir          # o abre tú http://127.0.0.1:8770 (o el puerto que te indicó)
```

Entra con **`admin` / `admin`**.

1. **Lo primero, protege el panel:** te pide una contraseña nueva (mínimo 12 caracteres) y, si quieres, otro nombre de
   usuario. Hasta que no lo hagas no puedes usar nada más. Después se cambian en **Ajustes → Tú y tu cuenta**.
2. **Bienvenida:** tu nombre, **cómo quieres llamar a tu asistente** (por defecto Jarvis), tus áreas, el motor de IA y
   los módulos. Si eliges Claude, pega ahí el token del paso 3 (se guarda en el `.env` del PC con permisos 600).
3. **Inicio** te enseña «Te falta por configurar»: cada punto lleva directo a donde se hace (conectar Google, el
   campus, Telegram…). Desaparece cuando no queda nada.

### 7. Opcional: más servicios en Docker

**PostgreSQL** (en vez de SQLite; necesario para la búsqueda semántica):

```bash
bin/pos postgres
```

Arranca el contenedor `<instancia>-db` (solo en `127.0.0.1`), copia los datos y cambia el panel. Si falla, el panel
sigue en SQLite.

**Voz y vídeos** (Whisper local):

```bash
bin/pos voz
```

Arranca el servicio `jarvis` de `docker-compose.yml`; el contenedor se llama como tu instancia.

### 8. Comprueba que todo va bien

```bash
bin/pos comprobar                                    # requisitos, servicios, permisos y disco
bin/pos estado                                       # servicios y salud del panel
docker images | grep <instancia>                     # imágenes construidas
docker ps --filter label=<instancia>.vc              # ordenadores virtuales en marcha
bin/pos logs                                         # registro del panel (bin/pos logs -f para seguirlo)
```

## Problemas frecuentes

| Síntoma | Solución |
|---|---|
| Olvidaste la contraseña | En el PC: `bin/pos contraseña <usuario>` |
| `permission denied ... docker.sock` | Tu usuario no está en el grupo `docker`, o no has vuelto a iniciar sesión (paso 1) |
| «Hace falta Python 3.12» | Actualiza Python o usa una distribución más reciente |
| El puerto 8770 está ocupado | El instalador elige otro solo; o pasa `--puerto 8780` |
| `docker build` falla por falta de espacio | Libera espacio. `docker system df` enseña lo que ocupa Docker |
| El panel no abre | `bin/pos logs` (registro del panel) |
| Los servicios se paran al cerrar sesión | `sudo loginctl enable-linger $USER` |

## Qué hace el instalador

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
7. Crea el usuario inicial **`admin` / `admin`** (o el de `--usuario`, pidiendo su contraseña).

Con `--simular` enseña todo lo anterior sin escribir nada.

**Varias instalaciones en el mismo PC** (por ejemplo, una de pruebas): clona el proyecto en otra carpeta e instálalo
con otro `--instancia`. Cada una tiene sus contenedores, servicios, puertos, base de datos y vault.

## Desde el móvil (Tailscale)

```bash
tailscale serve --bg --https=<puerto> http://127.0.0.1:<puerto>
```

Añade `https://<equipo>.<tailnet>.ts.net:<puerto>` a `CC_ALLOWED_ORIGINS` en `data/control-center/secrets.env`, pon
`CC_COOKIE_SECURE=1` y ejecuta `bin/pos actualizar`. En el iPhone, ábrelo en Safari y «Añadir a pantalla de inicio»
para recibir avisos. Nunca uses Tailscale Funnel ni abras el puerto al router.

## Mantenimiento

Todo desde un solo comando, `bin/pos` (`bin/pos ayuda` las enseña todas):

| Orden | Qué hace |
|---|---|
| `bin/pos abrir` | Abre el panel en el navegador |
| `bin/pos estado` | Servicios y salud del panel |
| `bin/pos comprobar` | Requisitos, permisos de los secretos, imagen y disco |
| `bin/pos logs [panel\|hostagent\|UNIDAD] [-f]` | Registro de un servicio (por defecto, el panel) |
| `bin/pos contraseña [USUARIO]` | Cambiar la contraseña del panel si la olvidaste |
| `bin/pos postgres` | Pasar de SQLite a PostgreSQL (búsqueda semántica y más concurrencia) |
| `bin/pos voz` | Arrancar Whisper (voz y vídeos) |
| `bin/pos actualizar` | Copia de la base, dependencias, web, imagen y reinicio. No toca tus datos |
| `bin/pos desinstalar` | Quita servicios y contenedores. Tus datos se quedan |
| `bin/pos desinstalar --borrar-datos` | Lo anterior y además borra base, vault y archivos (pide confirmación) |

Para actualizar: `git pull && bin/pos actualizar`. Para liberar las imágenes después de desinstalar:
`docker image rm $(docker images --format '{{.Repository}}:{{.Tag}}' | grep '^<instancia>')`.

Copias: cada noche, cifradas con `CC_BACKUP_KEY` (en `secrets.env`), en `data/control-center/backups/`. **Guarda esa
clave fuera del PC**: sin ella no se pueden restaurar en otra máquina. Restaurar: `control-center/deployment/restaurar.sh`.

## Windows con WSL2 (sin probar)

> **Aviso:** esta forma de instalarlo **no se ha probado**. En teoría funciona porque todo corre dentro de un Linux de
> verdad (WSL2), pero puede que encuentres problemas. Si lo pruebas, cuéntanos cómo te ha ido en una issue.

El Personal OS necesita Linux: sockets Unix, systemd y Docker nativo. En Windows no funciona directamente, pero sí
dentro de **WSL2**, que ejecuta una distribución Linux completa. La idea es instalarlo todo *dentro* de Ubuntu (WSL) y
abrir el panel desde el navegador de Windows.

### 1. Instala WSL2 con Ubuntu

Requisitos: Windows 10 (22H2) o Windows 11, con la virtualización activada en la BIOS (casi siempre lo está).

Abre **PowerShell como administrador** y ejecuta:

```powershell
wsl --install -d Ubuntu-24.04
```

Reinicia si te lo pide. Al abrir «Ubuntu» por primera vez, crea tu usuario y contraseña de Linux.

### 2. Activa systemd en Ubuntu

En la terminal de Ubuntu, comprueba si ya está activo (en las instalaciones recientes suele estarlo):

```bash
systemctl --user status >/dev/null && echo "systemd activo"
```

Si no lo está, edita `/etc/wsl.conf`:

```bash
sudo nano /etc/wsl.conf
```

y deja estas líneas:

```ini
[boot]
systemd=true
```

Después, en **PowerShell**: `wsl --shutdown`, y vuelve a abrir Ubuntu.

### 3. Instala Docker dentro de Ubuntu

Usa Docker **dentro de WSL**, no Docker Desktop. El Host Agent monta sockets Unix en los contenedores, y eso no cruza
bien la frontera entre Windows y la máquina de Docker Desktop. Si ya tienes Docker Desktop, desactiva su integración
con esta distribución (Docker Desktop → Settings → Resources → WSL integration) para no tener dos Docker a la vez.

```bash
curl -fsSL https://get.docker.com | sh
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
```

Cierra Ubuntu, vuelve a abrirlo y comprueba con `docker run --rm hello-world`.

### 4. Sigue la instalación normal, dentro de Ubuntu

Desde aquí, los [pasos 2 a 8 de la instalación](#2-instala-el-resto-de-requisitos) son los mismos que en Linux, todos en
la terminal de Ubuntu. Dos cosas importantes:

- **Clona el proyecto dentro de Linux** (por ejemplo en `~/personal-os`), **no** en `/mnt/c/...`. En el disco de
  Windows los permisos no funcionan bien (los secretos tienen que ser 600) y todo va mucho más lento.
- Instala las CLI de IA (`claude`, `codex`, `opencode`) también dentro de Ubuntu.

### 5. Abre el panel desde Windows

WSL2 redirige `localhost` a Windows, así que en el navegador de Windows abre `http://127.0.0.1:8770` (o el puerto que te
indicó el instalador).

### Lo que es distinto en Windows

| Tema | Qué pasa |
|---|---|
| WSL se apaga | Windows puede apagar Ubuntu cuando cierras todas sus terminales, y con él el panel. Si pasa, deja una terminal de Ubuntu abierta o ejecuta `wsl` al iniciar sesión en Windows. `sudo loginctl enable-linger $USER` también ayuda |
| Voz en el PC | No recomendado: el micrófono y los altavoces de Windows no llegan fácilmente a WSL. Deja el módulo Voz desactivado |
| Monitor | Enseña los recursos de la máquina de WSL (la memoria y CPU que Windows le da), no los de todo el PC |
| Memoria | WSL usa como máximo la mitad de la RAM. Si se queda corto, súbelo en `%UserProfile%\.wslconfig` (`[wsl2]` → `memory=8GB`) |
| Móvil con Tailscale | Instala Tailscale **dentro de Ubuntu** (no en Windows) para usar `tailscale serve`, como en Linux |
| Obsidian | Si quieres abrir la vault con Obsidian para Windows, está en `\\wsl$\Ubuntu-24.04\home\<tu-usuario>\personal-os\Jarvis-Vault` |
