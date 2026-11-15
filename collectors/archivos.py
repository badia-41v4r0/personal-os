#!/usr/bin/env python3
"""Carpeta común de archivos del usuario (en el PC: <carpeta del proyecto>/archivos; en el contenedor: /archivos).

Lo que llega desde el panel (o lo que Jarvis guarda de Telegram) entra en `Entrada/AAAA-MM-DD/`. Jarvis lo ordena
en subcarpetas con este script, que solo trabaja DENTRO de la carpeta común: no sobrescribe, no borra y no sigue
enlaces. Uso:

  archivos.py listar [carpeta]              árbol (2 niveles) con tamaños
  archivos.py mover <origen> <carpeta>      mueve un archivo o carpeta a <carpeta> (la crea si hace falta)
  archivos.py renombrar <origen> <nombre>   cambia el nombre sin moverlo
  archivos.py carpeta <carpeta>             crea una carpeta
  archivos.py guardar <ruta-telegram> [carpeta]
                                            copia un archivo de la bandeja de Telegram (por defecto a Entrada/hoy)

Las rutas son relativas a la carpeta común (también vale con /archivos/ delante).
"""
import datetime as dt
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path("/archivos") if Path("/archivos").is_dir() else Path(__file__).resolve().parent.parent / "archivos"
TELEGRAM_INBOX = Path("/home/node/.claude/channels/telegram/inbox")
NOMBRE_MAL = re.compile(r"[\x00-\x1f\x7f/\\]")


class Error(Exception):
    pass


def _rel(texto: str) -> Path:
    t = texto.strip()
    for pre in (str(ROOT) + "/", "/archivos/"):
        if t.startswith(pre):
            t = t[len(pre):]
    if t in ("", ".", str(ROOT), "/archivos"):
        return ROOT
    if t.startswith("/") or "\x00" in t:
        raise Error(f"Ruta fuera de la carpeta común: {texto}")
    partes = Path(t).parts
    if any(p in ("..", ".") or p.startswith(".") for p in partes):
        raise Error(f"Ruta no permitida: {texto}")
    p = ROOT.joinpath(*partes)
    # Ningún tramo puede ser un enlace (podría sacar la ruta fuera)
    cur = ROOT
    for parte in partes:
        cur = cur / parte
        if cur.is_symlink():
            raise Error(f"Enlace no permitido: {texto}")
    if ROOT.resolve() not in (p.resolve(), *p.resolve().parents):
        raise Error(f"Ruta fuera de la carpeta común: {texto}")
    return p


def _libre(destino: Path) -> Path:
    if not destino.exists():
        return destino
    stem, suf = destino.stem, destino.suffix
    for i in range(2, 1000):
        c = destino.with_name(f"{stem} ({i}){suf}")
        if not c.exists():
            return c
    raise Error("Demasiados archivos con ese nombre")


def _nombre(n: str) -> str:
    n = n.strip()
    if not n or n in (".", "..") or n.startswith(".") or NOMBRE_MAL.search(n) or len(n) > 150:
        raise Error(f"Nombre no válido: {n!r}")
    return n


def _mostrar(p: Path) -> str:
    return "/" + p.relative_to(ROOT).as_posix() if p != ROOT else "/"


def entrada_hoy() -> Path:
    return ROOT / "Entrada" / dt.date.today().isoformat()


def listar(carpeta: str = "") -> str:
    base = _rel(carpeta)
    if not base.is_dir():
        raise Error(f"No existe la carpeta {carpeta}")
    out = [f"📁 {_mostrar(base)}"]

    def walk(d: Path, nivel: int):
        hijos = sorted((c for c in d.iterdir() if not c.name.startswith(".") and not c.is_symlink()),
                       key=lambda c: (not c.is_dir(), c.name.lower()))
        for c in hijos:
            pre = "  " * nivel
            if c.is_dir():
                n = sum(1 for _ in c.rglob("*") if _.is_file())
                out.append(f"{pre}📁 {c.name}/ ({n} archivos)")
                if nivel < 2:
                    walk(c, nivel + 1)
            else:
                kb = c.stat().st_size / 1024
                out.append(f"{pre}- {c.name} ({kb:.0f} KB)" if kb < 1024 else f"{pre}- {c.name} ({kb / 1024:.1f} MB)")

    walk(base, 1)
    return "\n".join(out) if len(out) > 1 else out[0] + " (vacía)"


def carpeta(ruta: str) -> str:
    p = _rel(ruta)
    if p == ROOT:
        raise Error("Indica una carpeta")
    for parte in p.relative_to(ROOT).parts:
        _nombre(parte)
    p.mkdir(parents=True, exist_ok=True)
    return f"Carpeta lista: {_mostrar(p)}"


def mover(origen: str, destino_carpeta: str) -> str:
    o = _rel(origen)
    if o == ROOT or not o.exists():
        raise Error(f"No existe {origen}")
    carpeta(destino_carpeta)
    d = _rel(destino_carpeta)
    if o.is_dir() and (d == o or o in d.parents):
        raise Error("No se puede mover una carpeta dentro de sí misma")
    final = _libre(d / o.name)
    os.rename(o, final)
    return f"Movido: {_mostrar(o)} → {_mostrar(final)}"


def renombrar(origen: str, nombre: str) -> str:
    o = _rel(origen)
    if o == ROOT or not o.exists():
        raise Error(f"No existe {origen}")
    final = _libre(o.with_name(_nombre(nombre)))
    os.rename(o, final)
    return f"Renombrado: {_mostrar(o)} → {_mostrar(final)}"


def guardar(ruta_telegram: str, destino_carpeta: str = "") -> str:
    src = Path(ruta_telegram)
    inbox = TELEGRAM_INBOX.resolve()
    if src.is_symlink() or not src.is_file() or inbox not in src.resolve().parents:
        raise Error("Solo se pueden guardar archivos de la bandeja de Telegram")
    if destino_carpeta:
        carpeta(destino_carpeta)
        d = _rel(destino_carpeta)
    else:
        d = entrada_hoy()
        d.mkdir(parents=True, exist_ok=True)
    final = _libre(d / _nombre(src.name))
    shutil.copyfile(src, final)
    return f"Guardado: {_mostrar(final)}"


def main(argv: list[str]) -> int:
    ROOT.mkdir(exist_ok=True)
    cmds = {"listar": (listar, 0, 1), "carpeta": (carpeta, 1, 1), "mover": (mover, 2, 2),
            "renombrar": (renombrar, 2, 2), "guardar": (guardar, 1, 2)}
    if not argv or argv[0] not in cmds:
        print(__doc__)
        return 2
    fn, mn, mx = cmds[argv[0]]
    args = argv[1:]
    if not (mn <= len(args) <= mx):
        print(__doc__)
        return 2
    try:
        print(fn(*args))
        return 0
    except (Error, OSError) as e:
        print(f"❌ {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
