# Guía de uso

## Cómo está ordenado el panel

El menú de la izquierda tiene tres bloques y, abajo, Ajustes:

- **Hoy:** Inicio, Bandeja, Agenda y Tareas. Lo que miras cada día.
- **Tus áreas:** un apartado por módulo activo (Educación, Entrenamiento, Salud, Finanzas, Carrera, Objetivos, Estilo
  de vida, Proyectos). Lo desactivado no aparece.
- **Conocimiento:** tu vault de Obsidian y «Qué sé de ti».
- **Ajustes:** todo lo que se configura o se conecta, en un solo sitio (ver más abajo).

Cada apartado tiene a la derecha su propio asistente (en el móvil, el botón del centro de la barra de abajo), que solo ve
el contenido de ese apartado. El de Inicio es tu asistente general: se llama Jarvis salvo que le pongas otro nombre en
Ajustes → Tú y tu cuenta. Su icono de pantalla completa abre **Conversaciones**, con el historial.

`Ctrl+K` (o la lupa) busca apartados, secciones de Ajustes y notas de tu vault.

## Lo que conviene saber primero

- **Nada importante se hace sin ti.** Los agentes piden acciones. Las de poco impacto (marcar una tarea, registrar un
  entreno) se hacen solas y se pueden deshacer. Las que salen fuera (crear un evento, un borrador de correo) o cambian
  la configuración esperan tu aprobación en la **Bandeja** (la campana de arriba cuenta cuántas hay y te llega un
  aviso) o en la propia tarjeta. Enviar correos o dinero no existe.
- **Tus datos de verdad viven en la base** del panel. Algunas notas de la vault son copias que el sistema rehace (tareas,
  registro del gym, diario, tabla de candidaturas). Lo demás de la vault son tus documentos.
- **Si falta algo por configurar, Inicio te lo dice** («Te falta por configurar»), con un enlace directo a cada sitio.

## Hoy

**Inicio.** Resumen del día, check-in de mañana (ánimo, energía, sueño) y de noche («Guardar y cerrar el día» pide a
la rutina que escriba tu diario). Tu asistente responde a cualquier cosa y puede delegar en los demás apartados.

**Bandeja.** Todo lo que espera tu respuesta, en tres pestañas: **Por decidir** (acciones de los agentes y propuestas de
skills o subagentes), **Avisos** (lo que el sistema te ha notificado) y **Solicitudes** (lo que tu asistente no puede
resolver solo y necesita que hagas en el PC).

**Agenda y Tareas.** Calendario unificado (Google, entregas, tareas con fecha, sesiones de gym, seguimientos de
candidaturas, vencimientos) y tu lista de tareas. Las tareas se crean aquí, por tu asistente o en el cierre del día.

## Tus áreas

**Educación.** Asignaturas, entregas, plan de estudio con bloques según tu disponibilidad, cronómetro, repaso espaciado
(tarjetas) y simulacros. El **tutor** tiene un ordenador virtual con tu campus: inicias sesión tú una vez
(Ajustes → Ordenadores → Campus → Escritorio; también llegas desde Ajustes → Conexiones) y él lee anuncios, entregas y
materiales. **Solo lee**: nunca entrega ni publica nada. Lo que te prepara aparece en Educación → Archivos.

**Entrenamiento.** Registra entrenos (o importa el CSV de Hevy en Historial), mira progreso, récords, volumen por
músculo y la recomendación de pesos para hoy. El Coach propone cambios de rutina que tú aceptas o rechazas. Si estás
enfermo o de viaje, marca un periodo sin entrenar en Recuperación y la vuelta será prudente.

**Salud, Objetivos y Estilo de vida.** Medidas, objetivos con hitos y hábitos, viajes, compras, suscripciones y garantías.

**Finanzas.** Contabilidad de partida doble: importa el extracto del banco (CSV; Revolut tiene importador propio) o
la foto de un ticket. Lo que no se pueda clasificar queda pendiente y no cuenta hasta que lo revises. Presupuesto
mensual por categoría.

**Carrera.** Candidaturas, ofertas del radar (lee las alertas de empleo de tu correo y las puntúa con tus reglas) y
solicitudes con agente: rellena el formulario en un navegador aislado y **tú apruebas el envío** viendo exactamente
lo que se mandará.

**Proyectos.** Tus repos de GitHub: commits, PRs e issues. El programador trabaja en una copia, solo en la rama
`staging`, sin red salvo los registros de paquetes, y nunca hace push: lo sube tu PC y abre un PR.

## Conocimiento

Explora, busca y edita tu vault de Obsidian. La pestaña **Qué sé de ti** enseña la memoria: lo que los agentes deducen
nace como propuesta y lo confirmas tú.

## Ajustes

| Sección | Qué hay |
|---|---|
| Tú y tu cuenta | Usuario y contraseña del panel, cómo te llama tu asistente y cómo se llama |
| Motor de IA | Claude, Codex, OpenRouter o Antigravity, con su token o clave (ver [motores-de-ia.md](motores-de-ia.md)) |
| Módulos | Activar y desactivar apartados, y «Configurar con su asistente» |
| Conexiones | Google, GitHub, campus, Hevy, Telegram y los avisos en el móvil: estado de cada una y cómo conectarla |
| Automatizaciones | Horario de las rutinas (briefing, cierre, revisión semanal, recopilación) |
| Autonomía | Pausar todos los agentes y comprobar la auditoría |
| Avanzado | Agentes, Conversaciones, Ordenadores virtuales, Sistema, Monitor, Colas y temporizadores, Auditoría |

## Onboarding de cada apartado

La primera vez que abres un apartado aparece «Primera vez en…». Con **Configurar con el asistente** se abre un chat que
te pregunta lo necesario y te deja una propuesta para aprobar. **Ahora no** la quita; puedes volver a lanzarlo desde
Ajustes → Módulos → «Configurar con su asistente», o desde «Te falta por configurar» en Inicio.

## Telegram (opcional)

Solo de salida: copia las alertas críticas a un bot tuyo. Activa el módulo «Avisos por Telegram» y pon el token del bot
y tu chat id en Ajustes → Conexiones. Lo que le escribas al bot no lo lee nadie.

## Direcciones antiguas

Si tenías guardadas direcciones de antes (`/gym/`, `/tasks/`, `/settings/`…), siguen funcionando: llevan a su sitio
nuevo.
