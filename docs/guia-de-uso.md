# Guía de uso

El panel tiene **Inicio** (tu asistente, que lo ve todo; se llama Jarvis salvo que le pongas otro nombre en Configuración → Tú y tu asistente) y un apartado por módulo activo. Cada apartado tiene a la derecha su
propio asistente (en el móvil, en la barra de abajo), que solo ve el contenido de ese apartado.

## Lo que conviene saber primero

- **Nada importante se hace sin ti.** Los agentes piden acciones. Las de poco impacto (marcar una tarea, registrar un
  entreno) se hacen solas y se pueden deshacer. Las que salen fuera (crear un evento, un borrador de correo) o cambian
  la configuración esperan tu aprobación en **Tareas → Aprobaciones** (te llega un aviso) o en la propia tarjeta. Enviar correos o dinero no existe.
- **Tus datos de verdad viven en la base** del panel. Algunas notas de la vault son copias que el sistema rehace (tareas,
  registro del gym, diario, tabla de candidaturas). Lo demás de la vault son tus documentos.
- **Configuración → Módulos** activa y desactiva apartados. **Configuración → Motor de IA** elige el modelo.

## Apartados

**Inicio.** Resumen del día, check-in de mañana (ánimo, energía, sueño) y de noche («Guardar y cerrar el día» pide a
la rutina que escriba tu diario). Tu asistente responde a cualquier cosa y puede delegar en los demás apartados.

**Agenda y Tareas.** Calendario unificado (Google, entregas, tareas con fecha, sesiones de gym, seguimientos de
candidaturas, vencimientos). Conecta Google en Configuración → Permisos de Google. Las tareas se crean aquí, por
tu asistente o en el cierre del día.

**Educación.** Asignaturas, entregas, plan de estudio con bloques según tu disponibilidad, cronómetro, repaso
espaciado (tarjetas) y simulacros. El **tutor** tiene un ordenador virtual con tu campus: inicias sesión tú una vez
(Agentes → Ordenadores → Campus → Escritorio) y él lee anuncios, entregas y materiales. **Solo lee**: nunca entrega ni
publica nada. Lo que te prepara aparece en Educación → Archivos.

**Entrenamiento.** Registra entrenos (o importa el CSV de Hevy), mira progreso, récords, volumen por músculo y la
recomendación de pesos para hoy. El Coach propone cambios de rutina que tú aceptas o rechazas. Si estás enfermo o de
viaje, marca un periodo sin entrenar y la vuelta será prudente.

**Salud, Objetivos y Estilo de vida.** Medidas, objetivos con hitos y hábitos, viajes, compras, suscripciones y garantías.

**Finanzas.** Contabilidad de partida doble: importa el extracto del banco (CSV; Revolut tiene importador propio) o
la foto de un ticket. Lo que no se pueda clasificar queda pendiente y no cuenta hasta que lo revises. Presupuesto
mensual por categoría.

**Carrera.** Candidaturas, ofertas del radar (lee las alertas de empleo de tu correo y las puntúa con tus reglas) y
solicitudes con agente: rellena el formulario en un navegador aislado y **tú apruebas el envío** viendo exactamente
lo que se mandará.

**Conocimiento.** Explora, busca y edita tu vault de Obsidian. «Qué sé de ti» enseña la memoria: lo que los agentes
deducen nace como propuesta y lo confirmas tú.

**Proyectos.** Tus repos de GitHub: commits, PRs e issues. El programador trabaja en una copia, solo en la rama
`staging`, sin red salvo los registros de paquetes, y nunca hace push: lo sube tu PC y abre un PR.

**Automatizaciones.** Horario de las rutinas (briefing, cierre, revisión semanal, recopilación). Cambiarlo no toca los
archivos del proyecto.

## Onboarding de cada apartado

La primera vez que abres un apartado aparece «Primera vez en…». Con **Configurar con el asistente** se abre un chat que
te pregunta lo necesario y te deja una propuesta para aprobar. **Ahora no** la quita; puedes volver a lanzarlo desde
Configuración → Módulos → «Configurar con su asistente».

## Telegram (opcional)

Solo de salida: copia las alertas críticas a un bot tuyo (`TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` en `.env`). Lo que le escribas al bot no lo lee nadie.
