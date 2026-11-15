# Cierre del día

Úsalo cuando el usuario te cuente su día (suele ser por la noche, tras el recordatorio), o cuando la orden diga "cierre automático".

## Entradas
- **Panel del día:** `/vault/Jarvis/Panel.md` (su fecha está en el frontmatter `fecha:`). En cierre automático te indican otro archivo: el Panel archivado.
  - Casillas `[x]` = hecho, `[ ]` = no hecho.
  - `## 📝 Notas del día` = lo que apuntó él.
- **Su resumen**, si lo hay. Es la fuente principal: manda sobre las casillas.
- El día del diario es **la fecha del Panel**, no la hora actual (puede escribirte pasada la medianoche).

## Qué hacer
1. **Panel** (solo si es el de hoy, no en cierre automático): marca `[x]` lo que te diga que ha hecho y no está marcado. Usa solo las casillas existentes.
2. **Tareas** (por acciones, **no edites `Tareas.md`**: es una copia que genera el sistema; consulta la lista con `tasks.list`):
   - Las que diga que ha terminado → `pos_action` `task.done` con el texto de la tarea.
   - Las nuevas que mencione → `task.create` con texto, fecha (`AAAA-MM-DD`) y área.
   - Si dice que algo se pasa a otro día → `task.reschedule`.
3. **Áreas**: actualiza solo lo que haya cambiado, en pocas líneas:
   - Candidaturas, entrevistas o respuestas → **por acciones, no edites la tabla de `Trabajo.md`** (es una copia): `career.application.create` o `career.application.update` (estado, próximo paso y follow-up a 7 días). Busca el id con `career.list`.
   - Cumpleaños, vencimientos o suscripciones → `Personal.md`.
4. **Gym**: si manda pesos, regístralos con `gym.register` (formato y nombre de la sesión según `Sistema/gym.md`; **no escribas en `Areas/Gym.md`**, su `## Registro` es una copia). Si no, mira si la sesión de ese día ya está en `## Registro` de `Areas/Gym.md` (puede venir de Hevy) antes de decir que no hay pesos. Para corregir un entreno ya registrado, `gym.workout.replace`.
   - Si una acción devuelve `pending` o `denied`, no insistas ni edites la nota: cuéntalo en la respuesta.
5. **Diario** (por acción, **no escribas en `Diario/`**: sus notas son copias que genera el sistema): `pos_action` `journal.write` con `fecha` (la del Panel), `modo: crear` y `contenido` con este texto:
   ```
   ---
   fecha: AAAA-MM-DD
   cierre: manual | automático
   ---
   # 📓 {día de la semana} {día} de {mes}

   ## ✅ Hecho
   - (por área: estudio con los bloques hechos/total, tareas, gym)

   ## ⏳ Pendiente
   - (lo no hecho; los bloques de estudio se replanifican el domingo)

   ## 📝 Notas
   (su resumen condensado y sus notas del Panel; sin inventar)
   ```
6. **Respuesta** (solo en cierre manual; en el automático responde exactamente `SILENCIO`), como respuesta final, máximo 6 líneas:
   - "📓 Día cerrado: {bloques hechos/planificados} · {tareas hechas} · {gym sí/no}"
   - Qué has anotado y dónde.
   - Si falta algo importante para mañana (entrega en ≤2 días sin avanzar), dilo en una línea.

## Reglas
- No inventes nada. Si algo del resumen es ambiguo (qué tarea, qué fecha), pregunta antes de escribirlo.
- Si ya existe el diario de ese día (`journal.write` lo dice), vuelve a llamarla con `modo: anadir` y un `contenido` que empiece por `## Actualización`, en lugar de reescribirlo.
