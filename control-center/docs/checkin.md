# Check-ins de la mañana y de la noche (Inicio)

Bloque en la portada (`components/cc/checkin-card.tsx`) con una pestaña por franja. La portada sugiere la franja según la hora: mañana hasta las 14:00, noche desde las 19:00 y, entre medias, la que falte.

## Datos
- Tabla `checkins` (migración `0016`): una fila por `(día, franja)`; guardar otra vez la **corrige**. Ánimo y energía de 1 a 5, horas dormidas (mañana), «lo más importante de hoy» (mañana) y nota libre (noche). Todo opcional, pero hace falta al menos algo.
- Los hábitos son los de siempre (`/me/habits/{id}/toggle`); el bloque los enseña y los marca.
- Cada guardado deja un evento de memoria (`checkin.manana|noche`) y una entrada de auditoría.

## API (`modules/checkin.py`, `/api/v1/me/checkin`)
- `GET ?dia=` → check-ins del día, franja sugerida y hábitos con racha.
- `PUT` → crea o corrige (admin, CSRF, Origin). No acepta días futuros.
- `POST /close` → encarga el cierre del día a la rutina `cierre` con lo del check-in de la noche (ánimo, energía, nota y hábitos). El diario lo sigue escribiendo la rutina en la vault; exige haber hecho antes el check-in de la noche.
- `/home` lleva `checkin` y `estado_general` (medias de 7 días; `null` sin ningún check-in: no se inventa nada).

## Avisos e insights
- **22:30:** si falta el check-in de la noche, un aviso (`action`, con push) una sola vez al día, desde `runs.maintenance` → `reminders.run_night`. De la mañana no hay push: se ve al abrir Inicio.
- `bin/noche.sh` (Telegram) ya no avisa en modo `runs`, para no duplicar.
- Insights por reglas: 3 mañanas seguidas con menos de 6 h de sueño, y «ayer sin check-in» (solo si ya hay historial).
