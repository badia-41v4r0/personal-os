# Cambios

Todas las versiones de Personal OS. Se sigue [versionado semántico](https://semver.org/lang/es/): mientras la versión
sea 0.x, una versión menor (0.**2**.0) puede traer cambios que pidan hacer algo al actualizar; siempre se explican en
«Al actualizar». La versión actual está en el archivo `VERSION`.

## [Sin publicar]

## [0.1.1] — 2026-11-26

### Novedades

- **Constructor.** Un asistente nuevo del chat que personaliza el propio panel: le pides un apartado nuevo, otro
  aspecto o un ajuste de un agente y lo hace él, sin que toques código ni la terminal. Trabaja en una copia del panel,
  en tu PC y encerrado (no ve tus datos reales, tu vault real ni tus secretos), y te lo enseña en una **vista previa**
  en `/vista-previa/`, con una copia de tus datos. Si te gusta, **Aplicar cambios**; si no, le pides ajustes o lo
  descartas. Solo puede haber una personalización abierta a la vez. Viene activo en las instalaciones nuevas (Ajustes →
  Módulos para apagarlo).
- **Aplicar sin quedarte tirado.** Antes de cada cambio se hace una copia de seguridad (base de datos, vault y
  configuración). El panel se compila aparte, se reinicia y se comprueba que responde; si no, vuelve solo al código, a
  la web y a la base de antes. Mientras tanto, el panel enseña «Aplicando cambios…» y, al volver, cómo ha ido. El
  Constructor sigue trabajando aunque el panel se reinicie a mitad.
- **Ajustes → Versiones.** Busca y aplica versiones nuevas de Personal OS conservando tus personalizaciones (si chocan,
  el Constructor las junta en una vista previa), deshaz cualquier personalización y vuelve a una copia de seguridad
  (también la vault, sin borrar la actual). Todo sin terminal.
- `bin/pos actualizar` usa el mismo mecanismo: copia de seguridad completa y vuelta atrás si el panel no arranca.

### Al actualizar

- Esta vez, desde la terminal: `git pull && bin/pos actualizar` (a partir de aquí, las siguientes ya se pueden hacer
  desde Ajustes → Versiones).
- El Constructor necesita **bubblewrap** (`bwrap`): `sudo pacman -S bubblewrap`, `sudo apt install bubblewrap` o el
  equivalente de tu distribución. `bin/pos comprobar` dice si falta.
- Si ya tenías módulos elegidos, el Constructor llega apagado: actívalo en Ajustes → Módulos.

## [0.1.0] — 2026-11-26

Primera versión numerada. Hasta ahora el repositorio se publicaba sin versiones: esta recoge todo lo anterior y lo
nuevo de estos días.

### Novedades

- **Máquinas locales (VirtualBox).** En Ajustes → Ordenadores puedes conectar tus propias máquinas virtuales, por
  ejemplo la que pide una asignatura con su propio software. Un asistente de cuatro pasos crea una clave solo para esa
  máquina y una redirección de puerto que solo se alcanza desde tu PC, te da los comandos para pegar dentro de la
  máquina (la contraseña de la máquina nunca pasa por el panel), prueba la conexión y te deja elegir qué agentes la
  usan y con qué notas. Desde el panel también la enciendes, la reanudas, la apagas y ves su pantalla.
- **Herramientas `vm_*` para los agentes** con la capacidad «ordenador»: comandos, archivos, copiar desde la vault o tus
  entregables y hacia tus entregables, capturas, ratón y teclado, y leer webs con el navegador de la máquina y la sesión
  que hayas abierto en él. Todo queda en la auditoría.
- **Tutor:** nuevo modo para trabajar en esas máquinas (crear, probar y sacar los resultados a `/entregables`).

### Arreglos

- **Navegador del campus:** la herramienta con la que el agente lo lee no arrancaba en imágenes construidas con versiones
  recientes de Playwright (faltaba `libatomic1`).
- **Host Agent y VirtualBox:** con su `/tmp` aislado no veía las máquinas del usuario (las daba por apagadas) y `ssh`
  rechazaba la configuración del sistema.

### Al actualizar

- `bin/pos actualizar` regenera los servicios: el Host Agent pasa a compartir solo la carpeta `/tmp/.vbox-<usuario>-ipc`.
- Si usas el navegador del campus, reconstruye su imagen
  (`docker build --target canvas -t <instancia>-vc:canvas control-center/virtual-computers/images`) y vuelve a crear
  ese ordenador desde el panel. Tendrás que iniciar sesión en el campus otra vez.

### Ya incluido de antes

- Inicio con tu asistente (check-in de mañana y noche, avisos y resumen del día) y un asistente por apartado.
- Módulos que activas y desactivas: Agenda, Correo, Educación, Entrenamiento, Salud, Finanzas, Carrera, Objetivos,
  Estilo de vida, Conocimiento, Proyectos, Ayudante, Vídeos, Ordenadores virtuales, Voz y avisos por Telegram.
- Finanzas conectadas a tu banco en solo lectura (Enable Banking), con asistente en el panel.
- Motores de IA a elegir: Claude Code, Codex, OpenRouter (con OpenCode) y Antigravity.
- Onboarding guiado por apartado; el de Educación puede leer tu campus en un navegador aislado.
- Ordenadores virtuales aislados (contenedores endurecidos) para ti y para los agentes.
