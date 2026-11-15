# Agentes

- **Definición** (apartado Agents) ≠ **conversación** (Chat) ≠ **ejecución** (cada respuesta, con id, herramientas, estado y coste).
- Dos tipos:
  - **Subagente de Jarvis:** se activa escribiendo `agent/.claude/agents/<nombre>.md` (frontmatter `name`, `description`, `tools`, `model`). El panel enseña el archivo y pide confirmación. Jarvis lo carga al empezar sesión (el `/clear` de las 7:00). Ve lo mismo que Jarvis (vault, sin internet) y nunca más.
  - **Agente del panel:** plantilla para lanzar conversaciones independientes con sus instrucciones, capacidad, modelo, internet, vault y ordenador virtual.
- **Subagentes:** un agente del panel puede repartir trabajo con la herramienta `Agent` de Claude Code. Los subagentes viven en el mismo contenedor y heredan exactamente sus permisos (herramientas, ordenador virtual, vault): nunca más. Un subagente de Jarvis no puede lanzar otros ni usar ordenadores (Jarvis no tiene esa pasarela).
- **Agentes externos:** programas propios que lanzan Claude Code (hoy, el orquestador de un proyecto). Se listan en Agents con su estado y se controlan desde su página (Projects → un proyecto-1.0).
- **Entregables:** lo que una conversación deja en su carpeta (`data/sesiones/<id>/trabajo`) se ve y se descarga desde el chat (columna derecha → Archivos).
- **Capacidades:** `read` (Read, Grep, Glob) · `propose` (+ Edit, Write en su carpeta) · `execute` (comandos solo en su ordenador virtual). Todo nace como borrador y sin `execute`.
- **Seguridad:** ningún agente ve el panel ni `agent/.claude` con escritura, así que no puede cambiar su definición ni ampliarse permisos. Subir permisos queda marcado en la auditoría. Las propuestas que haga Jarvis siguen pasando por `bin/aprobar`.
- **Versiones:** cada guardado es una versión restaurable; guardar exige la versión de partida (si otro la cambió, conflicto). Si el archivo de un subagente cambia fuera del panel, se registra como versión nueva.
- Crear uno: Agents → Nuevo agente → rellenar → la vista previa enseña el archivo real y los errores → Guardar borrador → revisar → Activar.
