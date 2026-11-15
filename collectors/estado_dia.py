"""Estado del día a partir del Panel (sin IA). Lo usan el recordatorio de las 22:30 y el briefing.

Uso:
  python3 estado_dia.py cerrado AAAA-MM-DD   -> exit 0 si existe Diario/AAAA-MM-DD.md
  python3 estado_dia.py recordatorio          -> imprime el mensaje de las 22:30
"""
import re
import sys

from lib import JARVIS

PANEL = JARVIS / "Panel.md"
DIARIO = JARVIS / "Diario"


def cerrado(fecha: str) -> bool:
    return (DIARIO / f"{fecha}.md").exists()


def recordatorio() -> str:
    txt = PANEL.read_text(encoding="utf-8")
    secciones = re.split(r"^> \[!jarvis-\w+\]-? ", txt, flags=re.M)
    estudio, tareas, gym = [0, 0], [0, 0], None
    for sec in secciones:
        titulo = sec.splitlines()[0] if sec else ""
        marcas = re.findall(r"^> - \[( |x)\]", sec, re.M)
        hechas = sum(1 for m in marcas if m == "x")
        if titulo.startswith("📚"):
            estudio = [hechas, len(marcas)]
        elif titulo.startswith("🏋️"):
            gym = (hechas > 0) if marcas else None
        elif titulo.startswith(("💼", "🏢", "🏟️", "🙋", "🎓")):
            tareas[0] += hechas
            tareas[1] += len(marcas)
    lineas = ["🌙 ¿Cómo ha ido el día? Cuéntamelo en el chat de Inicio del panel y lo anoto (estudio, tareas, gym, lo que quieras)."]
    estado = []
    if estudio[1]:
        estado.append(f"📚 {estudio[0]}/{estudio[1]} bloques")
    if tareas[1]:
        estado.append(f"✅ {tareas[0]}/{tareas[1]} tareas")
    if gym is not None:
        estado.append("🏋️ entreno ✔️" if gym else "🏋️ entreno sin marcar")
    if estado:
        lineas.append("Según el Panel: " + " · ".join(estado))
    lineas.append("Si no me lo cuentas, mañana a las 7:00 cierro el día solo con lo marcado.")
    return "\n".join(lineas)


if __name__ == "__main__":
    if sys.argv[1] == "cerrado":
        sys.exit(0 if cerrado(sys.argv[2]) else 1)
    print(recordatorio())
