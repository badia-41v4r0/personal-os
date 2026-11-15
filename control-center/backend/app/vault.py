"""Memory: lectura, búsqueda y edición controlada de la vault de Obsidian (la fuente de verdad).

- Nada se copia a SQLite: se lee del disco en cada petición.
- Solo rutas dentro de la vault, sin carpetas ocultas (.obsidian, .stversions, .trash…) ni enlaces que salgan.
- Edición solo de .md que no genera un script (lista GENERADOS, con el motivo) y con control de concurrencia:
  el cliente manda el hash que leyó; si el archivo cambió entretanto (Obsidian, Syncthing, Jarvis), 409.
- Escritura atómica (temporal + rename), auditada y con evento.
"""
import hashlib
import os
import re
import tempfile
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import events
from .config import get_settings
from .db import get_db
from .security import Principal, current_principal, require_admin

router = APIRouter(prefix="/api/v1/memory", dependencies=[Depends(current_principal)])

MAX_READ = 2_000_000
MAX_WRITE = 1_000_000
TEXT_EXT = {".md", ".txt", ".csv", ".json", ".css", ".ics"}
IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}

# Archivos que escriben los scripts: se pueden leer, no editar desde el panel.
GENERADOS: list[tuple[str, str]] = [
    ("Jarvis/Tareas.md", "Copia de la base de datos del panel: crea y cambia las tareas desde Tareas en el panel (en Obsidian solo se acepta marcar casillas)"),
    ("Jarvis/Diario/*", "Copia de la base de datos del panel: el diario lo escribe el cierre del día (díselo a Jarvis para corregirlo)"),
    ("Jarvis/Panel.md", "Lo genera build.py cada mañana (Jarvis solo marca casillas y notas del día)"),
    ("Jarvis/Areas/Ofertas.md", "Lo genera ofertas.py"),
    ("Jarvis/Sistema/digest.md", "Lo genera build.py"),
    ("Jarvis/Sistema/semana.md", "Lo genera semanal.py"),
    ("Jarvis/Sistema/panel-archivo/*", "Archivo de Paneles anteriores"),
    ("Jarvis/Sistema/*.json", "Estado interno de los scripts"),
    ("Jarvis/*/en-curso/*", "Tarea en curso de una cola: la está procesando un script"),
    ("*.sync-conflict-*", "Conflicto de Syncthing: resuélvelo en Obsidian"),
]
# Notas con partes generadas: editables, con aviso.
PARCIALES: dict[str, str] = {
    "Jarvis/Areas/Trabajo.md": "La tabla «Pipeline de candidaturas» es una copia de la base de datos: lo que cambies ahí se descarta (usa Carrera en el panel)",
    "Jarvis/Areas/Notas-Uni.md": "El «## Resumen» (Nota actual y Estado) lo reescribe notas.py",
    "Jarvis/Areas/Gym.md": "«## Registro» es una copia de la base de datos: lo que cambies ahí se descarta (registra y corrige entrenos desde Entrenamiento o con Jarvis). Rutina y Perfil sí se editan aquí",
}
WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\\?\|[^\]]*)?\]\]")


def root() -> Path:
    return get_settings().vault.resolve()


def safe(rel: str) -> Path:
    """Ruta relativa → absoluta dentro de la vault, o 403/404."""
    rel = (rel or "").strip().lstrip("/")
    parts = PurePosixPath(rel).parts
    if any(p in ("..", "") or p.startswith(".") for p in parts) or "\x00" in rel:
        raise HTTPException(403, "Ruta no permitida")
    r = root()
    p = (r / rel).resolve()
    if p != r and r not in p.parents:
        raise HTTPException(403, "Ruta fuera de la vault")
    return p


def rel(p: Path) -> str:
    return p.relative_to(root()).as_posix()


def editable(relpath: str) -> tuple[bool, str]:
    if not relpath.endswith(".md"):
        return False, "Solo se editan notas .md"
    for pat, why in GENERADOS:
        if fnmatch(relpath, pat):
            return False, why
    return True, PARCIALES.get(relpath, "")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _visible(p: Path) -> bool:
    return not p.name.startswith(".")


def _all_md() -> list[Path]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root()):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        out += [Path(dirpath) / f for f in filenames if f.endswith(".md") and not f.startswith(".")]
    return out


@router.get("/tree")
def tree(path: str = ""):
    d = safe(path)
    if not d.is_dir():
        raise HTTPException(404, "Carpeta no encontrada")
    items = []
    for c in sorted(d.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower())):
        if not _visible(c) or c.is_symlink():
            continue
        st = c.stat()
        items.append({"name": c.name, "path": rel(c), "dir": c.is_dir(), "size": st.st_size,
                      "mtime": st.st_mtime})
    return {"path": rel(d) if d != root() else "", "items": items}


@router.get("/file")
def read_file(path: str):
    p = safe(path)
    if not p.is_file():
        raise HTTPException(404, "Archivo no encontrado")
    if p.suffix.lower() not in TEXT_EXT:
        raise HTTPException(415, "Solo se muestran archivos de texto")
    data = p.read_bytes()
    if len(data) > MAX_READ:
        raise HTTPException(413, "Archivo demasiado grande")
    r = rel(p)
    ok, note = editable(r)
    return {"path": r, "content": data.decode("utf-8", errors="replace"), "sha": sha(data),
            "mtime": p.stat().st_mtime, "editable": ok, "note": note}


@router.get("/raw")
def raw(path: str):
    """Imágenes incrustadas en las notas (solo tipos de imagen)."""
    from fastapi.responses import FileResponse
    p = safe(path)
    if not p.is_file() or p.suffix.lower() not in IMG_EXT:
        raise HTTPException(404, "Imagen no encontrada")
    resp = FileResponse(p)
    if p.suffix.lower() == ".svg":  # un SVG puede llevar scripts: que no se ejecute
        resp.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    return resp


class SaveIn(BaseModel):
    path: str
    content: str = Field(max_length=MAX_WRITE)
    base_sha: str | None = None  # None = archivo nuevo


@router.put("/file")
def save_file(body: SaveIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    f = safe(body.path)
    r = rel(f)
    ok, why = editable(r)
    if not ok:
        events.audit(db, p.name, "memory.save", target=r, outcome="denied", reason=why)
        db.commit()
        raise HTTPException(403, f"No editable: {why}")
    exists = f.exists()
    if exists and body.base_sha is None:
        raise HTTPException(409, "El archivo ya existe")
    if not exists and body.base_sha is not None:
        raise HTTPException(409, "El archivo ya no existe")
    if exists:
        current = f.read_bytes()
        if sha(current) != body.base_sha:
            events.audit(db, p.name, "memory.save", target=r, outcome="denied", reason="conflicto")
            db.commit()
            raise HTTPException(409, "La nota ha cambiado desde que la abriste (Obsidian, Syncthing o Jarvis). Recárgala.")
    if not f.parent.is_dir():
        raise HTTPException(404, "La carpeta no existe")
    data = body.content.encode("utf-8")
    fd, tmp = tempfile.mkstemp(prefix=".cc-", suffix=".tmp", dir=f.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        if exists:
            os.chmod(tmp, f.stat().st_mode & 0o777)
        os.replace(tmp, f)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise
    events.audit(db, p.name, "memory.save", target=r, bytes=len(data), new=not exists)
    events.publish("memory.saved", {"path": r}, db=db)
    return {"path": r, "sha": sha(data), "mtime": f.stat().st_mtime}


@router.get("/search")
def search(q: str, limit: int = 40):
    q = q.strip()
    if len(q) < 2:
        raise HTTPException(422, "Escribe al menos 2 caracteres")
    needle = q.lower()
    hits = []
    for f in _all_md():
        r = rel(f)
        name_hit = needle in f.stem.lower()
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        i = text.lower().find(needle)
        if i < 0 and not name_hit:
            continue
        snippet = ""
        if i >= 0:
            a, b = max(0, i - 60), min(len(text), i + len(q) + 80)
            snippet = ("…" if a else "") + text[a:b].replace("\n", " ") + ("…" if b < len(text) else "")
        hits.append({"path": r, "name": f.stem, "snippet": snippet, "score": (2 if name_hit else 0) + text.lower().count(needle),
                     "mtime": f.stat().st_mtime})
    hits.sort(key=lambda h: (-h["score"], -h["mtime"]))
    return hits[: max(1, min(limit, 100))]


@router.get("/recent")
def recent(limit: int = 20):
    files = sorted(_all_md(), key=lambda f: f.stat().st_mtime, reverse=True)[: max(1, min(limit, 100))]
    return [{"path": rel(f), "name": f.stem, "mtime": f.stat().st_mtime} for f in files]


@router.get("/resolve")
def resolve(name: str, from_path: str = ""):
    """Resuelve un [[wikilink]] como Obsidian: ruta exacta o, si no, por nombre de archivo (el más cercano)."""
    name = name.strip().removesuffix(".md")
    try:
        exact = safe(name + ".md")
        if exact.is_file():
            return {"path": rel(exact)}
    except HTTPException:
        pass
    target = name.split("/")[-1].lower()
    cands = [f for f in _all_md() if f.stem.lower() == target]
    if not cands:
        raise HTTPException(404, "Nota no encontrada")
    base = from_path.split("/")[:-1]
    cands.sort(key=lambda f: (-len(os.path.commonprefix([base, rel(f).split("/")[:-1]])), len(rel(f))))
    return {"path": rel(cands[0])}


@router.get("/backlinks")
def backlinks(path: str):
    stem = PurePosixPath(path).stem.lower()
    full = path.removesuffix(".md").lower()
    out = []
    for f in _all_md():
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in WIKILINK.finditer(text):
            t = m.group(1).strip().lower()
            if t == full or t.split("/")[-1] == stem:
                out.append({"path": rel(f), "name": f.stem})
                break
    return [o for o in out if o["path"] != path][:50]


@router.get("/rules")
def rules():
    return {"generados": [{"patron": p, "motivo": m} for p, m in GENERADOS],
            "parciales": [{"ruta": r, "aviso": m} for r, m in PARCIALES.items()],
            "ts": datetime.now(timezone.utc).isoformat()}
