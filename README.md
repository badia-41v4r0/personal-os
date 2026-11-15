# Personal OS

Un asistente personal que vive en tu PC. Organiza tu agenda, tus tareas, tus estudios, tu entrenamiento, tus finanzas
y tu búsqueda de empleo desde un panel web privado, con un asistente de IA en cada apartado. Tus datos se quedan en tu
máquina; el modelo de IA solo ve lo que necesita en cada turno.

![Asistente de bienvenida](docs/img/bienvenida.png)

## Qué hace

- **Inicio:** tu asistente (por defecto se llama Jarvis, pero le pones el nombre que quieras), que lo ve todo, con check-in de mañana y noche, avisos y un resumen de tu día.
- **Un asistente por apartado.** Cada uno solo ve lo suyo y solo puede hacer lo suyo.
- **Módulos que activas y desactivas:** Agenda, Correo, Educación, Entrenamiento, Salud, Finanzas, Carrera, Objetivos,
  Estilo de vida, Conocimiento (tu vault de Obsidian), Proyectos (GitHub), Ayudante, Vídeos, Ordenadores virtuales,
  Voz y avisos por Telegram. Lo desactivado desaparece del panel y ningún agente puede usarlo.
- **Rutinas:** briefing por la mañana, recordatorio por la noche y revisión semanal.
- **Elige tu motor de IA:** Claude Code, Codex (ChatGPT), OpenRouter (con OpenCode) o Antigravity.
- **Onboarding guiado:** la primera vez que abres un apartado, su asistente te ayuda a configurarlo. Nada se guarda
  sin tu aprobación. El de Educación puede abrir tu campus virtual en un navegador aislado y leer asignaturas,
  entregas y calendario por ti.

| Motor de IA | Módulos | Primera vez en un apartado |
|---|---|---|
| ![Motor de IA](docs/img/motor.png) | ![Módulos](docs/img/modulos.png) | ![Primera vez](docs/img/primera-vez.png) |

## Instalación rápida

Si ya tienes Docker, Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 20+ y git:

```bash
git clone https://github.com/badia-41v4r0/personal-os.git && cd personal-os
bin/pos instalar            # o «bin/pos instalar --simular» para ver qué haría sin tocar nada
```

Abre la dirección que te indica (por defecto `http://127.0.0.1:8770`) y entra con **`admin` / `admin`**: lo primero que
te pide es cambiarlos. Después, la bienvenida. Si no tienes los requisitos, sigue los pasos de abajo.

## Instalación paso a paso (con Docker)

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
| Claude Code | `npm install -g @anthropic-ai/claude-code` | `claude setup-token`: el token se pone en el paso 6 |
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

### 6. Si usas Claude, pon tu token

Edita `.env` (permisos 600, no se sube a git) y pega el token del paso 3:

```bash
CLAUDE_CODE_OAUTH_TOKEN=sk-ant-...
```

Después:

```bash
bin/pos actualizar
```

### 7. Abre el panel

`http://127.0.0.1:8770` (o el puerto que te indicó) y entra con **`admin` / `admin`**.

1. **Lo primero, protege el panel:** te pide una contraseña nueva (mínimo 12 caracteres) y, si quieres, otro nombre de
   usuario. Hasta que no lo hagas no puedes usar nada más. Después se cambian en **Configuración → Cuenta**.
2. **Bienvenida:** tu nombre, **cómo quieres llamar a tu asistente** (por defecto Jarvis), tus áreas, el motor de IA y
   los módulos. El nombre del asistente se cambia cuando quieras en **Configuración → Tú y tu asistente**.

### 8. Opcional: más servicios en Docker

**PostgreSQL** (en vez de SQLite; necesario para la búsqueda semántica):

```bash
control-center/deployment/pasar-a-postgres.sh
```

Arranca el contenedor `<instancia>-db` (solo en `127.0.0.1`), copia los datos y cambia el panel. Si falla, el panel
sigue en SQLite.

**Voz y vídeos** (Whisper local):

```bash
docker compose up -d jarvis
```

`jarvis` es el nombre del servicio en `docker-compose.yml`. El contenedor se llama como tu instancia.

### 9. Comprueba que todo va bien

```bash
bin/pos comprobar                                    # requisitos, servicios, permisos y disco
bin/pos estado                                       # servicios y salud del panel
docker images | grep <instancia>                     # imágenes construidas
docker ps --filter label=<instancia>.vc              # ordenadores virtuales en marcha
journalctl --user -u <instancia>-cc-backend -n 50    # registro del panel
```

### Problemas frecuentes

| Síntoma | Solución |
|---|---|
| Olvidaste la contraseña | En el PC: `cd control-center/backend && set -a && . ../../data/control-center/secrets.env && set +a && .venv/bin/python -m app.cli set-password <usuario>` |
| `permission denied ... docker.sock` | Tu usuario no está en el grupo `docker`, o no has vuelto a iniciar sesión (paso 1) |
| «Hace falta Python 3.12» | Actualiza Python o usa una distribución más reciente |
| El puerto 8770 está ocupado | El instalador elige otro solo; o pasa `--puerto 8780` |
| `docker build` falla por falta de espacio | Libera espacio. `docker system df` enseña lo que ocupa Docker |
| El panel no abre | `journalctl --user -u <instancia>-cc-backend -n 50` |
| Los servicios se paran al cerrar sesión | `sudo loginctl enable-linger $USER` |

### Actualizar y desinstalar

```bash
git pull && bin/pos actualizar         # copia de la base, recompila y reinicia; tus datos no se tocan
bin/pos desinstalar                    # quita servicios y contenedores; tus datos se quedan
bin/pos desinstalar --borrar-datos     # y además borra base, vault y archivos (pide confirmación)
docker image rm $(docker images --format '{{.Repository}}:{{.Tag}}' | grep '^<instancia>')   # liberar las imágenes
```

Más detalles (móvil con Tailscale, copias de seguridad, varias instalaciones en el mismo PC) en
[docs/instalacion.md](docs/instalacion.md).

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

Desde aquí, los [pasos 2 a 9 de la instalación](#2-instala-el-resto-de-requisitos) son los mismos que en Linux, todos en
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

## Documentación

- [Instalación](docs/instalacion.md): requisitos, opciones, móvil con Tailscale, actualizar y desinstalar.
- [Guía de uso](docs/guia-de-uso.md): qué hace cada apartado y cómo sacarle partido.
- [Motores de IA](docs/motores-de-ia.md): qué puede hacer cada uno, cómo conectarlo y qué cuesta.
- [Seguridad y privacidad](docs/seguridad.md): qué ve cada agente, qué sale de tu PC y qué no.
- [Crear un módulo](docs/modulos.md): para quien quiera extenderlo.
- Documentación técnica por tema en [control-center/docs/](control-center/docs/).

## Cómo está hecho

```
 Navegador (PC o móvil por Tailscale)
        │ solo 127.0.0.1 o tu tailnet
 ┌──────▼───────────────────────────┐      ┌──────────────────────────────┐
 │ Backend (FastAPI) + web (Next.js) │◄────►│ Host Agent (socket Unix)     │
 │ SQLite o PostgreSQL · módulos     │      │ systemd · Docker · métricas  │
 │ acciones con aprobación · memoria │      │ lista cerrada y auditada     │
 └──────┬───────────────────────────┘      └──────┬───────────────────────┘
        │ lee y escribe                            │ lanza
 ┌──────▼──────────┐                ┌──────────────▼─────────────────────────┐
 │ Vault Obsidian   │                │ Contenedor efímero por turno de IA     │
 │ (tus notas)      │                │ (Claude, Codex u OpenCode), sin $HOME, │
 └─────────────────┘                │ sin Docker, sin privilegios; escribe   │
                                     │ solo por acciones del Personal OS      │
                                     └────────────────────────────────────────┘
```

## Licencia

[PolyForm Noncommercial 1.0.0](LICENSE): puedes usarlo, modificarlo y compartirlo **sin fines comerciales** (uso
personal, estudio, investigación, organizaciones sin ánimo de lucro). El uso comercial está reservado al autor; si lo
quieres para un uso comercial, escríbele. Para contribuir, mira [CONTRIBUTING.md](CONTRIBUTING.md).

## Estado

Proyecto personal publicado tal cual. Funciona en Linux, donde los ordenadores virtuales están incluidos y se instalan
con `bin/pos instalar` (salvo con `--sin-ordenadores`). En Windows puede funcionar dentro de WSL2
([instrucciones](#windows-con-wsl2-sin-probar), sin probar). En Mac o con Docker Desktop no funciona: el Host Agent necesita
Linux. Documentación e interfaz en español.

Usar tu suscripción de un proveedor de IA con este proyecto es responsabilidad tuya: revisa sus condiciones de uso.
