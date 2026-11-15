# Gym 2.0 — entrenador, planificador y analista

Hevy registra, Jarvis entrena, el panel enseña. Flujo: el motor prepara la sesión → el usuario la acepta (o la modifica) en
**Gym → Training** → entrena con Hevy como siempre → el entreno llega a `Areas/Gym.md` (Jarvis por Telegram o el
importador del CSV) → el panel lo asocia con lo planificado, compara, actualiza estadísticas y propone el siguiente.

## Arquitectura

```
Hevy ──CSV──▶ hevy_import.py ──┐            (Telegram: Jarvis escribe las series)
                               ▼
                 Jarvis-Vault/Jarvis/Areas/Gym.md   ← fuente de verdad de los ENTRENOS (no se duplica)
                               │
          collectors/gym_stats.py (parseo, volumen, músculos, e1RM)
          collectors/gym_coach.py (motor: roles de series, objetivos, estancamientos, récords, recuperación,
                               │   plan frente a realizado, calendario, reprogramación, informes)
        ┌──────────────────────┼─────────────────────────────┐
        ▼                      ▼                             ▼
 backend app/gym.py      control-center/gym/gym_mcp.py   Jarvis (CLI: gym_coach.py, gym_stats.py)
 + app/gym_plan.py       (MCP del Coach, solo lectura,
 SQLite: lo del           en el contenedor efímero)
 entrenador
        ▼
 web: Gym (Overview · Training · Progress · Recovery · History · Routines · Coach)
```

- **Un solo cálculo.** Panel, Coach y Jarvis llaman a las mismas funciones. Los prompts no contienen lógica: el Coach
  interpreta resultados de herramientas.
- **Entrenos:** solo en `Gym.md`. El panel no los copia; los lee con caché por firma del archivo.
- **Del entrenador (SQLite, migración `0004_gym_2`):** `gym_routines` + `gym_routine_versions`,
  `gym_planned_sessions` + `gym_planned_versions`, `gym_exercise_settings` (rango, series, incremento, método,
  descanso, categoría y músculos por ejercicio), `gym_exercise_aliases`, `gym_recovery_logs`, `gym_coach_decisions`,
  `gym_reports` (único por tipo y periodo), `gym_imports` y `gym_hevy_workouts` (trazabilidad de Hevy: id externo,
  inicio, fin, duración y filas originales).
- Equivalencias con el modelo pedido: Workouts/WorkoutExercises/Sets = `Gym.md` parseado; ExerciseDefinitions,
  MuscleGroups y ExerciseMuscles = `gym_musculos.json` + `gym_exercise_settings`; TrainingPlans/Versions/
  PlannedExercises/ProgressionTargets = sesiones planificadas versionadas (cada ejercicio guarda su objetivo);
  PersonalRecords = calculados (no se guardan: se recalculan siempre igual); CoachRecommendations = decisiones en
  estado `propuesta`.

## Tipos de dato (siempre etiquetados)

| Nivel | Qué es | Ejemplos |
|---|---|---|
| registrado | Lo que pone Hevy/Gym.md | pesos, reps, calentamientos, récords reales, sensaciones |
| calculado | Cálculo exacto | volumen, series efectivas, series por músculo, cumplimiento |
| estimación | Fórmula | e1RM (Epley), duración prevista |
| inferencia | Patrón del motor | top set/back-off/aproximación, estancamiento, carga alta, correlaciones |
| recomendación | Propuesta | objetivo del próximo entreno, reprogramar, propuestas del Coach |

## Fórmulas y criterios

- **Serie efectiva:** no marcada `(cal.)`. **Volumen** = Σ peso × reps efectivas (peso corporal no suma kg). Volumen
  ≠ intensidad; series totales ≠ efectivas.
- **Series por músculo:** principal 1, secundario 0,5 (configurable en `/muscles?peso_secundario=`). Aproximación
  analítica, no medida fisiológica.
- **e1RM (Epley):** `peso × (1 + reps/30)`, solo 1–12 reps efectivas. Siempre «estimado»; nunca se presenta como
  levantado. No se mezcla con otras fórmulas.
- **Papel de cada serie** (método del usuario, `Sistema/gym.md`): top set = la más pesada con ≥3 reps; antes de ella y
  más ligeras = aproximación (inferida); ≤2 reps por encima = intento; resto = back-off. `(cal.)` = calentamiento
  (registrado).
- **Configuración por ejercicio:** categoría por nombre (compuesto 6–10, máquina 6–10, aislamiento 10–15, peso
  corporal 5–10); incremento = el paso más frecuente entre los pesos que has usado (respeta las placas de tu gym)
  o, si no hay datos, por equipo (barra 2,5, mancuerna 2, máquina 5, polea 2,5). Todo editable en Progress →
  ejercicio → «Progresión de este ejercicio».
- **Objetivo (top set + back-offs, doble progresión en el top set):** tope del rango → +incremento y vuelta al
  mínimo; dentro → mismo peso, +1 rep; por debajo → mismo peso (+1 rep si está muy por debajo, con la alternativa
  calculada por e1RM); dos sesiones por debajo → −5–10 %. Si el rendimiento cayó >5 % entre las dos últimas, no sube.
  Back-offs ≈ −10 %. **Doble progresión clásica** (series rectas) disponible por ejercicio: 60×10/9/8 → 60×10/10/9.
- **Molestias** (Perfil de Gym.md o sensaciones de los últimos 10 días): los ejercicios que cargan la zona (`ZONAS`
  en `gym_coach.py`) repiten el último top set a RIR 2–3, sin subir; nunca se recomienda entrenar con dolor.
- **Estancamiento** (ventana sobre el rendimiento del top set = e1RM o reps con peso corporal): «estancado» = 3+
  sesiones seguidas sin superar la mejor previa (+1 %) y ≥10 días; «retroceso» = dos bajadas seguidas ≥3 %.
  Confianza alta con 4+ sesiones sin huecos >21 días, baja si hay huecos. Nunca por una sola sesión.
- **Récords:** reales (peso máximo, más reps con el peso del top set, volumen en una serie, volumen en la sesión) y
  estimado (mejor e1RM). La primera sesión de un ejercicio fija la marca sin contar como récord.
- **Plan frente a realizado:** asociación automática solo si coinciden fecha y nombre de la sesión; si no, manual
  (Training → Planificadas → Asociar). Cumplido = top set con peso y reps objetivo; parcial = peso o e1RM a ≤3 %;
  omitido = 0. Lista de añadidos y omitidos, volumen previsto y real.
- **Recuperación (orientativa):** series de 7 días frente a la media semanal de las 3 anteriores; «carga alta» >1,5×.
  Correlación de Pearson entre sensaciones y el cambio medio del top set, solo con ≥6 días. No mide la recuperación,
  no diagnostica, correlación no es causa.
- **Reprogramación:** una sesión perdida se recoloca en un hueco de esta semana que no quede pegado a otra con los
  mismos músculos principales; si no hay, se propone no recuperarla.
- **Duración prevista:** mediana de minutos por serie de tus sesiones con duración de Hevy; si no hay, 45 s por serie
  + descansos + 1 min por ejercicio. Es estimación. Descansos y RPE: solo si están registrados.

## Nada se aplica solo

- Una recomendación es recomendación hasta que la aceptas. Al aceptar, se guarda como sesión planificada v1 y las
  decisiones con peso (subir, bajar, consolidar, precaución) quedan en el historial con su objetivo, para evaluarlas
  con el entreno real (cumplido, parcial, no cumplido o pendiente).
- Editar una sesión planificada crea una versión; lo no cambiado conserva el objetivo y la explicación del motor. Lo
  ya realizado no se edita. Una nueva planificación el mismo día deja la anterior como «sustituida».
- Rutina activa: cambiarla, activarla o restaurar una versión pide confirmación (428) y motivo; cada cambio es una
  versión con autor, motivo, cambios y resultados posteriores.
- El Coach no tiene herramientas de escritura: `proponer_cambio` y `proponer_rutina` dejan un JSON que el panel valida
  y convierte en una decisión «propuesta» (Gym → Coach: aceptar o rechazar). Aceptar una rutina crea una versión de
  la activa (o una rutina nueva en borrador).

## Coach

- Conversación independiente propia (`kind=independent`, nombre «Coach del gym»), una por usuario, con las
  instrucciones de `control-center/gym/coach.md` (se actualizan solas en cada turno).
- Contenedor efímero como el resto de conversaciones: sin Bash, sin internet, vault en solo lectura, más el servidor
  MCP `gym` y el motor montados en solo lectura en `/opt/gym`. Antes de cada turno el panel escribe
  `data/sesiones/<id>/gym/estado.json` (rutina, planificación, ajustes, sensaciones, decisiones); después recoge
  `gym/salida/*.json` (máx. 20, 200 KB). Lee `/gym` solo a través del MCP (Read de `/gym` y `/opt` denegado).
- Herramientas: `resumen`, `historial`, `sesion`, `ejercicio`, `progresion`, `records`, `musculos`, `planificacion`,
  `siguiente_sesion`, `recuperacion`, `decisiones`, `proponer_cambio`, `proponer_rutina`.

## Hevy

- Sin API (no hay Pro). Fuente real: el **CSV de exportación**. Se sube en History → Importar de Hevy o se manda a
  Jarvis por Telegram (el panel lista los CSV de Hevy de la bandeja del plugin y los importa con un clic).
- Vista previa → aplicar. Solo se añaden a `Gym.md` los días que aún no están (idempotente por fecha, como siempre);
  dos entrenos el mismo día no se fusionan solos. Escritura atómica. Errores por fila (fecha, peso, reps ilegibles)
  y avisos (tipo de serie desconocido, filas sin datos) quedan registrados en `gym_imports`.
- Trazabilidad: `external_id` = hash de título + inicio; duración, filas originales y a qué sesión de Gym.md
  corresponde. Las series `warmup` se escriben `(cal.)`; sin marca no se clasifica nada como calentamiento.
- Corrección de asociaciones: alias (otro nombre = este ejercicio) y músculos por ejercicio, sin tocar Gym.md.

## API (`/api/v1/gym`, sesión obligatoria; las que modifican exigen admin, CSRF y Origin)

Lectura: `overview`, `workouts` (filtros `desde`, `hasta`, `ejercicio`, `musculo`, `tipo`), `workouts/{id}`,
`workouts/{a}/compare/{b}`, `exercises`, `exercises/{id}`, `exercises/{id}/progress?periodo=7d|28d|3m|6m|1a|todo|custom`,
`exercises/aliases`, `statistics`, `muscles`, `records`, `stagnation`, `analysis`, `recovery`, `calendar`,
`recommendations`, `plans`, `plans/{id}`, `routines`, `routines/{id}`, `coach`, `coach/decisions`, `reports`,
`reports/{id}`, `imports`.
Escritura: `POST recommendations/{id}/accept|reject` (`siguiente`, `reprog-<fecha>` o id de decisión),
`POST plans`, `PATCH plans/{id}`, `POST plans/{id}/link`, `PUT exercises/{id}/settings`, `POST|DELETE exercises/aliases`,
`POST|DELETE recovery`, `POST routines`, `PATCH routines/{id}`, `POST routines/{id}/duplicate`,
`POST routines/{id}/restore/{v}`, `POST coach/decisions`, `POST coach/decisions/{id}/accept|reject`, `POST coach/chat`,
`POST reports/generate`, `POST reports/{id}/send` (Telegram, por el Host Agent), `POST import/hevy`,
`POST import/{id}/apply`.

## Informes

Semanal y mensual con los mismos cálculos. Se generan al abrir la lista para cada periodo cerrado (8 semanas y 3 meses
atrás), uno por periodo (restricción única), y se pueden regenerar. El envío a Telegram es manual desde el panel
(el resumen corto de `texto_informe`); no hay envío automático para no duplicar la revisión semanal del domingo.

## Jarvis (CLI)

`python3 /workspace/collectors/gym_coach.py siguiente | objetivo "<ejercicio>" | estancados | records [--dias N] |
musculos [--semanas N] | recuperacion | analisis` (con `--json` para salida estructurada). Ya cubierto por el permiso
`python3 /workspace/collectors/*`. La CLI no ve lo guardado en el panel (rutina activa, ajustes, sensaciones); para
eso está el Coach.

## Pruebas

- `backend/tests/test_gym_coach.py` (motor, importador y MCP), `test_gym_api.py` (API con persistencia, versiones,
  confirmaciones, importación idempotente, informes y propuestas del Coach), `test_gym.py` (parseo) y
  `host-agent/tests/test_sesiones.py::test_coach_del_gym` (montajes y permisos).
- `apps/web/e2e/gym.spec.ts`: navegación, filtros, gráficos, detalle, comparación, Coach; con `CC_E2E_GYM_MUTA=1`
  (solo contra un backend de prueba) también aceptar/modificar el plan, editor de rutinas y sensaciones.
- Entorno de prueba aislado: `CC_WEB_OUT=out-prueba npm run build` y un backend con `CC_WEB_DIR`, `CC_DATA_DIR`,
  `CC_VAULT` (copia de Gym.md) y otro puerto. Así no se toca el `out` que sirve el panel en marcha.

## Limitaciones

- Duración y descansos: solo con entrenos importados del CSV (lo que llega por Telegram no la trae).
- La asociación automática plan↔entreno exige misma fecha y nombre (por diseño).
- Las correlaciones de sensaciones necesitan ≥6 días con sensaciones y entreno.
- Con pocas semanas de historial casi todo es «progresa» o «pocos datos»: las confianzas lo reflejan.

## Periodos sin entrenar (pausas)

Enfermedad, lesión, vacaciones u otro motivo, con fecha de inicio y de fin (sin fin = en curso). Tabla `gym_pauses` (migración `0018`).

- **Dónde se apuntan:** Gym → Recovery → «Periodos sin entrenar» (añadir, terminar hoy, borrar), `POST /api/v1/gym/pauses`, o la acción `gym.pause.log` (nivel 1, con deshacer) que tienen Jarvis, el Coach y la rutina. No se pueden solapar dos pausas.
- **Calendario:** los días previstos dentro de una pausa salen como `pausa`, no como `perdido`, y no se proponen para reprogramar.
- **Informe y portada:** esos días no cuentan como sesiones previstas (`dias_en_pausa`, `pausas` en el informe). La portada resta los días laborables en pausa de la semana y el insight dice «En pausa del gym» o «Semana de pausa» en vez de «vas por detrás».
- **Vuelta (recomendación, `gym_coach.vuelta_de_pausa`):** solo tras pausas de 4 días o más y durante los 21 días siguientes. Primera vez de cada ejercicio: ~90 % del último top set de antes, mismas reps, RIR 2. Segunda: la carga de antes si la primera llegó al 85 % de su rendimiento; si no, se sigue el objetivo normal con el aviso. Después, progresión normal. Con una molestia activa manda la precaución.
- Las sensaciones (`gym_recovery_logs`) siguen siendo solo informativas salvo `molestia_zona`.

