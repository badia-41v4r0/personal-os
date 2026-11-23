"""Lo que un agente puede pedir y leer fuera de finanzas. Registrar esto no da acceso: cada ejecución solo abre su lista.

Los scripts de collectors/ se llaman sin shell, y sus límites en código (sin invitados, solo borradores, solo eventos
propios) siguen siendo el tope final. Tareas y entrenos se escriben en su nota y entran en la base en la misma transacción.

Niveles: 1 lo que el usuario podría deshacer de un vistazo; 2 lo visible fuera de la vault, con reglas; 3 lo que afecta a
terceros o gasta. Enviar correo no existe como capacidad.
"""
import json
import logging
import re
import shutil
import subprocess
import sys
import uuid
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import agenda as agenda_mod
from ..config import ROOT, get_settings
from ..core import actions, gateway, memory
from . import mirror
from ..models import Assessment, Goal, Habit, HealthLog, JobApplication, JournalDay, LifestyleItem, Milestone, Task
from ..db import utcnow

log = logging.getLogger("cc.caps")
CLI_TIMEOUT = 60
sys.path.insert(0, str(ROOT / "collectors"))
import ajustes  # noqa: E402


def cli(script: str, *args: str) -> str:
    """Sin shell, y con `--opcion=valor`: un valor que empiece por guion no puede hacerse pasar por opción."""
    r = subprocess.run([sys.executable, str(ROOT / "collectors" / script), *args], capture_output=True, text=True, timeout=CLI_TIMEOUT, cwd=ROOT)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip()[-300:] or f"{script} falló")
    return r.stdout.strip()


def _tasks_file():
    return get_settings().vault / "Jarvis/Tareas.md"


def _safe_line(text: str) -> str:
    return " ".join(str(text).split())[:300]


def _write(path, text: str) -> None:
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(text, encoding="utf-8")
    shutil.copymode(path, tmp)  # el backend crea con 600: el .md debe seguir como estaba
    tmp.replace(path)


def _pending_task(db: Session, texto: str, hecha: bool = False) -> Task | None:
    return db.scalar(select(Task).where(Task.text == texto, Task.done.is_(hecha), Task.removed_at.is_(None))
                     .order_by(Task.due.is_(None), Task.due, Task.id).limit(1))


def _export_tasks(db: Session) -> None:
    mirror.export_tasks(db, _tasks_file())


def task_create(p: dict, db: Session) -> dict:
    """La base manda: la tarea nace aquí y Tareas.md se rehace como copia."""
    texto = _safe_line(p["texto"])
    if not texto:
        raise ValueError("Tarea vacía")
    area = p.get("area") if p.get("area") in ajustes.areas() else "personal"
    due = date.fromisoformat(p["fecha"]).isoformat() if p.get("fecha") else None
    dup = db.scalar(select(Task).where(Task.text == texto, Task.area == area, Task.due == due if due else Task.due.is_(None),
                                       Task.done.is_(False), Task.removed_at.is_(None)).limit(1))
    if dup:
        return {"id": dup.id, "linea": mirror.task_line(dup), "repetida": True}
    t = Task(external_id=f"db:{uuid.uuid4().hex}", text=texto, area=area, due=due, done=False)
    db.add(t)
    db.flush()
    _export_tasks(db)
    return {"id": t.id, "linea": mirror.task_line(t)}


def task_create_undo(r: dict, db: Session) -> dict:
    if r.get("repetida"):
        return {}
    t = db.get(Task, r["id"])
    if t is not None:
        db.delete(t)
        db.flush()
        _export_tasks(db)
    return {}


def task_done(p: dict, db: Session) -> dict:
    import tareas
    t = _pending_task(db, p["texto"])
    if t is None:
        raise RuntimeError("No encuentro esa tarea pendiente")
    t.done, t.done_on, t.updated_at = True, date.today().isoformat(), utcnow()
    db.flush()
    _export_tasks(db)
    tareas.casilla_tarea(t.text, True)  # su casilla del Panel de hoy, para que la regeneración no la deshaga
    return {"texto": p["texto"]}


def task_done_undo(r: dict, db: Session) -> dict:
    import tareas
    t = _pending_task(db, r["texto"], hecha=True)
    if t is not None:
        t.done, t.done_on, t.updated_at = False, None, utcnow()
        db.flush()
        _export_tasks(db)
        tareas.casilla_tarea(t.text, False)
    return {}


def note_add(p: dict, db: Session) -> dict:
    """Solo en la bandeja del día: una nota no puede pisar nada."""
    inbox = get_settings().vault / "Jarvis/00-Inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    f = inbox / f"{date.today().isoformat()}.md"
    with f.open("a", encoding="utf-8") as h:
        h.write(f"- {datetime.now():%H:%M} {' '.join(str(p['texto']).split())[:2000]}\n")
    return {"archivo": f"Jarvis/00-Inbox/{f.name}"}


def gym_register(p: dict, db: Session) -> dict:
    from .. import gym
    body = gym.RegistroIn(texto=p["texto"], fecha=p.get("fecha") or date.today().isoformat(), sesion=p.get("sesion"))

    class Actor:
        name = "agente"
    return gym.register(body, Actor, db)


def health_log(p: dict, db: Session) -> dict:
    r = HealthLog(day=p.get("dia") or date.today().isoformat(), metric=str(p["metrica"])[:32], value=float(p["valor"]), note=str(p.get("nota", ""))[:300])
    db.add(r)
    db.flush()
    return {"id": r.id}


def health_log_undo(r: dict, db: Session) -> dict:
    row = db.get(HealthLog, r["id"])
    if row:
        db.delete(row)
    return {}


def application_create(p: dict, db: Session) -> dict:
    a = JobApplication(company=str(p["empresa"])[:160], role=str(p["puesto"])[:200], link=str(p.get("enlace", ""))[:500], next_step=str(p.get("proximo_paso", ""))[:300])
    db.add(a)
    db.flush()
    memory.log_event(db, "career", "application.created", f"{a.company}: {a.role}")
    mirror.export_jobs(db)
    return {"id": a.id}


def _cal_args(p: dict) -> list[str]:
    if p.get("dia"):
        return [f"--dia={date.fromisoformat(p['dia']).isoformat()}"]
    return [f"--inicio={datetime.fromisoformat(p['inicio']).isoformat(timespec='minutes')}", f"--fin={datetime.fromisoformat(p['fin']).isoformat(timespec='minutes')}"]


def calendar_create(p: dict, db: Session) -> dict:
    args = [f"--titulo={_safe_line(p['titulo'])}", *_cal_args(p)]
    if p.get("lugar"):
        args.append(f"--lugar={_safe_line(p['lugar'])}")
    return json.loads(cli("gcal.py", "crear", *args))


def calendar_create_undo(r: dict, db: Session) -> dict:
    cli("gcal.py", "borrar", f"--id={r['id']}")
    return {}


def calendar_move(p: dict, db: Session) -> dict:
    return json.loads(cli("gcal.py", "mover", f"--id={p['id']}", *_cal_args(p)))


def calendar_delete(p: dict, db: Session) -> dict:
    return json.loads(cli("gcal.py", "borrar", f"--id={p['id']}"))


def mail_draft(p: dict, db: Session) -> dict:
    args = [f"--cuenta={p['cuenta']}", f"--para={p['para']}", f"--asunto={_safe_line(p['asunto'])}", f"--cuerpo={p['cuerpo']}"]
    if p.get("responder_a"):
        args.append(f"--responder-a={p['responder_a']}")
    return {"salida": cli("correo.py", "borrador", *args)[:500]}




def _rule_mine(p: dict, limits: dict) -> bool:
    return True  # gcal.py ya impide invitados y tocar eventos ajenos


def goal_create(p: dict, db: Session) -> dict:
    g = Goal(title=str(p["titulo"])[:200], area=str(p.get("area", "personal"))[:32], horizon=p.get("horizonte") if p.get("horizonte") in ("corto", "medio", "largo") else "medio",
             target_date=date.fromisoformat(p["fecha"]).isoformat() if p.get("fecha") else None, why=str(p.get("porque", "")))
    db.add(g)
    db.flush()
    memory.log_event(db, "goals", "goal.created", g.title)
    return {"id": g.id}


def goal_milestone(p: dict, db: Session) -> dict:
    if db.get(Goal, int(p["objetivo"])) is None:
        raise ValueError("Objetivo no encontrado")
    m = Milestone(goal_id=int(p["objetivo"]), title=str(p["titulo"])[:200])
    db.add(m)
    db.flush()
    return {"id": m.id}


def habit_create(p: dict, db: Session) -> dict:
    h = Habit(name=str(p["nombre"])[:120])
    db.add(h)
    db.flush()
    return {"id": h.id}


def lifestyle_add(p: dict, db: Session) -> dict:
    if p.get("tipo") not in ("viaje", "actividad", "compra", "garantia", "suscripcion", "interes"):
        raise ValueError("Tipo no válido")
    i = LifestyleItem(kind=p["tipo"], title=str(p["titulo"])[:200], day=date.fromisoformat(p["dia"]).isoformat() if p.get("dia") else None, note=str(p.get("nota", "")))
    db.add(i)
    db.flush()
    return {"id": i.id}


class _Agente:
    name = "agente"


def _gym_block(p: dict) -> tuple[str, str, str]:
    from .. import gym
    import gym_texto
    fecha = date.fromisoformat(p["fecha"]).isoformat()
    sesion, ejercicios, _ = gym._registro(gym.RegistroIn(texto=p["texto"], fecha=fecha, sesion=p.get("sesion")))
    if not ejercicios:
        raise ValueError("No he encontrado ningún ejercicio con series")
    return fecha, sesion, gym_texto.bloque(fecha, sesion, ejercicios)


def gym_replace(p: dict, db: Session) -> dict:
    from .. import gym
    fecha, sesion, bloque = _gym_block(p)
    return {"fecha": fecha, "sesion": sesion, "anterior": gym.replace_workout(fecha, sesion, bloque, "agente", db)}


def gym_replace_undo(r: dict, db: Session) -> dict:
    from .. import gym
    gym.replace_workout(r["fecha"], r["sesion"], r["anterior"], "agente", db)
    return {}


def gym_recovery(p: dict, db: Session) -> dict:
    from .. import gym_plan
    return gym_plan.post_recovery(gym_plan.RecoveryIn(**p), _Agente, db)


def gym_pause(p: dict, db: Session) -> dict:
    """Periodo sin entrenar (enfermedad, lesión, vacaciones): el gym no lo cuenta como abandono y propone una vuelta prudente."""
    from .. import gym_plan
    return gym_plan.crear_pausa(db, gym_plan.PauseIn(**p), "agente")


def gym_pause_undo(r: dict, db: Session) -> dict:
    from ..models import GymPause
    x = db.get(GymPause, r["id"])
    if x is not None:
        db.delete(x)
    return {}


def gym_plan_create(p: dict, db: Session) -> dict:
    from .. import gym_plan
    return gym_plan.create_plan(gym_plan.PlanIn(**p), _Agente, db)


def gym_plan_update(p: dict, db: Session) -> dict:
    from .. import gym_plan
    datos = dict(p)
    return gym_plan.patch_plan(str(datos.pop("id")), gym_plan.PlanPatch(**datos), _Agente, db)


def gym_settings(p: dict, db: Session) -> dict:
    from .. import gym_plan
    datos = dict(p)
    return gym_plan.put_settings(str(datos.pop("ejercicio")), gym_plan.SettingsIn(**datos), _Agente, db)


def task_reschedule(p: dict, db: Session) -> dict:
    nueva = date.fromisoformat(p["fecha"]).isoformat()
    t = _pending_task(db, p["texto"])
    if t is None:
        raise RuntimeError("No encuentro esa tarea pendiente")
    antes = t.due
    t.due, t.updated_at = nueva, utcnow()
    db.flush()
    _export_tasks(db)
    return {"texto": p["texto"], "antes": antes, "fecha": nueva}


def _task_in(area: str):
    def create(p: dict, db: Session) -> dict:
        return task_create({"texto": p["texto"], "fecha": p.get("fecha"), "area": area}, db)
    return create


def _uni_task_done(p: dict, db: Session) -> dict:
    t = db.scalar(select(Task).where(Task.text == p["texto"], Task.area == "uni", Task.done.is_(False), Task.removed_at.is_(None)))
    if t is None:
        raise RuntimeError("No encuentro esa tarea de la uni")
    return task_done(p, db)


def uni_card_add(p: dict, db: Session) -> dict:
    """Tarjetas de repaso que propone el tutor a partir de las notas de la uni. Se pueden deshacer y borrar desde el panel."""
    from . import education
    tarjetas = p.get("tarjetas")
    if not isinstance(tarjetas, list) or not 1 <= len(tarjetas) <= 30:
        raise ValueError("Pasa entre 1 y 30 tarjetas en `tarjetas`")
    ids = education.add_cards(db, [t for t in tarjetas if isinstance(t, dict)], "tutor")
    return {"ids": ids, "repetidas": len(tarjetas) - len(ids)}


def uni_card_add_undo(r: dict, db: Session) -> dict:
    from ..models import EduCard, EduReview
    for i in r.get("ids", []):
        db.query(EduReview).filter(EduReview.card_id == i).delete()
        c = db.get(EduCard, i)
        if c:
            db.delete(c)
    return {}


def uni_grade(p: dict, db: Session) -> dict:
    """Solo la columna Nota: el Resumen lo recalcula notas.py."""
    nota = float(str(p["nota"]).replace(",", "."))
    if not 0 <= nota <= 10:
        raise ValueError("La nota va de 0 a 10")
    path = get_settings().vault / "Jarvis/Areas/Notas-Uni.md"
    lines, seccion, cols = path.read_text(encoding="utf-8").splitlines(), "", None
    for i, line in enumerate(lines):
        if line.startswith("## "):
            seccion, cols = line[3:].split("·")[0].strip(), None
        elif seccion == p["asignatura"] and line.lstrip().startswith("|"):
            celdas = line.strip().strip("|").split("|")
            nombres = [c.strip().strip("*").strip() for c in celdas]
            if cols is None:
                cols = nombres
            elif "Nota" in cols and "Entregable" in cols and nombres[cols.index("Entregable")] == p["entregable"]:
                anterior = nombres[cols.index("Nota")]
                celdas[cols.index("Nota")] = f" {nota:g} "
                lines[i] = "|" + "|".join(celdas) + "|"
                _write(path, "\n".join(lines) + "\n")
                cli("notas.py")
                return {"asignatura": p["asignatura"], "entregable": p["entregable"], "anterior": anterior, "nota": nota}
    raise RuntimeError("No encuentro ese entregable")


def uni_check(p: dict, db: Session) -> dict:
    from . import personal
    return personal.uni_check(str(p["clave"]), bool(p.get("hecho", True)), "agente", db)


def uni_check_undo(r: dict, db: Session) -> dict:
    from . import personal
    personal.uni_check(r["clave"], not r["hecho"], "agente", db)
    return {}


def application_update(p: dict, db: Session) -> dict:
    from . import personal
    return personal.patch_application(int(p["id"]), personal.ApplicationPatch(estado=p.get("estado"), proximo_paso=p.get("proximo_paso"), follow_up=p.get("follow_up")), _Agente, db)


def milestone_toggle(p: dict, db: Session) -> dict:
    from . import personal
    return personal.toggle_milestone(int(p["id"]), _Agente, db)


def goal_set_status(p: dict, db: Session) -> dict:
    from . import personal
    return personal.goal_status(int(p["id"]), personal.StatusIn(estado=p["estado"]), _Agente, db)


def habit_toggle(p: dict, db: Session) -> dict:
    from . import personal
    return personal.toggle_habit(int(p["id"]), personal.DayIn(dia=p.get("dia")), _Agente, db)


def lifestyle_remove(p: dict, db: Session) -> dict:
    row = db.get(LifestyleItem, int(p["id"]))
    if row is None:
        raise ValueError("No existe")
    datos = {"tipo": row.kind, "titulo": row.title, "dia": row.day, "nota": row.note}
    db.delete(row)
    return datos


def ocio_add(p: dict, db: Session) -> dict:
    """Con TMDB, busca el título y copia su ficha y carátula; sin TMDB o sin resultado, lo guarda a mano."""
    from . import ocio
    tipo = p.get("tipo") or None
    if tipo not in (None, "pelicula", "serie"):
        raise ValueError("Tipo no válido: pelicula o serie")
    titulo = _safe_line(p.get("titulo", ""))
    tmdb_id = int(p["tmdb_id"]) if p.get("tmdb_id") else None
    if tmdb_id and not tipo:
        raise ValueError("Con tmdb_id hay que decir el tipo")
    if tmdb_id is None and ocio.configured():
        m = ocio.best_match(titulo, tipo, int(p["anio"]) if p.get("anio") else None)
        if m:
            tmdb_id, tipo = m["tmdb_id"], m["tipo"]
    if not tipo:
        raise ValueError("No la encuentro en TMDB: di si es pelicula o serie para guardarla a mano")
    i = ocio.create(db, tipo=tipo, tmdb_id=tmdb_id, titulo=titulo, estado=p.get("estado") or "pendiente",
                    valoracion=int(p["valoracion"]) if p.get("valoracion") else None, nota=str(p.get("nota") or "")[:4000], actor="agente")
    return {"id": i.id, "titulo": i.title, "anio": i.year, "tipo": i.kind, "estado": i.status, "tmdb": i.tmdb_id is not None}


def ocio_add_undo(r: dict, db: Session) -> dict:
    from ..models import MediaItem
    x = db.get(MediaItem, r["id"])
    if x is not None:
        db.delete(x)
    return {}


def _ocio_item(p: dict, db: Session):
    from ..models import MediaItem
    if p.get("id"):
        i = db.get(MediaItem, int(p["id"]))
    else:
        t = _safe_line(p.get("titulo", "")).lower()
        hits = [x for x in db.scalars(select(MediaItem)) if t and t in (x.title.lower(), x.original_title.lower())]
        i = hits[0] if len(hits) == 1 else None
    if i is None:
        raise ValueError("No la encuentro en Ocio: usa el id de ocio.list")
    return i


def ocio_update(p: dict, db: Session) -> dict:
    from . import ocio
    i = _ocio_item(p, db)
    cambios = {k: p[k] for k in ocio.EDITABLE if k in p}
    if not cambios:
        raise ValueError("Nada que cambiar")
    return {"id": i.id, "titulo": i.title, "antes": ocio.update(db, i, cambios, "agente")}


def ocio_update_undo(r: dict, db: Session) -> dict:
    from . import ocio
    from ..models import MediaItem
    i = db.get(MediaItem, r["id"])
    if i is not None:
        for k, v in r["antes"].items():
            setattr(i, ocio.EDITABLE[k], v)
    return {}


# ---------- lo que antes hacía la sesión de tmux escribiendo en la vault ----------
_SLUG = re.compile(r"[^a-z0-9]+")
VIDEO_URL = re.compile(r"^https://([\w-]+\.)?(instagram\.com|tiktok\.com|youtube\.com|youtu\.be)/\S+$")


def _cola(carpeta: str, slug: str, frontmatter: dict, cuerpo: str = "") -> dict:
    """Un archivo en la cola que ya vigila cada servicio. Nunca pisa otro."""
    d = get_settings().vault / "Jarvis" / carpeta
    d.mkdir(parents=True, exist_ok=True)
    nombre = f"{datetime.now():%Y%m%d-%H%M%S}-{_SLUG.sub('-', slug.lower()).strip('-')[:40] or 'x'}.md"
    cabecera = "\n".join(f"{k}: {_safe_line(v)}" for k, v in frontmatter.items())
    f = d / nombre
    with f.open("x", encoding="utf-8") as h:
        h.write(f"---\n{cabecera}\n---\n{cuerpo.strip()}\n")
    f.chmod(0o644)
    return {"archivo": f"Jarvis/{carpeta}/{nombre}"}


def encargo_create(p: dict, db: Session) -> dict:
    if p.get("tipo") not in ("codigo", "issue", "plan"):
        raise ValueError("Tipo no válido")
    if not re.fullmatch(r"[\w.-]+", str(p.get("repo", ""))) or not (ROOT / "repos" / p["repo"]).is_dir():
        raise ValueError("No conozco esa repo")
    return _cola("Encargos/cola", p["titulo"], {"repo": p["repo"], "tipo": p["tipo"], "titulo": p["titulo"], "creado": f"{datetime.now():%Y-%m-%dT%H:%M}"}, str(p["detalle"]))


def ayudante_create(p: dict, db: Session) -> dict:
    modelo = p.get("modelo") if p.get("modelo") in ("sonnet", "opus") else "sonnet"
    return _cola("Ayudante/cola", p["titulo"], {"titulo": p["titulo"], "modelo": modelo, "minutos": max(5, min(int(p.get("minutos") or 30), 90))}, str(p["detalle"]))


def repo_create(p: dict, db: Session) -> dict:
    if not re.fullmatch(r"[\w.-]{1,80}", str(p.get("nombre", ""))) or p.get("area") not in ajustes.areas():
        raise ValueError("Nombre o área no válidos")
    return _cola("Repos/cola", p["nombre"], {"nombre": p["nombre"], "descripcion": p.get("descripcion", ""), "area": p["area"]}, str(p.get("detalle", "")))


def video_analyze(p: dict, db: Session) -> dict:
    if not VIDEO_URL.fullmatch(str(p.get("url", ""))):
        raise ValueError("Solo Instagram, TikTok o YouTube")
    return _cola("Videos/cola", "video", {"url": p["url"], "pregunta": p.get("pregunta") or "resumen"})


def day_close(p: dict, db: Session) -> dict:
    """El cierre escribe en varias notas: lo hace la rutina, que sí puede. Aquí solo se encarga."""
    from ..core import runs
    runs.order_routine("cierre", f"Haz el cierre manual del día según /vault/Jarvis/Sistema/cierre.md. Lo que cuenta el usuario:\n\n{str(p['resumen'])[:6000]}")
    return {"encargado": True}


FECHA = re.compile(r"\d{4}-\d{2}-\d{2}")
MAX_DIARIO = 60_000


def journal_write(p: dict, db: Session) -> dict:
    """El diario manda en la base: crea el día (o la semana), añade una actualización o lo reemplaza, y rehace su copia."""
    import hashlib
    dia, tipo, modo = str(p.get("fecha", "")), p.get("tipo") or "dia", p.get("modo") or "crear"
    texto = str(p.get("contenido") or "")
    if not FECHA.fullmatch(dia) or tipo not in ("dia", "semana") or modo not in ("crear", "anadir", "reemplazar"):
        raise ValueError("fecha AAAA-MM-DD, tipo dia|semana y modo crear|anadir|reemplazar")
    date.fromisoformat(dia)
    if not texto.strip() or len(texto) > MAX_DIARIO:
        raise ValueError("Contenido vacío o demasiado largo")
    path = mirror.journal_path(dia, tipo)
    row = db.get(JournalDay, path)
    anterior = row.content if row else None
    if row is not None and modo == "crear":
        raise ValueError("Ese día ya tiene diario: usa modo «anadir» (con una sección ## Actualización) o «reemplazar»")
    nuevo = texto if row is None or modo == "reemplazar" else row.content.rstrip() + "\n\n" + texto.strip() + "\n"
    nuevo = mirror.journal_canon(nuevo)
    h = hashlib.sha256(nuevo.encode()).hexdigest()
    if row is None:
        row = JournalDay(path=path, day=dia, kind=tipo, content=nuevo, content_hash=h)
        db.add(row)
    else:
        row.content, row.content_hash = nuevo, h
    db.flush()
    mirror.export_journal(db, row)
    return {"path": path, "anterior": anterior}


def journal_write_undo(r: dict, db: Session) -> dict:
    import hashlib
    row = db.get(JournalDay, r["path"])
    if row is None:
        return {}
    if r.get("anterior") is None:
        db.delete(row)
        db.flush()
        f = get_settings().vault / r["path"]
        if f.exists():
            f.unlink()
    else:
        row.content, row.content_hash = r["anterior"], hashlib.sha256(r["anterior"].encode()).hexdigest()
        db.flush()
        mirror.export_journal(db, row)
    return {}


def _synced(fn, *secciones: str):
    """La base manda: queda al día en el acto, sin esperar a la sincronización de cada 10 minutos."""
    def run(p: dict, db: Session) -> dict:
        r = fn(p, db)
        from . import vault_sync
        for nombre in secciones:
            try:
                with db.begin_nested():
                    getattr(vault_sync, nombre)(db)
            except Exception as e:  # noqa: BLE001  el cambio ya está hecho: la sincronización periódica lo recogerá
                log.warning("%s tras la acción: %s", nombre, e)
        return r
    return run


for cap in (
    actions.Capability("gym.workout.replace", 1, _synced(gym_replace, "sync_workouts"), "Corregir un entreno registrado", inverse=gym_replace_undo, summary=lambda p: f"Corregir entreno del {p.get('fecha')}"),
    actions.Capability("gym.pause.log", 1, gym_pause, "Apuntar un periodo sin entrenar (enfermedad, lesión, vacaciones)", inverse=gym_pause_undo,
                       summary=lambda p: f"Sin entrenar desde el {p.get('desde')}" + (f" hasta el {p.get('hasta')}" if p.get('hasta') else "") + f" ({p.get('motivo', 'enfermedad')})"),
    actions.Capability("gym.recovery.log", 1, gym_recovery, "Apuntar sensaciones y molestias", summary=lambda p: f"Sensaciones del {p.get('fecha')}"),
    actions.Capability("gym.plan.create", 1, gym_plan_create, "Planificar una sesión", summary=lambda p: f"Planificar {p.get('nombre')} el {p.get('fecha')}"),
    actions.Capability("gym.plan.update", 1, gym_plan_update, "Cambiar una sesión planificada", summary=lambda p: f"Cambiar la sesión {p.get('id')}"),
    actions.Capability("gym.exercise.settings", 1, gym_settings, "Ajustar un ejercicio", summary=lambda p: f"Ajustes de {p.get('ejercicio')}"),
    actions.Capability("task.reschedule", 1, task_reschedule, "Cambiar la fecha de una tarea", summary=lambda p: f"{p.get('texto')} → {p.get('fecha')}"),
    actions.Capability("uni.task.create", 1, _task_in("uni"), "Crear una tarea de la uni", inverse=task_create_undo, summary=lambda p: f"Tarea: {p.get('texto')}"),
    actions.Capability("uni.task.done", 1, _uni_task_done, "Marcar hecha una tarea de la uni", inverse=task_done_undo, summary=lambda p: f"Hecha: {p.get('texto')}"),
    actions.Capability("uni.check", 1, uni_check, "Marcar un bloque, entrega u objetivo de la uni", inverse=uni_check_undo, summary=lambda p: f"Uni: {str(p.get('clave'))[:120]}"),
    actions.Capability("uni.card.add", 1, uni_card_add, "Añadir tarjetas de repaso", inverse=uni_card_add_undo, summary=lambda p: f"{len(p.get('tarjetas') or [])} tarjetas de repaso"),
    actions.Capability("uni.grade.set", 1, uni_grade, "Apuntar una nota", summary=lambda p: f"{p.get('asignatura')} · {p.get('entregable')}: {p.get('nota')}"),
    actions.Capability("career.application.update", 1, application_update, "Actualizar una candidatura", summary=lambda p: f"Candidatura {p.get('id')}: {p.get('estado') or p.get('proximo_paso')}"),
    actions.Capability("career.task.create", 1, _task_in("trabajo"), "Crear una tarea de empleo", inverse=task_create_undo, summary=lambda p: f"Tarea: {p.get('texto')}"),
    actions.Capability("goal.milestone.toggle", 1, milestone_toggle, "Marcar o desmarcar un hito", inverse=milestone_toggle, summary=lambda p: f"Hito {p.get('id')}"),
    actions.Capability("goal.status", 1, goal_set_status, "Cambiar el estado de un objetivo", summary=lambda p: f"Objetivo {p.get('id')}: {p.get('estado')}"),
    actions.Capability("habit.toggle", 1, habit_toggle, "Marcar un hábito", summary=lambda p: f"Hábito {p.get('id')}"),
    actions.Capability("lifestyle.remove", 1, lifestyle_remove, "Quitar de estilo de vida", inverse=lambda r, db: lifestyle_add(r, db), summary=lambda p: f"Quitar {p.get('id')}"),
    actions.Capability("journal.write", 1, journal_write, "Escribir el diario de un día o de una semana", inverse=journal_write_undo,
                       summary=lambda p: f"Diario {p.get('tipo') or 'dia'} {p.get('fecha')} ({p.get('modo') or 'crear'})"),
    actions.Capability("day.close", 1, day_close, "Cerrar el día con lo que cuenta el usuario", summary=lambda p: "Cierre del día"),
    actions.Capability("video.analyze", 1, video_analyze, "Analizar un vídeo", summary=lambda p: f"Vídeo: {p.get('url')}"),
    actions.Capability("ayudante.create", 2, ayudante_create, "Encargar una tarea al ayudante", summary=lambda p: f"Ayudante: {p.get('titulo')}"),
    actions.Capability("encargo.create", 3, encargo_create, "Encargar código al programador", summary=lambda p: f"{p.get('repo')} ({p.get('tipo')}): {p.get('titulo')}"),
    actions.Capability("repo.create", 3, repo_create, "Crear una repo privada", summary=lambda p: f"Repo: {p.get('nombre')}"),
    actions.Capability("task.create", 1, task_create, "Crear una tarea", inverse=task_create_undo, summary=lambda p: f"Tarea: {p.get('texto')}"),
    actions.Capability("task.done", 1, task_done, "Marcar una tarea como hecha", inverse=task_done_undo, summary=lambda p: f"Hecha: {p.get('texto')}"),
    actions.Capability("note.add", 1, note_add, "Guardar una nota en la bandeja", summary=lambda p: "Nota en la bandeja"),
    actions.Capability("gym.register", 1, _synced(gym_register, "sync_workouts"), "Registrar un entreno", summary=lambda p: f"Entreno del {p.get('fecha') or 'día de hoy'}"),
    actions.Capability("health.log", 1, health_log, "Registrar una medida de salud", inverse=health_log_undo, summary=lambda p: f"{p.get('metrica')}: {p.get('valor')}"),
    actions.Capability("career.application.create", 1, application_create, "Seguir una candidatura", summary=lambda p: f"Candidatura: {p.get('empresa')}"),
    actions.Capability("calendar.create", 2, calendar_create, "Crear un evento propio", rule=_rule_mine, inverse=calendar_create_undo,
                       summary=lambda p: f"Evento: {p.get('titulo')} ({p.get('inicio') or p.get('dia')})"),
    actions.Capability("calendar.move", 2, calendar_move, "Mover un evento propio", rule=_rule_mine, summary=lambda p: f"Mover evento {p.get('id')}"),
    actions.Capability("calendar.delete", 3, calendar_delete, "Borrar un evento propio", summary=lambda p: f"Borrar evento {p.get('id')}"),
    actions.Capability("mail.draft", 2, mail_draft, "Crear un borrador de correo", rule=lambda p, lim: p.get("cuenta") in ("gmail", "secundaria", "zoho"),
                       summary=lambda p: f"Borrador a {p.get('para')}: {p.get('asunto')}"),
    actions.Capability("goal.create", 1, goal_create, "Crear un objetivo", summary=lambda p: f"Objetivo: {p.get('titulo')}"),
    actions.Capability("goal.milestone", 1, goal_milestone, "Añadir un hito", summary=lambda p: f"Hito: {p.get('titulo')}"),
    actions.Capability("habit.create", 1, habit_create, "Crear un hábito", summary=lambda p: f"Hábito: {p.get('nombre')}"),
    actions.Capability("ocio.add", 1, ocio_add, "Añadir una peli o serie a Ocio", inverse=ocio_add_undo,
                       summary=lambda p: f"Ocio: {p.get('titulo') or p.get('tmdb_id')} ({p.get('estado') or 'pendiente'})"),
    actions.Capability("ocio.update", 1, ocio_update, "Actualizar una peli o serie (estado, nota, capítulo)", inverse=ocio_update_undo,
                       summary=lambda p: f"Ocio {p.get('id') or p.get('titulo')}: " + ", ".join(f"{k} {p[k]}" for k in ("estado", "valoracion", "temporada", "capitulo") if k in p)),
    actions.Capability("lifestyle.add", 1, lifestyle_add, "Guardar en estilo de vida", summary=lambda p: f"{p.get('tipo')}: {p.get('titulo')}"),
):
    actions.register(cap)


# ---------- lecturas ----------


@gateway.tool("tasks.list")
def _tasks(args: dict, db: Session):
    q = select(Task).where(Task.done.is_(False), Task.removed_at.is_(None)).order_by(Task.due)
    return [{"texto": t.text, "area": t.area, "fecha": t.due} for t in db.scalars(q)]


@gateway.tool("agenda.days")
def _agenda(args: dict, db: Session):
    return agenda_mod.calendario(max(0, min(int(args.get("dias") or 0), 14)))


@gateway.tool("uni.deadlines")
def _deadlines(args: dict, db: Session):
    q = select(Assessment).where(Assessment.done.is_(False), Assessment.removed_at.is_(None), Assessment.due >= date.today().isoformat()).order_by(Assessment.due).limit(30)
    return [{"fecha": a.due, "hora": a.due_time, "texto": a.title} for a in db.scalars(q)]


@gateway.tool("gym.summary")
def _gym(args: dict, db: Session):
    return cli("gym_stats.py", "resumen", f"--dias={max(1, min(int(args.get('dias') or 7), 90))}")


@gateway.tool("mail.recent")
def _mail(args: dict, db: Session):
    return cli("correo.py", "recientes", "--cuenta=todas", f"--dias={max(1, min(int(args.get('dias') or 2), 14))}")


@gateway.tool("mail.read")
def _mail_read(args: dict, db: Session):
    if args.get("cuenta") not in ("gmail", "secundaria", "zoho"):
        raise ValueError("cuenta no válida")
    return cli("correo.py", "leer", f"--cuenta={args['cuenta']}", f"--id={args['id']}")




@gateway.tool("goals.list")
def _goals(args: dict, db: Session):
    from . import personal
    return personal.goals(db)


@gateway.tool("health.list")
def _health(args: dict, db: Session):
    from . import personal
    return personal.health(db)


@gateway.tool("career.list")
def _career(args: dict, db: Session):
    from . import personal
    return personal.career(db)


@gateway.tool("habits.list")
def _habits(args: dict, db: Session):
    from . import personal
    return personal.habits(db)


@gateway.tool("uni.overview")
def _uni_overview(args: dict, db: Session):
    from . import personal
    return personal.education()


@gateway.tool("uni.snapshot")
def _uni_snapshot(args: dict, db: Session):
    from . import education
    return education.tutor_snapshot(db)


@gateway.tool("uni.cards.due")
def _uni_cards_due(args: dict, db: Session):
    from . import education
    return education.cards_due(args.get("asignatura") or None, max(1, min(int(args.get("limite") or 20), 50)), db)


def _tasks_of(area: str, db: Session) -> list[dict]:
    q = select(Task).where(Task.area == area, Task.done.is_(False), Task.removed_at.is_(None)).order_by(Task.due)
    return [{"texto": t.text, "fecha": t.due} for t in db.scalars(q)]


@gateway.tool("uni.tasks")
def _uni_tasks(args: dict, db: Session):
    return _tasks_of("uni", db)


@gateway.tool("career.tasks")
def _career_tasks(args: dict, db: Session):
    return _tasks_of("trabajo", db)


@gateway.tool("lifestyle.list")
def _lifestyle(args: dict, db: Session):
    from . import personal
    return personal.lifestyle(db)


@gateway.tool("ocio.list")
def _ocio_list(args: dict, db: Session):
    from . import ocio
    estado = args.get("estado") or None
    if estado not in (None, *ocio.STATUSES):
        raise ValueError("estado no válido")
    # Sin sinopsis: lo justo para saber qué tiene y por dónde va
    return [{k: v for k, v in x.items() if k not in ("sinopsis", "poster", "capitulos_por_temporada", "actualizado")} for x in ocio.listing(db, estado)]


@gateway.tool("ocio.search")
def _ocio_search(args: dict, db: Session):
    from . import ocio
    return ocio.search(_safe_line(args.get("q", ""))[:200], args.get("tipo") or None)


# Las sinopsis de TMDB son texto de terceros
gateway.EXTERNAL_TOOLS.update({"mail.recent", "mail.read", "ocio.search"})
