# Constructor, vista previa y versiones

El **Constructor** es un asistente del chat flotante que cambia el propio panel: añade apartados, cambia el aspecto,
ajusta un agente… El usuario no programa ni abre una terminal: lo pide, lo ve funcionando en una **vista previa** con
una copia de sus datos y, si le gusta, pulsa **Aplicar cambios**. Si algo sale mal, el panel vuelve solo a como estaba.

Es el módulo `constructor` (activo por defecto en las instalaciones nuevas; se apaga en Ajustes → Módulos). Ajustes →
**Versiones** (núcleo) permite además actualizar Personal OS, deshacer personalizaciones y restaurar copias de
seguridad, también sin terminal.

## Piezas

| Pieza | Dónde | Qué hace |
|---|---|---|
| Supervisor de cambios | `control-center/cambios/supervisor.py` | Aplica, deshace, actualiza, restaura y recompila, con copia de seguridad y vuelta atrás |
| Vista previa | `control-center/cambios/vista_previa.py` | Copia del código y de los datos y un segundo panel encerrado |
| Turno del Constructor | `control-center/cambios/constructor.py` | La CLI de IA trabajando en la copia, en el PC del usuario, encerrada |
| Instrucciones | `control-center/cambios/instrucciones.md` | Cómo trabaja el Constructor (leer antes, extensiones, pruebas, commits) |
| Host Agent | `/v1/constructor/*`, `/v1/cambios/*` | Lanza todo lo anterior como **unidades transitorias de systemd** |
| Backend | `app/constructor.py`, `app/cambios.py`, `app/vista_previa.py` | Conversación, lectura de los turnos, API de Versiones y proxy de `/vista-previa/` |
| Web | `components/cc/chat/constructor.tsx`, `components/cc/cambios.tsx`, `ajustes/versiones` | Barra del Constructor, «Aplicando cambios…», franja de la vista previa y Versiones |

Todo lo largo corre en **unidades aparte** (`<instancia>-cc-cambios`, `-constructor`, `-vista-previa`, `-vp-preparar`),
no como hijos del panel ni del Host Agent. Por eso un reinicio del panel —el que hace el propio supervisor al aplicar—
no corta nada: el turno del Constructor sigue y su salida se retoma (`constructor.recover()`), y la operación del
supervisor termina y deja su resultado en `data/cambios/estado.json`, que la web lee aunque el Host Agent se esté
reiniciando (`GET /api/v1/cambios/progreso`).

## Una personalización a la vez

`data/constructor/personalizacion.json` dice cuál está abierta y de qué conversación es. La escribe el Host Agent en el
acto (con un cerrojo), así dos peticiones a la vez no abren dos vistas previas. Mientras exista:
- crear otra conversación del Constructor devuelve 409 y el chat ofrece «Ir a ella»;
- no se puede actualizar Personal OS (hay que aplicarla o descartarla antes).

Se cierra al **aplicar** (con éxito) o al **descartar**. Una conversación cerrada se puede retomar: si no hay otra abierta,
el siguiente mensaje prepara una copia nueva del panel tal como está ahora (y la CLI sigue la misma conversación).

## Vista previa

- **Código:** `git clone --local` de la instalación en `data/constructor/copia`, rama `personalizaciones`. El Constructor
  solo hace commits ahí; el panel real no cambia hasta aplicar.
- **Datos:** copia en `data/constructor/datos` de la base (API de backup de SQLite, o `pg_dump` a `personal_os_vp`), la
  vault y `data/config`. **Nunca** se copian `secrets.env`, credenciales de los motores, claves de avisos, la sesión del
  banco ni las copias de seguridad. Lo hecho en la vista previa se tira al cerrarla.
- **Sin efectos hacia fuera:** `CC_VISTA_PREVIA=1` apaga los bucles de fondo (avisos, banco, sesión principal, monitor);
  no hay Host Agent (sin agentes, ordenadores, Telegram ni Docker) y los temporizadores siguen llamando al panel real.
- **Encerrada con bubblewrap:** sistema en solo lectura, lo personal del home oculto (`~/.ssh`, `~/.claude`, navegadores…),
  la carpeta de la instalación tapada; solo ve su copia del código (lectura) y sus datos (escritura).
- **Dirección:** `/vista-previa/` del mismo panel (sirve desde el móvil con Tailscale sin abrir otro puerto). El panel
  real comprueba la sesión y pasa a la vista previa el usuario, el token de sesión y el CSRF junto con un token que solo
  conocen los dos; la vista previa adopta esa sesión (`security.adoptar_sesion_vista_previa`, solo con
  `CC_VISTA_PREVIA=1`). Las cookies que ponga la vista previa no llegan al navegador.
- La web de la vista previa se compila con `NEXT_PUBLIC_BASE_PATH=/vista-previa` (`lib/base.ts` lo añade a `fetch`,
  WebSocket y enlaces de la API) y enseña arriba una franja con **Aplicar cambios**, **Descartar** y **Volver al panel**.
- Se **duerme** si nadie la usa en una hora y se despierta al abrirla.

## Turno del Constructor

`constructor.py turno <run>` lee la petición que deja el Host Agent (`data/constructor/turnos/<run>.json`), lanza la CLI
del motor elegido en Ajustes → Motor de IA (Claude Code, Codex u OpenCode; Antigravity no) y escribe su salida en
`<run>.ndjson` (formato de `claude -p --output-format stream-json`; los demás se traducen con `host-agent/proveedores.py`).
El backend la lee según crece y emite `session.delta` y `session.tool` como en el resto de chats.

Encierro: escribe solo en la copia del código, en los datos de la vista previa, en su home (`data/constructor/home`,
donde la CLI guarda sus conversaciones) y en las cachés de `uv` y `npm`. Tiene red (la CLI habla con su modelo). La
credencial entra solo durante el turno (la de Claude desde `.env`; la de Codex, copiada y renovada como en las sesiones).
Máximo 45 minutos por turno. Para que la persona vea el cambio, el Constructor ejecuta
`control-center/cambios/recargar-vista-previa.sh` (migra la base de la copia y recompila su web).

## Supervisor de cambios

Una operación a la vez (cerrojo en `data/cambios/` y nombre de unidad fijo). Cada una:

1. **Copia de seguridad** en `data/cambios/copias/<id>/`: la base de datos (`base/`, cifrada como `backup.py`; si el
   código nuevo trae migraciones, otra justo antes de migrar en `base-antes-de-migrar/`, que es la que usa la vuelta
   atrás), la vault (`vault.tar.gz`) y la configuración (`.env`, `secrets.env`, `data/config`, credenciales; cifrada con
   `CC_BACKUP_KEY`). Si no hay espacio en disco para la copia, **no se toca nada**. Se guardan las 5 últimas.
2. **Código con git:** fusión `--no-ff` de la rama de la copia («Personalización: …»), `git revert -m 1` para deshacer
   («Deshacer personalización: …» + `Deshace <commit>`), o fusión de la etiqueta `vX.Y.Z` del repo de origen
   («Actualización a vX.Y.Z», o avance directo si no hay personalizaciones). Si choca, se aborta y no cambia nada. Si
   alguien editó el código a mano, se guarda antes en un commit («Cambios hechos fuera del panel»).
3. **Despliegue:** `uv sync`, `npm ci` si cambió el lock, web compilada en `out-nuevo`, imagen de Docker, migraciones
   (solo si el código trae una nueva), cambio de la web de golpe (`out` → `out-anterior`, `out-nuevo` → `out`),
   unidades, reinicio y comprobación de `/api/v1/health` y de la web durante 150 s.
4. **Vuelta atrás si algo falla:** `git reset --hard` al commit anterior, `uv sync`, la web anterior y, si la base se llegó
   a migrar, la copia de la base; reinicio y comprobación. El resultado queda como `revertido` (o `roto` si tampoco
   arranca así, con las copias intactas).

Para encontrar `uv` y `node` sin terminal usa el `PATH` que `bin/pos instalar` y `bin/pos actualizar` guardan en `.env`
(`POS_PATH`). `bin/pos actualizar` usa este mismo supervisor (`desplegar`, sin tocar git).

## Actualizar Personal OS desde el panel

Ajustes → Versiones → **Buscar actualizaciones** hace `git fetch --tags` del repo de origen y enseña las notas de la
versión (del `CHANGELOG.md` de esa etiqueta). **Actualizar** junta esa versión con las personalizaciones. Si chocan,
**Juntar con el Constructor** abre una personalización con la fusión a medias en la copia: el Constructor resuelve los
conflictos, se ve en la vista previa y se aplica como cualquier otro cambio.

## Probarlo

- Backend: `tests/test_cambios_supervisor.py` (repo git de mentira: aplicar, vuelta atrás, conflictos, deshacer,
  actualizar, espacio, cerrojo, restaurar), `tests/test_cambios_vista_previa.py` (qué se copia y qué no, encierro,
  entorno limpio) y `tests/test_constructor.py` (una a la vez, turnos, reinicio, proxy, sesión adoptada).
- Host Agent: `tests/test_constructor_ha.py` (reserva, validación, una operación a la vez).
- De punta a punta: una instancia de prueba (`bin/pos instalar --instancia posdev --puerto 8791 --sin-ordenadores`)
  clonada de un repo de origen local con etiquetas.
