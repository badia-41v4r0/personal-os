"""Carpeta común de archivos del usuario (<carpeta del proyecto>/archivos; en los contenedores, /archivos).

Lo que se adjunta en el panel se guarda primero aquí, en `Entrada/AAAA-MM-DD/`, sin sobrescribir nunca. Jarvis lo
ordena después en subcarpetas con `collectors/archivos.py` (solo puede mover dentro de esta carpeta). A una
conversación independiente se le da además una copia en su carpeta de trabajo: los agentes no ven la carpeta común.
"""
import datetime as dt
import os
import re
import unicodedata
import uuid
from pathlib import Path

from fastapi import HTTPException, Request

from .config import get_settings

MAX_FILE = 20 * 1024 * 1024  # como Telegram (límite de los bots)
MAX_FILES = 10
ENTRADA = "Entrada"


def safe_name(name: str) -> str:
    """Nombre plano y legible: sin rutas, sin caracteres de control ni ocultos."""
    n = unicodedata.normalize("NFC", name).replace("\\", "/").split("/")[-1]
    n = re.sub(r"[\x00-\x1f\x7f]", "", n)
    n = re.sub(r"[^\w.\- ()]", "_", n).strip(" .")
    if not n:
        n = "archivo"
    stem, dot, ext = n.rpartition(".")
    if dot and len(ext) <= 10:
        return f"{stem[:100]}.{ext}"
    return n[:110]


def free_name(d: Path, name: str) -> str:
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    final, i, stem = name, 2, stem[:90]
    while (d / final).exists():
        final = f"{stem} ({i}){'.' + ext if ext else ''}"
        i += 1
    return final


def _dir(base: Path, d: Path) -> Path:
    """Crea `d` dentro de `base` y comprueba que ningún tramo intermedio sea un enlace."""
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    cur = base
    for part in d.relative_to(base).parts:
        cur = cur / part
        if cur.is_symlink():
            raise HTTPException(403, "Carpeta no válida")
    if base.resolve() not in d.resolve().parents:
        raise HTTPException(403, "Carpeta no válida")
    return d


async def receive(request: Request, d: Path, name: str) -> tuple[Path, int]:
    """Guarda el cuerpo de la petición en `d` con un nombre libre (hasta 20 MB). Nunca sobrescribe."""
    if int(request.headers.get("content-length") or 0) > MAX_FILE:
        raise HTTPException(413, "El archivo pasa de 20 MB")
    tmp = d / f".subiendo-{uuid.uuid4().hex}"
    total = 0
    try:
        with open(tmp, "xb") as fh:
            async for chunk in request.stream():
                total += len(chunk)
                if total > MAX_FILE:
                    raise HTTPException(413, "El archivo pasa de 20 MB")
                fh.write(chunk)
        if total == 0:
            raise HTTPException(422, "Archivo vacío")
        os.chmod(tmp, 0o600)
        for _ in range(5):
            final = d / free_name(d, safe_name(name))
            try:
                os.link(tmp, final)  # atómico y sin sobrescribir
                return final, total
            except FileExistsError:
                continue
        raise HTTPException(409, "No se pudo elegir un nombre libre")
    finally:
        tmp.unlink(missing_ok=True)


def root() -> Path:
    r = get_settings().files_dir
    r.mkdir(parents=True, exist_ok=True, mode=0o700)
    return r


async def store(request: Request, name: str) -> tuple[Path, int]:
    """Guarda en la carpeta común (Entrada/hoy). Devuelve la ruta en el PC y el tamaño."""
    r = root()
    d = _dir(r, r / ENTRADA / dt.date.today().isoformat())
    return await receive(request, d, name)


def resolve_entry(rel: str) -> Path:
    """Valida una ruta devuelta por store() (relativa a la carpeta común y dentro de Entrada/)."""
    r = root().resolve()
    parts = Path(rel).parts
    if not parts or parts[0] != ENTRADA or any(p in ("..", ".") or p.startswith((".", "/")) for p in parts) \
            or "\x00" in rel:
        raise HTTPException(422, "Adjunto no válido")
    f = r.joinpath(*parts)
    if f.is_symlink() or not f.is_file() or r not in f.resolve().parents:
        raise HTTPException(422, f"No encuentro el adjunto {parts[-1]}: súbelo otra vez")
    return f
