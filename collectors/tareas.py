"""Tareas: lee Jarvis/Tareas.md (formato `- [ ] texto 📅 AAAA-MM-DD #area`)."""
import os
import re
from datetime import date, datetime, timedelta

import ajustes
from lib import CHECKBOX, JARVIS, SISTEMA, load_json, save_json

TAREAS = JARVIS / "Tareas.md"
PANEL = JARVIS / "Panel.md"
HECHOS = SISTEMA / "hechos.json"         # clave -> fecha en que se marcó (estudio, entregas, entreno)
PANEL_ESTADO = SISTEMA / "panel-estado.json"   # texto de cada casilla del Panel -> clave (lo escribe build.py)
CASILLA = re.compile(r"^(>?\s*- \[)( |x|X)(\] )(.*)$")   # la misma casilla que lee build.py
# Áreas de la instancia (config perfil.json); se leen en cada uso para que un cambio en Ajustes valga sin reiniciar
AREAS = ajustes.areas()
FECHA = re.compile(r"📅\s*(\d{4}-\d{2}-\d{2})")
TAG = re.compile(r"#(\w+)")
HECHO = re.compile(r"✅\s*(\d{4}-\d{2}-\d{2})")


def parse(line: str):
    c = CHECKBOX.match(line)
    if not c:
        return None
    body = c[2]
    f = FECHA.search(body)
    tags = [t.lower() for t in TAG.findall(body)]
    area = next((t for t in tags if t in ajustes.areas()), "personal")
    texto = re.sub(r"\s+", " ", TAG.sub("", FECHA.sub("", body))).strip()
    hecho_el = HECHO.search(texto)
    texto = HECHO.sub("", texto).strip()
    return {"texto": texto, "fecha": f[1] if f else None, "area": area, "hecho": c[1] != " ",
            "hecho_el": hecho_el[1] if hecho_el else None}


def recoger(hoy: date, dias: int = 7) -> dict:
    if not TAREAS.exists():
        return {"hoy": [], "hechas_hoy": [], "proximas": [], "sin_fecha": []}
    todas = [t for t in map(parse, TAREAS.read_text(encoding="utf-8").splitlines()) if t]
    tareas = [t for t in todas if not t["hecho"]]
    limite = (hoy + timedelta(days=dias)).isoformat()
    h = hoy.isoformat()
    return {
        # Hoy incluye las atrasadas
        "hoy": [t | {"atrasada": t["fecha"] < h} for t in tareas if t["fecha"] and t["fecha"] <= h],
        "proximas": sorted((t for t in tareas if t["fecha"] and h < t["fecha"] <= limite), key=lambda t: t["fecha"]),
        "sin_fecha": [t for t in tareas if not t["fecha"]],
        "hechas_hoy": [t for t in todas if t["hecho"] and t["hecho_el"] == h],
    }


def marcar_hechas(textos: set[str], hoy: date) -> int:
    """Marca como hechas en Tareas.md las tareas cuyo texto está en `textos`."""
    if not TAREAS.exists() or not textos:
        return 0
    lines, n = TAREAS.read_text(encoding="utf-8").splitlines(), 0
    for i, line in enumerate(lines):
        t = parse(line)
        if t and not t["hecho"] and t["texto"] in textos:
            lines[i] = line.replace("- [ ]", "- [x]", 1).rstrip() + f" ✅ {hoy.isoformat()}"
            n += 1
    TAREAS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return n


def desmarcar(textos: set[str]) -> int:
    """Deshace marcar_hechas para tareas que se han desmarcado en el Panel."""
    if not TAREAS.exists() or not textos:
        return 0
    lines, n = TAREAS.read_text(encoding="utf-8").splitlines(), 0
    for i, line in enumerate(lines):
        t = parse(line)
        if t and t["hecho"] and t["texto"] in textos:
            lines[i] = HECHO.sub("", line.replace("- [x]", "- [ ]", 1)).rstrip()
            n += 1
    TAREAS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return n


def _escribir(path, lines: list[str]) -> None:
    """Escritura atómica: Obsidian o Syncthing nunca ven el archivo a medias."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _casilla_panel(texto: str, hecho: bool) -> int:
    return casilla_panel(f"tarea|{texto}", hecho)


def casilla_tarea(texto: str, hecho: bool) -> int:
    """La casilla de esa tarea en el Panel de hoy (la base ya cambió: el Panel debe quedar igual)."""
    return _casilla_panel(texto, hecho)


def marcas_panel() -> dict[str, bool]:
    """Cómo está cada casilla del Panel de hoy: lo marcado en Obsidian aún no ha llegado a hechos.json."""
    if not PANEL.exists():
        return {}
    estado = load_json(PANEL_ESTADO, {})
    marcas = {}
    for line in PANEL.read_text(encoding="utf-8").splitlines():
        c = CASILLA.match(line)
        if c and c[4].strip() in estado:
            marcas[estado[c[4].strip()]] = c[2] != " "
    return marcas


def marcar_clave(clave: str, hecho: bool, hoy: date | None = None) -> None:
    """Marca un bloque de estudio o una entrega igual que la casilla del Panel: planificador y resumen semanal leen esto."""
    hechos = load_json(HECHOS, {})
    if hecho:
        hechos.setdefault(clave, (hoy or datetime.now().date()).isoformat())
    else:
        hechos.pop(clave, None)
    save_json(HECHOS, hechos)
    casilla_panel(clave, hecho)


def casilla_panel(clave: str, hecho: bool) -> int:
    """Pone igual esa casilla en el Panel de hoy, para que la regeneración no la deshaga
    (build.py quita lo que se marcó en el Panel y luego se desmarcó)."""
    if not PANEL.exists():
        return 0
    estado = load_json(PANEL_ESTADO, {})
    lines, n = PANEL.read_text(encoding="utf-8").splitlines(), 0
    for i, line in enumerate(lines):
        c = CASILLA.match(line)
        if c and estado.get(c[4].strip()) == clave and (c[2] != " ") != hecho:
            lines[i] = f"{c[1]}{'x' if hecho else ' '}{c[3]}{c[4]}"
            n += 1
    if n:
        _escribir(PANEL, lines)
    return n


def cambiar(texto: str, hecho: bool, hoy: date | None = None) -> dict:
    """Marca (o desmarca) como hecha una tarea de Tareas.md por su texto, y su casilla del Panel si está.
    Lo usa el Control Center; el resultado es el mismo que marcarla en el Panel y esperar a la regeneración."""
    hoy = hoy or datetime.now().date()
    if not TAREAS.exists():
        return {"tareas": 0, "panel": 0}
    lines, n = TAREAS.read_text(encoding="utf-8").splitlines(), 0
    for i, line in enumerate(lines):
        t = parse(line)
        if not t or t["texto"] != texto or t["hecho"] == hecho:
            continue
        if hecho:
            lines[i] = re.sub(r"\[ \]", "[x]", line, count=1).rstrip() + f" ✅ {hoy.isoformat()}"
        else:
            lines[i] = HECHO.sub("", re.sub(r"\[[xX]\]", "[ ]", line, count=1)).rstrip()
        n += 1
    if n:
        _escribir(TAREAS, lines)
    return {"tareas": n, "panel": _casilla_panel(texto, hecho) if n else 0}


if __name__ == "__main__":
    import json, sys
    d = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else datetime.now().date()
    print(json.dumps(recoger(d), ensure_ascii=False, indent=1))
