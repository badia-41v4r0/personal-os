"""Gym: sesión de hoy y la última sesión comparable registrada en Jarvis/Areas/Gym.md.

Formato del registro en Gym.md:
    ### 2026-09-28 · Leg day
    - Sentadilla: 4×8 @ 80 kg
"""
import re
from datetime import date, datetime

from lib import JARVIS

GYM = JARVIS / "Areas" / "Gym.md"
RUTINA = {0: "Leg day", 1: "Push", 2: "Pull", 3: "Lower", 4: "Upper"}
SESION = re.compile(r"^###\s*(\d{4}-\d{2}-\d{2})\s*·\s*(.+?)\s*$")


def sesiones() -> list[dict]:
    if not GYM.exists():
        return []
    out, actual = [], None
    for line in GYM.read_text(encoding="utf-8").splitlines():
        m = SESION.match(line)
        if m:
            actual = {"fecha": m[1], "sesion": m[2], "lineas": []}
            out.append(actual)
        elif line.startswith("#"):
            actual = None
        elif actual is not None and line.strip():
            actual["lineas"].append(line.strip())
    return out


def recoger(hoy: date) -> dict:
    sesion = RUTINA.get(hoy.weekday())
    if not sesion:
        return {"sesion": None, "anterior": None}
    # Cada sesión se compara con la anterior del mismo nombre (lunes con lunes, jueves con jueves)
    previas = [s for s in sesiones() if s["fecha"] < hoy.isoformat() and s["sesion"].lower() == sesion.lower()]
    anterior = max(previas, key=lambda s: s["fecha"]) if previas else None
    return {"sesion": sesion, "anterior": anterior}


if __name__ == "__main__":
    import json, sys
    d = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else datetime.now().date()
    print(json.dumps(recoger(d), ensure_ascii=False, indent=1))
