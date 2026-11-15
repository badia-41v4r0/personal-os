"""Planificador de estudio: reparte paquetes de trabajo en bloques según tu disponibilidad (config estudios.json).

Escribe la tabla "Plan diario" de cada nota semanal (Uni/Planificación/Semanas/) desde `--desde`.
Si ya hay bloques marcados como hechos en el Panel (Sistema/hechos.json), los descuenta:
así se puede recalcular el plan cuando haya retrasos sin perder lo avanzado.

Uso: python3 planificador.py [--desde AAAA-MM-DD] [--simular]
"""
import argparse
import re
from collections import Counter
from datetime import date, datetime, timedelta

import ajustes
from lib import SISTEMA, VAULT, fecha_corta, load_json, write_atomic

SEMANAS = VAULT / "Uni" / "Planificación" / "Semanas"
DIAS = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")
D = date.fromisoformat


def _cargar():
    """Asignaturas, paquetes, horarios y descansos de la configuración de estudios (data/config/estudios.json).

    asignaturas: [{"codigo": "FP", "nombre": "…", "paquetes": [{"tarea": "…", "inicio": "AAAA-MM-DD", "limite": "AAAA-MM-DD", "bloques": 2}]}]
    disponibilidad: {"lunes": ["10:30–12:30", …], …, "domingo": []}  (cada franja es un bloque)
    descansos: ["AAAA-MM-DD", …];  fin: "AAAA-MM-DD" (último día del semestre)
    """
    c = ajustes.leer("estudios")
    asig, paquetes = {}, []
    for a in c.get("asignaturas") or []:
        cod = str(a.get("codigo") or "").strip()
        if not cod:
            continue
        asig[cod] = str(a.get("nombre") or cod)
        for q in a.get("paquetes") or []:
            try:
                paquetes.append((cod, str(q["tarea"]), str(q["inicio"]), str(q["limite"]), int(q.get("bloques", 1))))
            except (KeyError, ValueError, TypeError):
                continue
    disp = {d: [str(h) for h in (c.get("disponibilidad") or {}).get(d) or []] for d in DIAS}
    descanso = set()
    for x in c.get("descansos") or []:
        try:
            descanso.add(D(str(x)))
        except ValueError:
            pass
    fines = [D(l) for *_, l, _n in paquetes]
    try:
        fin = D(str(c["fin"]))
    except (KeyError, ValueError):
        fin = max(fines) if fines else date.today()
    return asig, paquetes, disp, descanso, fin


def recargar() -> None:
    """Vuelve a leer la configuración (el backend la cambia sin reiniciar)."""
    global ASIG, PAQUETES, DISPONIBILIDAD, DESCANSO, FIN, HORAS, HORAS_SAB
    ASIG, PAQUETES, DISPONIBILIDAD, DESCANSO, FIN = _cargar()
    # Franjas de un día laborable tipo (cabecera de la tabla) y del sábado
    HORAS = next((DISPONIBILIDAD[d] for d in DIAS[:5] if DISPONIBILIDAD[d]), [])
    HORAS_SAB = DISPONIBILIDAD["sabado"]


recargar()


def horas(d: date) -> list[str]:
    return [] if d in DESCANSO else DISPONIBILIDAD[DIAS[d.weekday()]]


def bloques_dia(d: date) -> int:
    return len(horas(d))


def laborables(desde: date, hasta: date):
    d = desde
    while d <= hasta:
        if bloques_dia(d):
            yield d
        d += timedelta(days=1)


def etiqueta(asig: str, tarea: str) -> str:
    return f"{asig} · {tarea}"


def hechos_por_paquete() -> Counter:
    """Bloques ya marcados en el Panel, por etiqueta de paquete."""
    c = Counter()
    for clave in load_json(SISTEMA / "hechos.json", {}):
        if clave.startswith("estudio|"):
            texto = clave.split("|", 2)[2]
            c[re.sub(r"\s*\(\d+/\d+\)$", "", texto)] += 1
    return c


def planificar(desde: date):
    hechos = hechos_por_paquete()
    pend = []
    for asig, tarea, ini, lim, n in PAQUETES:
        et = etiqueta(asig, tarea)
        restantes = n - hechos.get(et, 0)
        if restantes > 0:
            pend.append({"asig": asig, "et": et, "ini": max(D(ini), desde), "lim": D(lim),
                         "total": n, "hechos": n - restantes, "rest": restantes})

    plan, avisos = {}, []
    for dia in laborables(desde, FIN):
        usados = Counter()
        bloques = []
        for _ in range(bloques_dia(dia)):
            cand = [p for p in pend if p["rest"] > 0 and p["ini"] <= dia]
            if not cand:
                bloques.append(None)
                continue

            def urgencia(p):
                dias = sum(1 for _ in laborables(dia, max(p["lim"], dia)))
                return p["rest"] / max(dias, 1)

            def permitido(p):  # máx. 2 bloques/día por asignatura salvo entrega inminente
                return usados[p["asig"]] < 2 or (p["lim"] - dia).days <= 2

            cand = [p for p in cand if permitido(p)] or cand
            # EDF (primero lo que vence antes): óptimo para cumplir plazos; la urgencia desempata
            p = min(cand, key=lambda p: (p["lim"], -urgencia(p)))
            p["rest"] -= 1
            p["hechos"] += 1
            usados[p["asig"]] += 1
            bloques.append((f"{p['et']} ({p['hechos']}/{p['total']})", p["asig"]))
            if p["rest"] == 0 and dia > p["lim"]:
                avisos.append(f"{p['et']}: termina el {fecha_corta(dia)}, después del límite ({fecha_corta(p['lim'])})")
        plan[dia] = bloques

    for p in pend:
        if p["rest"] > 0:
            avisos.append(f"{p['et']}: quedan {p['rest']} bloques sin hueco")
    return plan, avisos


def celda(item) -> str:
    if not item:
        return "Libre / recuperar"
    texto, asig = item
    return texto.replace(f"{asig} · ", f"[[Uni/Asignaturas/{ASIG[asig]}\\|{asig}]] · ", 1)


def escribir(plan: dict, desde: date):
    cab = "| Día | " + " | ".join(HORAS) + " |"
    sep = "|---|" + "---|" * len(HORAS)
    for f in sorted(SEMANAS.glob("*.md")):
        txt = f.read_text(encoding="utf-8")
        ini = re.search(r"^inicio:\s*(\d{4}-\d{2}-\d{2})", txt, re.M)
        if not ini:
            continue
        lunes = D(ini[1])
        if lunes + timedelta(days=6) < desde:
            continue
        m = re.search(r"^## 🗓️ Plan diario.*?(?=^## )", txt, re.M | re.S)
        if not m:
            continue
        viejas = {int(x[1]): x[0] for x in re.finditer(r"^\|\s*\w+\s+(\d{2})/\d{2}\s*\|.*$", m[0], re.M)}
        filas = []
        for i in range(7):
            d = lunes + timedelta(days=i)
            nombre = f"{['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo'][i]} {d:%d/%m}"
            if d < desde:
                filas.append(viejas.get(d.day, f"| {nombre} | — | — | — |"))
            elif i == 5 and d in plan:
                filas.append(f"| {nombre} | " + " | ".join(celda(x) for x in plan[d]) + " | — |")
            elif i == 5:
                filas.append(f"| {nombre} | Libre | — | — |")
            elif i == 6:
                filas.append(f"| {nombre} | Repaso semanal con Jarvis (1 h) | — | — |")
            elif d in DESCANSO:
                filas.append(f"| {nombre} | Descanso | — | — |")
            elif d in plan:
                filas.append(f"| {nombre} | " + " | ".join(celda(x) for x in plan[d]) + " |")
            else:
                filas.append(f"| {nombre} | — | — | — |")
        nuevo = ("## 🗓️ Plan diario (3 bloques de 2 h: 10:30, 12:30 y 16:00)\n\n"
                 "> Generado por el planificador de Jarvis. Si te retrasas, pídele que lo recalcule.\n\n"
                 + "\n".join([cab, sep] + filas) + "\n"
                 + (f"\n> Sábado de estudio: {', '.join(horas(lunes + timedelta(days=5)))}.\n" if bloques_dia(lunes + timedelta(days=5)) else "")
                 + "\n")
        write_atomic(f, txt.replace(m[0], nuevo))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", default=datetime.now().date().isoformat())
    ap.add_argument("--simular", action="store_true")
    a = ap.parse_args()
    desde = D(a.desde)
    plan, avisos = planificar(desde)
    total = sum(n for *_, n in PAQUETES)
    usados = sum(1 for b in plan.values() for x in b if x)
    print(f"Paquetes: {total} bloques · capacidad: {len(plan) * len(HORAS)} · asignados: {usados}")
    for asig in ASIG:
        print(f"  {asig}: {sum(n for s, *_, n in PAQUETES if s == asig)} bloques")
    print("Avisos:" if avisos else "Sin avisos: todo cabe antes de su límite.")
    for x in avisos:
        print("  ⚠️", x)
    if not a.simular:
        escribir(plan, desde)
        print("Notas semanales actualizadas.")
        if avisos:  # que el usuario se entere sin tener que mirar nada
            import subprocess
            from lib import ROOT
            msg = "⚠️ Plan de estudio recalculado, pero hay cosas que no caben antes de su entrega:\n" + "\n".join(f"• {x}" for x in avisos)
            subprocess.run([str(ROOT / "bin" / "telegram-send.sh"), msg], check=False)
