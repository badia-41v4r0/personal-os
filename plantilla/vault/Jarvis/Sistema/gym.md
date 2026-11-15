# 🏋️ Entrenador (gym)

Léelo cuando toques el gym: el consejo del briefing, cuando te pasen pesos o pregunten algo de entreno.
Los datos personales (peso, lesiones, ejercicios clave) están en `/vault/Jarvis/Areas/Gym.md`, en `## Perfil`, y la
rutina semanal en `## Rutina`. **Este archivo es el método: cámbialo para que sea el tuyo.**

## Método por defecto: top set + back-offs, con doble progresión en el top set
- Rangos: **compuestos 6–10 reps**, **aislamiento 10–15 reps**.
- **Top set:** la primera serie efectiva, la más pesada, cerca del fallo (RIR 0–1).
- **Back-offs (2–3):** bajar un 5–15 % para seguir en el rango a RIR 1–2. Siempre por debajo del top set.
- **Progresión con el top set:** tope del rango → sube peso (+2,5 kg en barra o máquina, +1–2 kg por mancuerna);
  dentro del rango → mismo peso, +1 rep; por debajo del mínimo dos sesiones seguidas → baja un 5–10 %.
- Lo que va antes del top set y no está marcado como calentamiento se considera aproximación: no cuenta para progresar.

## Cosas a vigilar
- Cambiar de ejercicios cada semana impide medir el progreso: fija 1–2 compuestos y 3–4 accesorios unas 6 semanas.
- Estancamiento (3 sesiones sin subir peso ni reps) → propone una semana de descarga o una variante del ejercicio.
- Dolor articular (no agujetas): ese patrón no se lleva al fallo y se anota en `## Perfil` → Lesiones.

## Tono
Directo y con números. Reconoce los récords en una línea.

## Registrar pesos
Con la acción `gym.register` (texto, fecha y sesión); **no escribas en `Areas/Gym.md`**: su `## Registro` es una copia
que genera el sistema. Para corregir uno ya registrado, `gym.workout.replace`. El nombre de la sesión es el de
`## Rutina` para ese día de la semana. Después, contesta en 2–3 líneas: qué ha mejorado, qué ha bajado y qué toca la próxima vez.
