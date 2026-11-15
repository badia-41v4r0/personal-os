"""Lleva a la base de datos lo que se escribe en la vault, sin borrar nada.

Estado real (07/11): tareas, candidaturas y diario se escriben primero en la base; `Tareas.md`, la tabla del pipeline
de `Trabajo.md` y `Diario/*.md` son copias (`mirror.export_*`) y lo editado a mano en ellas se descarta y se avisa
(de `Tareas.md` solo se aceptan casillas). Entrenos y uni siguen escribiéndose en la vault y se importan aquí.
Es idempotente: se puede repetir sin duplicar. Lo que desaparece del origen se marca con `removed_at`, salvo que el
origen pierda de golpe más de la mitad (nota rota): entonces no se retira nada y se avisa una vez.
Cada sección va en su propia transacción: si una falla, las demás siguen y el fallo queda en el informe.
"""
import hashlib
import json
import re
import sys
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import ROOT, get_settings
from . import mirror
from ..db import session_scope, utcnow
from ..models import (Assessment, DecisionRecord, GradeItem, JobApplication, JobLead, JournalDay, StudyBlock, Subject, Task, VaultRecord,
                      Workout, WorkoutExercise, WorkoutSet)
from ..marca import asistente

sys.path.insert(0, str(ROOT / "collectors"))
FILA = re.compile(r"^\|(.+)\|\s*$")
SECCION = re.compile(r"^## ([^·\n]+?) · ")
DECISION = re.compile(r"^### (\d{4}-\d{2}-\d{2}) · (.+)$")
DESDE = date(2026, 1, 1)
HORIZONTE = 800
PERDIDA_MIN = 4  # desde aquí, perder de golpe la mitad de lo registrado no es una edición: es una copia rota


def _sospechosa(activas: int, quedan: int) -> bool:
    return activas >= PERDIDA_MIN and quedan < activas / 2


_avisadas: set[tuple] = set()


def _retirar(db: Session, model, seen: set[str], nombre: str) -> int:
    """Retira lo que ya no está en el origen, salvo que el origen haya perdido de golpe más de la mitad.

    Aquí manda la vault y no hay copia que rehacer: si parece una nota rota, se conserva lo de la base, se avisa una vez
    y se vuelve a mirar en la siguiente pasada (si la pérdida era real, bastará con editar bien la nota)."""
    activas = db.scalar(select(func.count()).select_from(model).where(model.removed_at.is_(None))) or 0
    if _sospechosa(activas, len(seen)):
        if (nombre, activas, len(seen)) not in _avisadas:
            _avisadas.add((nombre, activas, len(seen)))
            mirror.warn(f"{nombre}: la nota de origen solo tiene {len(seen)} de {activas}. No he retirado nada de la base de datos; revisa que no se haya roto.")
        return 0
    return _mark_removed(db, model, seen)


def sha(*parts) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()


def _table(text: str) -> list[dict]:
    """Filas de las tablas Markdown de un texto, con sus encabezados."""
    out: list[dict] = []
    head: list[str] | None = None
    for line in text.splitlines():
        m = FILA.match(line.strip())
        if not m:
            head = None
            continue
        cells = [c.strip().strip("*").strip() for c in m[1].split("|")]
        if head is None:
            head = cells
        elif not set("".join(cells)) <= {"-", ":", " "}:
            out.append(dict(zip(head, cells)))
    return out


def _mark_removed(db: Session, model, seen: set[str], key: str = "external_id") -> int:
    n = 0
    for row in db.scalars(select(model).where(model.removed_at.is_(None))):
        if getattr(row, key) not in seen:
            row.removed_at = utcnow()
            n += 1
    return n


MARCA_EMPLEO = "fuente-empleo-bd"  # existe desde que la base manda en las candidaturas
MARCA_TAREAS = "fuente-tareas-bd"  # existe desde que la base manda en las tareas


def _clave_tareas(rows) -> dict:
    """(texto, n-ésima repetición) -> fila: dos tareas iguales son dos tareas, en el orden de la base."""
    count, out = {}, {}
    for t in sorted(rows, key=lambda r: r.id):
        n = count[t.text] = count.get(t.text, 0) + 1
        out[(t.text, n)] = t
    return out


def sync_tasks(db: Session, path=None) -> dict:
    """Tareas: manda la base y Tareas.md es una copia que se regenera tras cada cambio.

    De la nota solo se acepta marcar o desmarcar una casilla (así llegan las que se marcan en el Panel o en Obsidian).
    Todo lo demás que se haya hecho a mano (tareas nuevas, textos, fechas o áreas cambiados, líneas borradas) se
    descarta: la nota se rehace desde la base y se avisa. La primera vez siembra la base desde la nota, para no
    perder lo escrito justo antes del cambio."""
    import tareas
    path = path or get_settings().vault / "Jarvis/Tareas.md"
    marca = get_settings().data_dir / MARCA_TAREAS
    if not marca.exists():
        r = import_tasks(db, path)
        marca.parent.mkdir(parents=True, exist_ok=True)
        marca.write_text(utcnow().isoformat())
        return r | {"sembrada": True}
    activas = _clave_tareas(db.scalars(select(Task).where(Task.removed_at.is_(None))))
    if not path.exists():
        mirror.export_tasks(db, path)
        mirror.warn("Tareas.md había desaparecido. La he rehecho desde la base de datos.")
        return {"origen": 0, "cambios": 0, "rehecha": True}
    filas = [t for t in map(tareas.parse, path.read_text(encoding="utf-8").splitlines()) if t]
    vistas, count, marcas, ajenas = set(), {}, 0, 0
    for t in filas:
        n = count[t["texto"]] = count.get(t["texto"], 0) + 1
        row = activas.get((t["texto"], n))
        if row is None or (t["texto"], n) in vistas or (row.area, row.due) != (t["area"], t["fecha"]):
            ajenas += 1
            continue
        vistas.add((t["texto"], n))
        if row.done != t["hecho"]:
            row.done = t["hecho"]
            row.done_on = (t["hecho_el"] or date.today().isoformat()) if t["hecho"] else None
            row.updated_at = utcnow()
            marcas += 1
    faltan = len(activas) - len(vistas)  # tareas de la base que no están (o están cambiadas) en la nota
    cambios = max(ajenas, faltan)
    db.flush()
    if cambios:
        mirror.export_tasks(db, path)
        mirror.warn(f"Tareas.md es una copia de la base de datos: he descartado {cambios} cambios hechos a mano en la nota (tareas nuevas, editadas o borradas). Cámbialas desde el panel o pídeselo a Jarvis.")
    elif marcas:
        mirror.export_tasks(db, path)  # normaliza la línea (✅ y orden)
    return {"origen": len(filas), "marcas": marcas, "descartados": cambios, "retiradas": 0}


def import_tasks(db: Session, path=None) -> dict:
    """Siembra la base desde Tareas.md. Solo la primera vez (ver `sync_tasks`) y en pruebas: desde entonces manda la base."""
    import tareas
    path = path or get_settings().vault / "Jarvis/Tareas.md"
    filas = [t for t in map(tareas.parse, path.read_text(encoding="utf-8").splitlines()) if t] if path.exists() else []
    seen, count = set(), {}
    existing = {t.external_id: t for t in db.scalars(select(Task))}
    activas = sum(1 for t in existing.values() if t.removed_at is None)
    if _sospechosa(activas, len(filas)):
        mirror.export_tasks(db, path)
        mirror.warn(f"Tareas.md había perdido tareas ({len(filas)} de {activas}). La he rehecho desde la base de datos.")
        return {"origen": activas, "retiradas": 0, "rehecha": True}
    if not path.exists():
        return {"origen": 0, "retiradas": 0}
    for t in filas:
        n = count[t["texto"]] = count.get(t["texto"], 0) + 1  # dos tareas iguales son dos tareas
        ext = sha("tarea", t["texto"], n)
        seen.add(ext)
        row = existing.get(ext)
        if row is None:
            row = Task(external_id=ext, text=t["texto"])
            db.add(row)
        row.area, row.due, row.done, row.done_on, row.removed_at, row.updated_at = t["area"], t["fecha"], t["hecho"], t["hecho_el"], None, utcnow()
    return {"origen": len(filas), "retiradas": _mark_removed(db, Task, seen)}


MARCA_GYM = "fuente-gym-bd"  # existe desde que la base manda en los entrenos


def _importar_entrenos(db: Session, path, guard: bool = True) -> dict:
    """Lleva a la base las sesiones de un texto con el formato de `## Registro` (la nota, o el registro nuevo que
    prepara un escritor). Idempotente por huella; lo que no está se retira."""
    import gym_stats
    sesiones = gym_stats.cargar(path)
    existing = {w.external_id: w for w in db.scalars(select(Workout))}
    activos = sum(1 for w in existing.values() if w.removed_at is None and w.source_text)
    if guard and _sospechosa(activos, len(sesiones)):
        mirror.export_workouts(db)
        mirror.warn(f"Gym.md había perdido entrenos ({len(sesiones)} de {activos}). He rehecho el registro desde la base de datos.")
        return {"origen": activos, "series": 0, "retiradas": 0, "rehecha": True}
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen, series = set(), 0
    for s in sesiones:
        seen.add(s.id)
        fin = next((i for i in range(s.linea, len(lines)) if lines[i].startswith("#")), len(lines))
        crudo = "\n".join(lines[s.linea - 1:fin]).strip()
        data = [(e.nombre, e.id, e.notas, [(x.peso, x.reps, x.calentamiento, x.fallo, x.drop, x.rpe) for x in e.series]) for e in s.ejercicios]
        h = sha(s.fecha, s.nombre, s.hevy, data)
        series += sum(len(d[3]) for d in data)
        w = existing.get(s.id)
        if w is not None and w.content_hash == h:
            w.removed_at, w.source_text = None, crudo
            continue
        if w is None:
            w = Workout(external_id=s.id, day=s.fecha, name=s.nombre, hevy_title=s.hevy or "", content_hash=h, source_text=crudo)
            db.add(w)
            db.flush()
        else:
            for old in db.scalars(select(WorkoutExercise).where(WorkoutExercise.workout_id == w.id)):
                db.delete(old)
            db.flush()
            w.day, w.name, w.hevy_title, w.content_hash, w.removed_at, w.source_text = s.fecha, s.nombre, s.hevy or "", h, None, crudo
        for i, (nombre, key, notas, sets) in enumerate(data):
            ex = WorkoutExercise(workout_id=w.id, position=i, name=nombre[:200], exercise_key=key[:120], notes=notas or "")
            db.add(ex)
            db.flush()
            for j, (peso, reps, warm, fallo, drop, rpe) in enumerate(sets):
                db.add(WorkoutSet(exercise_id=ex.id, position=j, weight=peso, reps=reps, warmup=warm, failure=fallo, drop_set=drop, rpe=rpe))
    db.flush()
    return {"origen": len(sesiones), "series": series, "retiradas": _mark_removed(db, Workout, seen)}


def _sembrar_gym(db: Session) -> dict | None:
    """La primera vez tras el corte: la base se siembra desde la nota y el registro se normaliza. None si ya estaba.

    La marca se escribe solo cuando la transacción se confirma: si se deshiciera, la siguiente pasada vuelve a sembrar
    en vez de dar por buena una base vacía. Si otra sesión siembra a la vez, gana la que confirme primero."""
    from sqlalchemy import event
    from sqlalchemy.exc import IntegrityError
    marca = get_settings().data_dir / MARCA_GYM
    if marca.exists():
        return None
    try:
        with db.begin_nested():
            r = _importar_entrenos(db, get_settings().vault / "Jarvis/Areas/Gym.md")
    except IntegrityError:
        return None  # otra sesión la está sembrando con lo mismo
    if not r.get("rehecha"):
        mirror.export_workouts(db)

    def marcar(_s):
        marca.parent.mkdir(parents=True, exist_ok=True)
        marca.write_text(utcnow().isoformat())
    event.listen(db, "after_commit", marcar, once=True)
    return r | {"sembrada": True}


def write_workouts(db: Session, registro: str) -> dict:
    """Escritores del gym (panel, Jarvis, Hevy): el registro completo nuevo va a la base y la nota se rehace."""
    import tempfile
    from pathlib import Path
    _sembrar_gym(db)
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "Gym.md"
        f.write_text("## Registro\n\n" + registro.strip() + "\n", encoding="utf-8")
        r = _importar_entrenos(db, f, guard=False)
    mirror.export_workouts(db)
    return r


def sync_workouts(db: Session) -> dict:
    """Entrenos: manda la base y el `## Registro` de Gym.md es una copia (Rutina y Perfil siguen siendo editables).

    Si el registro de la nota no coincide con la base (editado a mano, por Syncthing o por un script antiguo), se
    guarda la nota en `descartes/gym`, se rehace y se avisa. La primera vez siembra la base desde la nota."""
    if (r := _sembrar_gym(db)) is not None:
        return r
    path = get_settings().vault / "Jarvis/Areas/Gym.md"
    if not path.exists():
        if not mirror.workouts_text(db):
            return {"descartados": 0}
        mirror.export_workouts(db)
        mirror.warn("Gym.md había desaparecido. La he rehecho desde la base de datos.")
        return {"rehecha": True, "descartados": 0}
    texto = path.read_text(encoding="utf-8")
    actual = mirror.registro_partes(texto)[1]
    if actual and not mirror.workouts_text(db):  # base sin entrenos y nota con ellos: nunca se descarta la nota
        mirror.warn("La base de datos no tenía entrenos y Gym.md sí: los he vuelto a importar desde la nota.")
        return _importar_entrenos(db, path) | {"descartados": 0}
    if actual is not None and actual == mirror.workouts_text(db).strip():
        if mirror.AVISO_GYM not in texto:
            mirror.export_workouts(db)
        return {"descartados": 0}
    d = get_settings().data_dir / "descartes" / "gym"
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    (d / f"{utcnow():%Y%m%d-%H%M%S}-Gym.md").write_text(texto, encoding="utf-8")
    mirror.export_workouts(db)
    mirror.warn("El registro de Gym.md es una copia de la base de datos: he descartado lo que cambiaste a mano (guardado en "
                f"data/control-center/descartes/gym). Registra o corrige entrenos desde Entrenamiento en el panel o pídeselo a {asistente()}.")
    return {"descartados": 1}


def sync_grades(db: Session) -> dict:
    path = get_settings().vault / "Jarvis/Areas/Notas-Uni.md"
    if not path.exists():
        return {"origen": 0}
    text = path.read_text(encoding="utf-8")
    subjects = {s.code: s for s in db.scalars(select(Subject))}
    resumen = text.split("## Resumen", 1)[1].split("\n## ", 1)[0] if "## Resumen" in text else ""
    for r in _table(resumen):
        code = r.get("Asignatura", "")[:32]
        s = subjects.get(code) or Subject(code=code)
        s.formula, s.minimums, s.current_grade, s.status = r.get("Fórmula", "")[:300], r.get("Mínimos", "")[:300], r.get("Nota actual", "")[:32], r.get("Estado", "")[:300]
        db.add(s)
        subjects[code] = s
    existing = {g.external_id: g for g in db.scalars(select(GradeItem))}
    seen: set[str] = set()
    actual, bloque = "", []

    def flush() -> None:
        for r in _table("\n".join(bloque)):
            titulo = r.get("Entregable", "")
            if not actual or not titulo:
                continue
            ext = sha("nota", actual, titulo)
            seen.add(ext)
            g = existing.get(ext) or GradeItem(external_id=ext, subject=actual[:32], title=titulo[:300])
            g.weight, g.due, g.grade, g.removed_at = r.get("Peso", "")[:120], r.get("Entrega", "")[:40], r.get("Nota", "")[:32], None
            db.add(g)
            existing[ext] = g

    for line in text.splitlines():
        m = SECCION.match(line)
        if m or line.startswith("## "):
            flush()
            actual, bloque = (m[1].strip() if m else ""), []
        else:
            bloque.append(line)
    flush()
    return {"asignaturas": len(subjects), "origen": len(seen), "retiradas": _retirar(db, GradeItem, seen, "Notas-Uni.md")}


def sync_uni(db: Session) -> dict:
    import uni
    data = uni.recoger(DESDE, HORIZONTE)
    existing = {a.external_id: a for a in db.scalars(select(Assessment))}
    seen, count = set(), {}
    for e in data.get("entregas", []):
        n = count[(e["fecha"], e["texto"])] = count.get((e["fecha"], e["texto"]), 0) + 1
        ext = sha("entrega", e["fecha"], e["texto"], n)
        seen.add(ext)
        a = existing.get(ext) or Assessment(external_id=ext, due=e["fecha"], title=e["texto"])
        a.due_time, a.done, a.removed_at = e.get("hora", "")[:5], bool(e.get("hecho")), None
        db.add(a)
    bloques = {(b.day, b.slot): b for b in db.scalars(select(StudyBlock))}
    total = 0
    for ini, _fin, txt in uni._semanas():
        for line in uni._seccion(txt, "Plan diario"):
            m = uni.FILA_DIA.match(line)
            if not m:
                continue
            dia = date(ini.year, int(m[2]), int(m[1])).isoformat()
            for slot, celda in enumerate(c.strip(" |") for c in line.replace("\\|", "|").split(" | ")[1:]):
                texto = uni.plain(celda)
                if texto in ("", "—", "Libre"):
                    continue
                b = bloques.get((dia, slot)) or StudyBlock(day=dia, slot=slot, text=texto)
                b.text = texto
                db.add(b)
                bloques[(dia, slot)] = b
                total += 1
    return {"entregas": len(seen), "retiradas": _retirar(db, Assessment, seen, "Notas semanales de la uni"), "bloques": total}


def sync_jobs(db: Session) -> dict:
    jarvis = get_settings().vault / "Jarvis"
    leads = 0
    f = jarvis / "Sistema/ofertas-vistas.json"
    if f.exists():
        vistas = json.loads(f.read_text(encoding="utf-8"))
        existing = set(db.scalars(select(JobLead.external_id)))
        for k, o in vistas.items():
            leads += 1
            if k in existing:
                continue
            db.add(JobLead(external_id=str(k)[:64], title=str(o.get("titulo", ""))[:300], company=str(o.get("empresa", ""))[:200], place=str(o.get("lugar", ""))[:200],
                           link=str(o.get("enlace", ""))[:500], score=int(o.get("puntos") or 0), seen_on=str(o.get("visto", ""))[:10]))
    apps = 0
    t = jarvis / "Areas/Trabajo.md"
    marca = get_settings().data_dir / MARCA_EMPLEO
    if t.exists() and "## Pipeline de candidaturas" in t.read_text(encoding="utf-8"):
        texto = t.read_text(encoding="utf-8")
        if not marca.exists():  # primera vez: lo escrito justo antes del cambio entra en la base
            tabla = texto.split("## Pipeline de candidaturas", 1)[1].split("\n## ", 1)[0]
            for r in _table(tabla):
                empresa, puesto = r.get("Empresa", "")[:160], r.get("Puesto", "")[:200]
                if empresa and not db.scalar(select(JobApplication.id).where(JobApplication.company == empresa, JobApplication.role == puesto)):
                    db.add(JobApplication(company=empresa, role=puesto, status=r.get("Estado") or "interés", next_step=r.get("Próximo paso", "")[:300]))
                    apps += 1
            db.flush()
            marca.parent.mkdir(parents=True, exist_ok=True)
            marca.write_text(utcnow().isoformat())
        elif mirror.pipeline_in_note(texto) != mirror.pipeline_rows(db):
            # La base manda: la tabla es una copia. Lo cambiado a mano se descarta y se avisa
            mirror.export_jobs(db)
            mirror.warn(f"La tabla del pipeline de Trabajo.md es una copia de la base de datos: he descartado lo que cambiaste a mano. Las candidaturas se cambian desde Carrera en el panel o pidiéndoselo a {asistente()}.")
    return {"ofertas": leads, "candidaturas_nuevas": apps}


MARCA_DIARIO = "fuente-diario-bd"  # existe desde que la base manda en el diario


def _dia_de(nombre: str) -> tuple[str, str] | None:
    m = re.search(r"\d{4}-\d{2}-\d{2}", nombre)
    return (m[0], "semana" if nombre.startswith("Semana") else "dia") if m else None


def _import_journal(db: Session, folder, root) -> int:
    n = 0
    for f in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        if "sync-conflict" in f.name or not (d := _dia_de(f.name)):
            continue
        text = mirror.journal_canon(f.read_text(encoding="utf-8", errors="replace"))
        rel, h = f.relative_to(root).as_posix(), sha(text)
        row = db.get(JournalDay, rel)
        if row is None:
            db.add(JournalDay(path=rel, day=d[0], kind=d[1], content=text, content_hash=h))
        elif row.content_hash != h:
            row.content, row.content_hash = text, h
        n += 1
    return n


def _descartar(f, root) -> None:
    """Guarda lo que se descarta, por si acaso: nunca se pierde un texto escrito a mano."""
    d = get_settings().data_dir / "descartes" / "diario"
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    (d / f"{utcnow():%Y%m%d-%H%M%S}-{f.name}").write_bytes(f.read_bytes())


def sync_journal(db: Session) -> dict:
    """Diario: manda la base (lo escribe la rutina con `journal.write`) y `Diario/*.md` son copias.

    La primera vez siembra la base desde las notas. Desde entonces, una nota editada, borrada o creada a mano se
    rehace desde la base (o se quita, si la base no la tiene); lo descartado se guarda en `data/.../descartes/diario`
    y se avisa una vez por pasada."""
    root = get_settings().vault
    folder = root / mirror.DIARIO
    marca = get_settings().data_dir / MARCA_DIARIO
    if not marca.exists():
        n = _import_journal(db, folder, root)
        db.flush()
        mirror.export_journal(db)  # pone el aviso de copia
        marca.parent.mkdir(parents=True, exist_ok=True)
        marca.write_text(utcnow().isoformat())
        return {"origen": n, "sembrada": True}
    filas = {r.path: r for r in db.scalars(select(JournalDay))}
    cambiadas, ajenas, rehechas = 0, 0, 0
    for f in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        if "sync-conflict" in f.name or not _dia_de(f.name):  # lo que no es un día ni una semana no es del diario
            continue
        rel = f.relative_to(root).as_posix()
        row = filas.get(rel)
        if row is None:
            _descartar(f, root)
            f.unlink()
            ajenas += 1
            continue
        actual = f.read_text(encoding="utf-8", errors="replace")
        if mirror.strip_journal_notice(actual) != row.content:
            _descartar(f, root)
            cambiadas += 1
    for row in filas.values():
        rehechas += mirror.export_journal(db, row)
    if cambiadas or ajenas:
        mirror.warn(f"El diario es una copia de la base de datos: he descartado {cambiadas + ajenas} cambios hechos a mano en Diario/ "
                    f"(guardados en data/control-center/descartes/diario). Para corregir un día, díselo a {asistente()} o ciérralo desde el check-in de la noche.")
    return {"origen": len(filas), "descartados": cambiadas + ajenas, "rehechas": rehechas}


def sync_decisions(db: Session) -> dict:
    path = get_settings().root / "CLAUDE.md"
    if not path.exists():
        return {"origen": 0}
    n, actual, body = 0, None, []

    def flush() -> int:
        if actual is None:
            return 0
        titulo = actual[1][:200]
        if not db.scalar(select(DecisionRecord.id).where(DecisionRecord.decided_on == actual[0], DecisionRecord.title == titulo)):
            db.add(DecisionRecord(decided_on=actual[0], title=titulo, domain="jarvis", choice="\n".join(body).strip()))
            db.flush()
        return 1

    for line in path.read_text(encoding="utf-8").splitlines():
        m = DECISION.match(line)
        if m or line.startswith("## "):
            n += flush()
            actual, body = ((m[1], m[2]) if m else None), []
        elif actual:
            body.append(line)
    n += flush()
    return {"origen": n}


def sync_records(db: Session) -> dict:
    jarvis = get_settings().vault / "Jarvis"
    fuentes: list[tuple[str, str, dict]] = []
    cobros = jarvis / "Contabilidad/Cobros.md"  # tabla de cobros (freelance), si la usas
    if cobros.exists():
        for r in _table(cobros.read_text(encoding="utf-8")):
            fuentes.append(("cobro", sha(json.dumps(r, sort_keys=True, ensure_ascii=False)), r))
    existing = {(r.kind, r.external_id): r for r in db.scalars(select(VaultRecord).where(VaultRecord.kind == "cobro"))}
    seen = set()
    for kind, ext, data in fuentes:
        seen.add((kind, ext))
        r = existing.get((kind, ext))
        if r is None:
            db.add(VaultRecord(kind=kind, external_id=ext, data=data))
        else:
            r.data, r.removed_at = data, None
    for key, r in existing.items():
        if key not in seen and r.removed_at is None:
            r.removed_at = utcnow()
    return {"origen": len(fuentes)}


MARCA_UNI = "fuente-uni-bd"  # existe desde que la base manda en lo marcado (hechos.json)


def _marcar_tras_commit(db: Session, nombre: str) -> None:
    from sqlalchemy import event
    marca = get_settings().data_dir / nombre

    def escribir(_s):
        marca.parent.mkdir(parents=True, exist_ok=True)
        marca.write_text(utcnow().isoformat())
    event.listen(db, "after_commit", escribir, once=True)


def set_hecho(db: Session, clave: str, hecho: bool, fecha: str | None = None) -> None:
    """Marcar o desmarcar en la base, y rehacer `hechos.json` (la copia que leen planificador y resumen semanal)."""
    ext = sha(clave)
    r = db.scalar(select(VaultRecord).where(VaultRecord.kind == "hecho", VaultRecord.external_id == ext))
    if hecho:
        if r is None:
            db.add(VaultRecord(kind="hecho", external_id=ext, data={"clave": clave, "fecha": fecha or date.today().isoformat()}))
        elif r.removed_at is not None:
            r.removed_at, r.data = None, {"clave": clave, "fecha": fecha or date.today().isoformat()}
    elif r is not None and r.removed_at is None:
        r.removed_at = utcnow()
    db.flush()
    mirror.export_hechos(db)


def sync_hechos(db: Session) -> dict:
    """Lo marcado de la uni (y del Panel): manda la base y `Sistema/hechos.json` es una copia.

    `build.py` vuelca cada mañana en la copia las casillas del Panel, así que de ella se aceptan marcas nuevas y
    desmarcadas, igual que las casillas de Tareas.md. Lo que no se acepta es perderla: si desaparece, no se puede
    leer o pierde de golpe más de la mitad, se rehace desde la base y se avisa. La primera vez siembra la base."""
    f = mirror.hechos_path()
    filas = {r.external_id: r for r in db.scalars(select(VaultRecord).where(VaultRecord.kind == "hecho"))}
    activas = {e: r for e, r in filas.items() if r.removed_at is None}
    try:
        archivo = json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
        if archivo is not None and not isinstance(archivo, dict):
            raise ValueError("no es un objeto")
    except ValueError:
        d = get_settings().data_dir / "descartes" / "uni"
        d.mkdir(mode=0o700, parents=True, exist_ok=True)
        (d / f"{utcnow():%Y%m%d-%H%M%S}-hechos.json").write_bytes(f.read_bytes())
        archivo = None
    primera = not (get_settings().data_dir / MARCA_UNI).exists()
    if archivo is None:
        if activas:
            mirror.export_hechos(db)
            mirror.warn("Sistema/hechos.json (lo marcado de la uni y del Panel) había desaparecido o estaba roto. Lo he rehecho desde la base de datos.")
        return {"origen": 0, "rehecha": bool(activas)}
    claves = {sha(k): (k, v) for k, v in archivo.items()}
    if not primera and _sospechosa(len(activas), len(set(claves) & set(activas))):
        for e, (k, v) in claves.items():  # lo nuevo de la copia sí entra; lo perdido no se da por desmarcado
            if e not in activas:
                set_hecho(db, k, True, str(v))
        mirror.export_hechos(db)
        mirror.warn(f"Sistema/hechos.json había perdido marcas ({len(set(claves) & set(activas))} de {len(activas)}). La he rehecho desde la base de datos.")
        return {"origen": len(archivo), "rehecha": True}
    nuevas = quitadas = 0
    for e, (k, v) in claves.items():
        r = filas.get(e)
        if r is None:
            db.add(VaultRecord(kind="hecho", external_id=e, data={"clave": k, "fecha": str(v)}))
            nuevas += 1
        elif r.removed_at is not None or r.data.get("fecha") != v:
            r.removed_at, r.data = None, {"clave": k, "fecha": str(v)}
            nuevas += 1
    for e, r in activas.items():
        if e not in claves:
            r.removed_at = utcnow()
            quitadas += 1
    db.flush()
    if primera:
        _marcar_tras_commit(db, MARCA_UNI)
    return {"origen": len(archivo), "nuevas": nuevas, "quitadas": quitadas}


SECTIONS = (("tareas", sync_tasks), ("entrenos", sync_workouts), ("notas", sync_grades), ("uni", sync_uni), ("empleo", sync_jobs),
            ("diario", sync_journal), ("decisiones", sync_decisions), ("hechos", sync_hechos), ("registros", sync_records))


def run_all() -> dict:
    report: dict = {}
    for name, fn in SECTIONS:
        try:
            with session_scope() as db:
                report[name] = fn(db)
        except Exception as e:  # noqa: BLE001  una sección rota no debe parar las demás
            report[name] = {"error": f"{type(e).__name__}: {e}"[:300]}
    return report
