"""Copias en Markdown de lo que manda la base de datos: tareas, entrenos, candidaturas y diario.

Scripts, rutinas y Obsidian siguen leyendo estas notas, y lo que se edite en ellas se importa (vault_sync). Pero si una
nota desaparece o se vacía, la base no se borra con ella: la nota se rehace desde aquí y se avisa.
"""
import json
import logging
import os
import tempfile
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import JobApplication, JournalDay, Task, VaultRecord, Workout

log = logging.getLogger("cc.mirror")
TAREAS_INICIO = "# ✅ Tareas\n\n🧭 [[Jarvis/Panel|← Panel]]\n\nFormato: `- [ ] qué hay que hacer 📅 AAAA-MM-DD #area`\n"
AVISO_COPIA = "> ⚠️ Copia generada desde la base de datos del panel: solo se acepta marcar casillas; lo demás que cambies aquí se descarta."
PIPELINE = "## Pipeline de candidaturas"
CABECERA = ["| Empresa | Puesto | Estado | Fecha | Próximo paso | Follow-up |", "|---|---|---|---|---|---|"]


def _write(path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as h:
        h.write(text)
    os.chmod(tmp, path.stat().st_mode & 0o777 if path.exists() else 0o644)
    os.replace(tmp, path)


def warn(text: str) -> None:
    """Aviso sin modelo, por la misma cola que usan los scripts: si falla, queda en el registro."""
    log.warning(text)
    try:
        d = get_settings().data_dir / "avisos"
        d.mkdir(mode=0o700, parents=True, exist_ok=True)
        (d / f"{time.time_ns()}-copia.json").write_text(json.dumps({"text": text, "level": "action", "url": "/bandeja/"}, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        log.warning("aviso no guardado: %s", e)


def task_line(t: Task) -> str:
    return (f"- [{'x' if t.done else ' '}] {t.text}" + (f" 📅 {t.due}" if t.due else "") + f" #{t.area}"
            + (f" ✅ {t.done_on}" if t.done and t.done_on else ""))


def orden_nota(tareas) -> list[Task]:
    """El orden en que salen en Tareas.md: pendientes y luego hechas; en cada grupo, por fecha (sin fecha al final) y por
    antigüedad. vault_sync empareja las tareas repetidas por este mismo orden."""
    return sorted(tareas, key=lambda t: (bool(t.done), t.due is None, t.due or "", t.id))


def export_tasks(db: Session, path=None) -> None:
    path = path or get_settings().vault / "Jarvis/Tareas.md"
    previo = path.read_text(encoding="utf-8") if path.exists() else TAREAS_INICIO
    if "## Pendientes" in previo:
        inicio = previo.split("## Pendientes", 1)[0].rstrip()
    else:  # una nota sin secciones: la cabecera llega hasta la primera tarea, para no duplicarlas
        lineas = previo.splitlines()
        inicio = "\n".join(lineas[:next((i for i, x in enumerate(lineas) if x.lstrip().startswith("- [")), len(lineas))]).rstrip()
    if AVISO_COPIA not in inicio:
        inicio += "\n\n" + AVISO_COPIA
    filas = orden_nota(db.scalars(select(Task).where(Task.removed_at.is_(None))))
    pendientes = [task_line(t) for t in filas if not t.done]
    hechas = [task_line(t) for t in filas if t.done]
    _write(path, "\n".join([inicio, "", "## Pendientes", *pendientes, "", "## Hechas", *hechas]) + "\n")


AVISO_GYM = "> ⚠️ Copia generada desde la base de datos del panel: registra o corrige entrenos desde el panel o con tu asistente; lo que cambies aquí se descarta."


def workouts_text(db: Session) -> str:
    """El registro tal como lo escribe la copia, sin el aviso."""
    filas = db.scalars(select(Workout).where(Workout.removed_at.is_(None), Workout.source_text != "").order_by(Workout.day, Workout.id))
    return "\n\n".join(w.source_text.strip() for w in filas)


def registro_partes(text: str) -> tuple[str, str | None, str]:
    """(lo de antes de `## Registro`, el registro sin aviso o None si no hay, las secciones `## ` que vengan detrás)."""
    if "## Registro" not in text:
        return text.rstrip(), None, ""
    inicio, cuerpo = text.split("## Registro", 1)
    corte = cuerpo.find("\n## ")
    reg, resto = (cuerpo, "") if corte == -1 else (cuerpo[:corte], cuerpo[corte + 1:])
    return inicio.rstrip(), reg.strip().removeprefix(AVISO_GYM).strip(), resto.strip()


def export_workouts(db: Session) -> None:
    path = get_settings().vault / "Jarvis/Areas/Gym.md"
    registro = workouts_text(db)
    if not path.exists() and not registro:
        return  # nada que copiar: no se crea una nota vacía
    previo = path.read_text(encoding="utf-8") if path.exists() else "# Gym\n\n"
    inicio, _, resto = registro_partes(previo)
    nuevo = "\n\n".join(x for x in [inicio, "## Registro", AVISO_GYM, registro, resto] if x) + "\n"
    if nuevo != previo:
        _write(path, nuevo)


def _cell(v) -> str:
    return " ".join(str(v or "").replace("|", "/").split())


def pipeline_rows(db: Session) -> list[str]:
    """Las filas del pipeline tal como las escribe la copia (sin cabecera)."""
    return [f"| {_cell(a.company)} | {_cell(a.role)} | {_cell(a.status)} | {a.updated_at:%Y-%m-%d} | {_cell(a.next_step)} | {_cell(a.follow_up)} |"
            for a in db.scalars(select(JobApplication).order_by(JobApplication.created_at))]


def pipeline_in_note(text: str) -> list[str] | None:
    """Las filas que hay ahora en la nota (sin cabecera ni separador), o None si no tiene el pipeline."""
    if PIPELINE not in text:
        return None
    lineas = text.split(PIPELINE, 1)[1].split("\n")[1:]
    tabla = []
    for x in lineas:
        if not x.lstrip().startswith("|"):
            break
        tabla.append(x.strip())
    return tabla[2:]  # cabecera y separador


def export_jobs(db: Session) -> None:
    """La tabla del pipeline de Trabajo.md: el resto de la nota no se toca."""
    path = get_settings().vault / "Jarvis/Areas/Trabajo.md"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    if PIPELINE not in text:
        return
    antes, resto = text.split(PIPELINE, 1)
    lineas = resto.split("\n")
    i = 1
    while i < len(lineas) and lineas[i].lstrip().startswith("|"):
        i += 1
    nuevo = antes + PIPELINE + "\n" + "\n".join([*CABECERA, *pipeline_rows(db), *lineas[i:]])
    if nuevo != text:
        _write(path, nuevo)


AVISO_DIARIO = "> ⚠️ Copia generada desde la base de datos del panel: lo que cambies aquí se descarta. El diario lo escribe el cierre del día."
DIARIO = "Jarvis/Diario"


def journal_path(day: str, kind: str) -> str:
    return f"{DIARIO}/{'Semana ' if kind == 'semana' else ''}{day}.md"


def _split_front(text: str) -> tuple[str, str]:
    """(frontmatter con sus ---, resto). Sin frontmatter, ('', texto)."""
    if text.startswith("---\n"):
        fin = text.find("\n---\n", 4)
        if fin != -1:
            return text[:fin + 5], text[fin + 5:]
    return "", text


def journal_text(content: str) -> str:
    """El texto de la copia: el aviso va justo tras el frontmatter, para que Obsidian lo siga leyendo."""
    front, body = _split_front(content)
    return f"{front}{AVISO_DIARIO}\n\n{body.lstrip(chr(10))}"


def strip_journal_notice(text: str) -> str:
    front, body = _split_front(text)
    if body.startswith(AVISO_DIARIO):
        body = body[len(AVISO_DIARIO):].lstrip("\n")
    return front + body


def journal_canon(text: str) -> str:
    """La forma en que se guarda en la base: sin aviso y como queda tras pasar por la copia."""
    return strip_journal_notice(journal_text(strip_journal_notice(text)))


def export_journal(db: Session, row: "JournalDay | None" = None) -> int:
    """Rehace la copia de un día (o de todos). Devuelve cuántas notas ha escrito."""
    root = get_settings().vault
    rows = [row] if row is not None else list(db.scalars(select(JournalDay)))
    n = 0
    for r in rows:
        path = root / r.path
        text = journal_text(r.content)
        if not path.exists() or path.read_text(encoding="utf-8", errors="replace") != text:
            _write(path, text)
            n += 1
    return n


def hechos_path():
    return get_settings().vault / "Jarvis/Sistema/hechos.json"  # la misma que `tareas.HECHOS` en producción


def hechos_dict(db: Session) -> dict[str, str]:
    """clave -> fecha de lo marcado (bloques, entregas, gym, tareas del Panel), como lo leen planificador y semanal."""
    filas = db.scalars(select(VaultRecord).where(VaultRecord.kind == "hecho", VaultRecord.removed_at.is_(None)))
    pares = sorted(((r.data.get("fecha") or "", r.data["clave"]) for r in filas if r.data.get("clave")))
    return {k: f for f, k in pares}


def export_hechos(db: Session) -> None:
    path = hechos_path()
    nuevo = json.dumps(hechos_dict(db), ensure_ascii=False, indent=1)
    if not path.exists() or path.read_text(encoding="utf-8") != nuevo:
        _write(path, nuevo)
