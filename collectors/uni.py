"""Uni: bloques de estudio de hoy, objetivos pendientes y entregas, leídos de las notas semanales."""
import re
from datetime import date, datetime, timedelta

from lib import CHECKBOX, VAULT, plain, write_atomic

SEMANAS = VAULT / "Uni" / "Planificación" / "Semanas"
FECHA_ENTREGA = re.compile(r"(\d{2})/(\d{2})/(\d{4})(?:\s+(\d{1,2}:\d{2}))?")
FILA_DIA = re.compile(r"^\|\s*\w+\s+(\d{2})/(\d{2})\s*\|")


def _semanas():
    """[(inicio, fin, texto)] a partir del frontmatter de cada nota semanal."""
    out = []
    for f in sorted(SEMANAS.glob("*.md")):
        txt = f.read_text(encoding="utf-8")
        ini = re.search(r"^inicio:\s*(\d{4}-\d{2}-\d{2})", txt, re.M)
        fin = re.search(r"^fin:\s*(\d{4}-\d{2}-\d{2})", txt, re.M)
        if ini and fin:
            out.append((date.fromisoformat(ini[1]), date.fromisoformat(fin[1]), txt))
    return out


def _seccion(txt: str, titulo: str) -> list[str]:
    """Líneas de la sección cuyo encabezado contiene `titulo` (hasta el siguiente encabezado ##)."""
    lines, dentro = [], False
    for line in txt.splitlines():
        if line.startswith("#"):
            if dentro and line.startswith("## "):
                break
            if titulo in line:
                dentro = True
                continue
        if dentro:
            lines.append(line)
    return lines


def recoger(hoy: date, dias: int = 7) -> dict:
    semanas = _semanas()
    bloques, objetivos, entregas, eventos = [], [], [], []

    for ini, fin, txt in semanas:
        # Plan diario de hoy
        if ini <= hoy <= fin:
            for line in _seccion(txt, "Plan diario"):
                m = FILA_DIA.match(line)
                if m and int(m[1]) == hoy.day and int(m[2]) == hoy.month:
                    celdas = line.replace("\\|", "|").split(" | ")[1:]  # "\|" va dentro de los enlaces
                    celdas = [plain(c.strip(" |")) for c in celdas]
                    bloques = [c for c in celdas if c not in ("", "—", "Libre")]
            for line in _seccion(txt, "Objetivos"):
                c = CHECKBOX.match(line)
                if c:
                    asignatura, _, detalle = plain(c[2]).partition(":")
                    objetivos.append({"asignatura": asignatura.strip(), "detalle": detalle.strip(),
                                      "hecho": c[1] != " "})

        # Entregas y eventos en la ventana [hoy, hoy+dias]
        if fin < hoy or ini > hoy + timedelta(days=dias):
            continue
        for line in _seccion(txt, "Entregas"):
            c = CHECKBOX.match(line)
            f = FECHA_ENTREGA.search(line) if c else None
            if not f:
                continue
            d = date(int(f[3]), int(f[2]), int(f[1]))
            if hoy <= d <= hoy + timedelta(days=dias):
                _, _, desc = plain(c[2]).partition("·")
                entregas.append({"fecha": d.isoformat(), "hora": f[4] or "23:59",
                                 "texto": desc.strip(), "hecho": c[1] != " "})
        for line in _seccion(txt, "Eventos"):
            f = FECHA_ENTREGA.search(line)
            if not f:
                continue
            d = date(int(f[3]), int(f[2]), int(f[1]))
            if hoy <= d <= hoy + timedelta(days=dias):
                _, _, desc = plain(line.lstrip("- ")).partition("·")
                eventos.append({"fecha": d.isoformat(), "texto": desc.strip()})

    # Objetivos relevantes hoy: los pendientes de las asignaturas de los bloques
    obj_hoy = [o for o in objetivos if not o["hecho"] and any(b in o["asignatura"] or o["asignatura"] in b for b in bloques)]
    entregas.sort(key=lambda e: (e["fecha"], e["hora"]))
    eventos.sort(key=lambda e: e["fecha"])
    return {"bloques": bloques, "objetivos": obj_hoy, "entregas": entregas, "eventos": eventos}


def objetivos_semana(hoy: date) -> list[dict]:
    """Todos los objetivos de la semana en curso, hechos o no."""
    out = []
    for ini, fin, txt in _semanas():
        if ini <= hoy <= fin:
            for line in _seccion(txt, "Objetivos"):
                c = CHECKBOX.match(line)
                if c:
                    out.append({"texto": plain(c[2]), "hecho": c[1] != " "})
    return out


def _marcar(titulo: str, coincide, hecho: bool) -> int:
    """Cambia en las notas semanales la casilla de esa sección que cumpla `coincide(línea, casilla)`."""
    n = 0
    for f in sorted(SEMANAS.glob("*.md")):
        lines, dentro, cambios = f.read_text(encoding="utf-8").split("\n"), False, 0
        for i, line in enumerate(lines):
            if line.startswith("#"):
                dentro = line.startswith("## ") and titulo in line
            c = CHECKBOX.match(line) if dentro else None
            if c and (c[1] != " ") != hecho and coincide(line, c):
                lines[i] = line.replace(f"[{c[1]}]", "[x]" if hecho else "[ ]", 1)
                cambios += 1
        if cambios:
            write_atomic(f, "\n".join(lines))
            n += cambios
    return n


def marcar_objetivo(texto: str, hecho: bool) -> int:
    return _marcar("Objetivos", lambda _, c: plain(c[2]) == texto, hecho)


def marcar_entrega(fecha: str, texto: str, hecho: bool) -> int:
    def coincide(line, c):
        f = FECHA_ENTREGA.search(line)
        return bool(f) and f"{f[3]}-{f[2]}-{f[1]}" == fecha and plain(c[2]).partition("·")[2].strip() == texto
    return _marcar("Entregas", coincide, hecho)


if __name__ == "__main__":
    import json, sys
    d = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else datetime.now().date()
    print(json.dumps(recoger(d), ensure_ascii=False, indent=1))
