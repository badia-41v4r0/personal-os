"""Navegación de la vault: barra del Panel y línea 🧭 (migas) al principio de cada nota de Jarvis.

La línea que empieza por 🧭 la pone este script (justo debajo del título #); no se edita a mano.
Se ejecuta al final de build.py, después del script que regenera Ofertas.md.
"""
import re
from datetime import date

from lib import JARVIS, VAULT, write_atomic

SEMANAS = VAULT / "Uni" / "Planificación" / "Semanas"
MARCA = "🧭 "


def _semana_actual(hoy: date) -> str | None:
    for f in sorted(SEMANAS.glob("*.md")):
        txt = f.read_text(encoding="utf-8")
        ini = re.search(r"^inicio:\s*(\d{4}-\d{2}-\d{2})", txt, re.M)
        fin = re.search(r"^fin:\s*(\d{4}-\d{2}-\d{2})", txt, re.M)
        if ini and fin and ini[1] <= hoy.isoformat() <= fin[1]:
            return f"Uni/Planificación/Semanas/{f.stem}"
    return None


def _ultimo_diario() -> str | None:
    dias = sorted(p.stem for p in (JARVIS / "Diario").glob("????-??-??.md"))
    return f"Jarvis/Diario/{dias[-1]}" if dias else None


def enlaces(hoy: date) -> dict[str, str]:
    """Nombre corto -> enlace de Obsidian."""
    e = {
        "Panel": "[[Jarvis/Panel|← Panel]]",
        "Uni": "[[Jarvis/Areas/Uni|🎓 Uni]]",
        "Notas": "[[Jarvis/Areas/Notas-Uni|📊 Notas]]",
        "Plan": "[[Uni/Planificación/Plan|🚀 Plan]]",
        "Asignaturas": "[[Uni/Inicio|📚 Asignaturas]]",
        "Trabajo": "[[Jarvis/Areas/Trabajo|💼 Trabajo]]",
        "Ofertas": "[[Jarvis/Areas/Ofertas|🎯 Ofertas]]",
        "Gym": "[[Jarvis/Areas/Gym|🏋️ Gym]]",
        "Personal": "[[Jarvis/Areas/Personal|🙋 Personal]]",
        "Tareas": "[[Jarvis/Tareas|✅ Tareas]]",
    }
    if s := _semana_actual(hoy):
        e["Semana"] = f"[[{s}|📅 Semana actual]]"
    if d := _ultimo_diario():
        e["Diario"] = f"[[{d}|📓 Diario]]"
    return e


def barra(hoy: date) -> list[str]:
    """Líneas del callout de navegación para el Panel."""
    e = enlaces(hoy)
    filas = [["Uni", "Notas", "Plan", "Semana", "Asignaturas"],
             ["Trabajo", "Ofertas", "Gym", "Personal"],
             ["Tareas", "Diario"]]
    return ["> [!jarvis-nav] 🧭"] + ["> " + " · ".join(e[k] for k in f if k in e) for f in filas]


# Nota -> enlaces de su línea 🧭 (además de ← Panel)
MIGAS = {
    "Areas/Uni": ["Notas", "Plan", "Semana", "Asignaturas"],
    "Areas/Notas-Uni": ["Uni", "Semana", "Plan"],
    "Areas/Trabajo": ["Ofertas"],
    "Areas/Ofertas": ["Trabajo"],
    "Areas/Gym": [],
    "Areas/Personal": [],
    "Tareas": [],
}


def poner_migas(path, linea: str) -> None:
    if not path.exists():
        return
    txt = path.read_text(encoding="utf-8")
    lineas = txt.split("\n")
    i = next((n for n, l in enumerate(lineas) if l.startswith(MARCA)), None)
    if i is not None:
        lineas[i] = linea
    else:
        h1 = next((n for n, l in enumerate(lineas) if l.startswith("# ")), None)
        if h1 is None:
            return
        lineas[h1 + 1:h1 + 1] = ["", linea]
    nuevo = "\n".join(lineas)
    if nuevo != txt:
        write_atomic(path, nuevo)


def migas(hoy: date) -> None:
    e = enlaces(hoy)
    for nota, extra in MIGAS.items():
        poner_migas(JARVIS / f"{nota}.md", MARCA + " · ".join(e[k] for k in ["Panel", *extra] if k in e))


if __name__ == "__main__":
    print("\n".join(barra(date.today())))
    migas(date.today())
