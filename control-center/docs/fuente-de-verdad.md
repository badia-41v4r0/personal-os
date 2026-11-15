# Fuente de verdad: base de datos y copias en la vault

Plan `compiled-stirring-cocoa`, fase 3. En cada dominio hay **un solo sentido** a la vez. Cuando manda la base, la nota de la vault es una copia que rehace `modules/mirror.py` tras cada escritura, y `modules/vault_sync.py` la concilia cada 10 minutos: lo editado a mano se descarta y se avisa.

| Dominio | Manda | Copia | Qué se acepta de la copia | Marca de corte (`data/control-center/`) |
|---|---|---|---|---|
| Tareas | base (`tasks`) | `Jarvis/Tareas.md` | marcar o desmarcar casillas | `fuente-tareas-bd` |
| Candidaturas | base (`job_applications`) | tabla «Pipeline de candidaturas» de `Areas/Trabajo.md` | nada (el resto de la nota sí es editable) | `fuente-empleo-bd` |
| Diario | base (`journal_days`) | `Jarvis/Diario/AAAA-MM-DD.md` y `Diario/Semana AAAA-MM-DD.md` | nada | `fuente-diario-bd` |
| Entrenos | base (`workouts`) | `## Registro` de `Areas/Gym.md` | nada (Rutina, Perfil y lo que vaya tras el registro sí son de la nota) | `fuente-gym-bd` |
| Marcas (uni, Panel) | base (`vault_records`, tipo `hecho`) | `Sistema/hechos.json` | marcas y desmarcas (las vuelca `build.py` desde el Panel); no perderla | `fuente-uni-bd` |
| Uni: notas semanales, plan, Notas-Uni | vault (documentos) | — (la base espeja) | — | no se invierte (decisión del 07/11) |

La primera pasada después del corte siembra la base desde la nota y deja la marca. Para volver atrás: revertir el commit y borrar la marca.

## Diario (07/11)
- **Quién escribe:** la rutina (`cierre` y revisión semanal) con la acción `journal.write` (nivel 1, con deshacer): `fecha`, `tipo` (`dia` | `semana`), `modo` (`crear`, `anadir` para una `## Actualización`, `reemplazar`) y `contenido`. Instrucciones en `Sistema/cierre.md` y `Sistema/revision-semanal.md`.
- **Copia:** el texto tal cual, con el aviso «Copia generada…» justo después del frontmatter. La base guarda el texto sin el aviso.
- **Conciliación:** una nota con fecha editada o borrada se rehace; una nota con fecha que la base no tiene se quita. Lo descartado se guarda antes en `data/control-center/descartes/diario/` y se avisa una vez por pasada. Los conflictos de Syncthing y las notas sin fecha en el nombre no se tocan.
- **Permisos:** las sesiones con escritura en la vault (la rutina) tienen denegado `Edit`/`Write` en `Jarvis/Diario/**` y `Jarvis/Tareas.md` (`host-agent/sesiones.py`, `COPIAS`). Memory las enseña en solo lectura.
- **Lectores sin cambios:** `estado_dia.py cerrado`, `manana.sh`, `noche.sh`, `navegacion.py` y la Agenda siguen leyendo los archivos: la copia se escribe en el mismo momento que la base.

## Entrenos (07/11)
- **Quién escribe:** el panel (`POST /gym/register`, importación de Hevy) y los agentes (`gym.register`, `gym.workout.replace`). Todos preparan el registro completo nuevo a partir de la base (`mirror.workouts_text`) y lo pasan a `vault_sync.write_workouts`, que lo guarda y rehace la nota.
- **Copia:** `## Registro` con el aviso y las sesiones ordenadas por fecha. Lo de antes (Rutina, Perfil) y las secciones `## ` de después se conservan tal cual. Los cálculos (`gym_stats`, Coach, `semanal.py`, `gym.py`) siguen leyendo la copia.
- **Conciliación:** si el registro de la nota no coincide con la base, se guarda la nota entera en `descartes/gym/`, se rehace y se avisa. Nunca se descarta si la base no tiene entrenos: entonces se vuelve a importar de la nota.
- **Siembra segura:** la marca se escribe solo cuando se confirma la transacción, y si dos sesiones siembran a la vez gana la primera (la otra no falla).
- `collectors/hevy_import.py` por línea de comandos se niega a escribir tras el corte: el CSV se sube en el panel.

## Marcas de la uni (07/11)
- Decisión del usuario: **solo las marcas**. Las notas semanales, el plan diario y `Notas-Uni.md` siguen siendo documentos de la vault; `planificador.py` y `notas.py` no cambian.
- **Quién escribe:** el panel y Jarvis (`uni.check`, `/me/education/check`, calendario) marcan primero en la base (`vault_sync.set_hecho`) y rehacen `hechos.json`; la casilla del Panel y, en entregas y objetivos, la de la nota semanal se ponen igual.
- **Copia:** `hechos.json` (clave → fecha), que siguen leyendo `planificador.py`, `semanal.py` y `build.py`. `build.py` vuelca ahí cada mañana las casillas del Panel: esas marcas y desmarcas se aceptan.
- **Lo que protege:** si `hechos.json` desaparece, no se puede leer o pierde de golpe más de la mitad (con 4 o más), se rehace desde la base (lo nuevo que traiga sí entra) y se avisa; la versión rota se guarda en `descartes/uni/`. Antes, perderlo hacía que el replan del domingo diera por no hecho todo lo estudiado.
