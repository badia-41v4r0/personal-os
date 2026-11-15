# Educación

Página `/educacion/` con seis pestañas (`?tab=`): **Hoy**, **Asignaturas**, **Plan**, **Repaso**, **Cruces** y **Archivos**.
Backend: `backend/app/modules/education.py` (API `/api/v1/education/*`); las casillas de siempre siguen en
`/api/v1/me/education` y marcan igual que el Panel de Obsidian. Todo se calcula con datos reales y sin modelo.

## Qué hay
- **Cómo vas:** bloques hechos frente a planificados hasta hoy; restantes frente a la capacidad real hasta el 22/01
  (`planificador.bloques_dia`) y los avisos del propio planificador. Con `hechos.json` y las marcas del Panel.
- **Asignaturas:** nota actual y estado (`notas.py`), semáforo (rojo: entrega atrasada de los últimos 14 días o mínimo
  incumplido; ámbar: entrega a ≤3 días), siguiente entrega, bloques y tarjetas pendientes. Botones que le piden algo al tutor.
- **Plan:** semana y mes con bloques y entregas; estado de cada entrega (sin empezar, en curso, revisando, entregada;
  «entregada» = marcarla con `uni.check`, una sola fuente de verdad).
- **Estudiar ahora:** manda al tutor el bloque en curso con sus entregas y tarjetas, y arranca el cronómetro. El tiempo
  real (`edu_study_sessions`) se compara con los 120 min que supone el plan.
- **Reprogramar desde hoy:** `planificador.planificar` + `escribir` (lo mismo que el recálculo del domingo, a demanda).
- **Plan → Google Calendar:** un clic crea los bloques de 7 días con la marca `jarvis=1` (una vez por bloque).
- **Repaso espaciado:** SM-2 con cuatro respuestas (`edu_cards`). Las tarjetas las crea el usuario o el tutor con la
  capacidad `uni.card.add` (nivel 1, deshacible). Simulacro cronometrado: primero tipo examen y las más falladas.
- **Canvas:** el calendario de Canvas llega por Google Calendar; se compara con la foto anterior (`edu_canvas_*`) cada
  vez que corren los recordatorios (9:00) o con «Comprobar». La primera lectura es la línea base y no avisa. Aviso por
  cambio (movido, nuevo, retirado) y banner en Hoy. Hay que confirmar en el aula antes de mover nada.
- **Cruces:** ofertas del radar por asignatura (palabras clave en `HABILIDADES`), sueño/entreno frente a bloques hechos
  (solo con datos suficientes), pagado a el campus según el ledger y coste por crédito (créditos anotados a mano).
- **Archivos:** explorador de `archivos/Uni/<ASIG>/`. Ver (md, texto, PDF, imágenes), descargar, subir y crear carpetas;
  **no borra ni renombra**. Nada activo (HTML, SVG) se ve en línea. Rutas sin `..`, ocultos ni enlaces simbólicos.

## El tutor y los archivos
`tutor` (v6 del archivo `agents/tutor.md`) deja los entregables en `/entregables/<ASIG>/<tarea>/` con un `LEEME.md`.
El Host Agent monta **solo** `archivos/Uni` en `/entregables` (lectura y escritura) y no la carpeta común entera; hace falta
nivel `propose` o `execute`. Modos nuevos del tutor: repaso (tarjetas), revisión de borradores y cambios de Canvas.

## Pruebas
`backend/tests/test_education.py` (15), `host-agent/tests/test_sesiones.py` (montaje y permisos) y `apps/web/e2e/educacion.spec.ts`
(pestañas en escritorio y móvil; con `CC_E2E_EDU_MUTA=1`, y solo contra un backend de prueba, repaso y subida de archivos).

## Limitaciones
- Las fechas de Canvas dependen de que el calendario de Canvas esté visible en Google Calendar y de que el permiso de Google esté vigente.
- Cruces: la correlación sueño/entreno usa pocos días; el coste exige que el ledger tenga gastos con «campus».
- Las tarjetas dependen de que el tutor las genere; no hay generación sin modelo.
