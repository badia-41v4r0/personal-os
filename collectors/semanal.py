"""Resumen semanal sin IA (Sistema/semana.md) para las revisiones del domingo.

- Estudio: bloques planificados vs marcados como hechos en el Panel, por asignatura.
- Gym: top set de cada ejercicio frente a la misma sesión de la semana anterior (tendencia por fuerza estimada).

Uso: python3 semanal.py [AAAA-MM-DD]   (cualquier día de la semana a resumir; por defecto, hoy)
"""
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

import gym
import uni
from lib import SISTEMA, fecha_corta, load_json, plain, write_atomic

SALIDA = SISTEMA / "semana.md"
SERIE = re.compile(r"(PC|[\d.]+)×(\d+)")


def series(linea: str) -> tuple[str, list[tuple[float, int]]]:
    """Series efectivas: '- Prensa: 40×10 (cal.), 140×10, 130×10 (nota)' -> ('Prensa', [(140, 10), (130, 10)]).
    Quita las marcadas como calentamiento y, si no hay marcas, todo lo anterior al top set (aproximación)."""
    nombre, _, resto = linea.lstrip("- ").partition(":")
    out = []
    for trozo in resto.split(","):
        m = SERIE.search(trozo)
        if m and "(cal.)" not in trozo:
            out.append((0.0 if m[1] == "PC" else float(m[1]), int(m[2])))
    if out:
        top = max(range(len(out)), key=lambda i: (out[i][0], out[i][1]))
        out = out[top:]
    return nombre.strip(), out


def bloques_del_dia(d: date) -> list[str]:
    return uni.recoger(d, dias=0)["bloques"] if d.weekday() < 5 else []


def e1rm(p: float, r: int) -> float:
    """Fuerza estimada (Epley); con peso corporal, las reps."""
    return r if p == 0 else p * (1 + r / 30)


def fmt(p: float, r: int) -> str:
    return f"PC×{r}" if p == 0 else f"{p:g}×{r}"


def resumen_ejercicio(s: list[tuple[float, int]]) -> str:
    if not s:
        return "sin series"
    top, back = s[0], s[1:]
    txt = f"top {fmt(*top)}"
    if back:
        txt += " · back-offs " + ", ".join(fmt(*b) for b in back)
        if top[0] and any(b[0] < 0.7 * top[0] or b[0] > top[0] for b in back):
            txt += " ⚠️ back-off incoherente"
    return txt


def main(ref: date):
    lunes = ref - timedelta(days=ref.weekday())
    hechos = load_json(SISTEMA / "hechos.json", {})
    S = [f"# Semana del {fecha_corta(lunes)} al {fecha_corta(lunes + timedelta(days=6))}", "",
         "## Estudio: planificado vs hecho"]

    por_asig = defaultdict(lambda: [0, 0])
    pendientes = []
    for i in range(5):
        d = lunes + timedelta(days=i)
        for b in bloques_del_dia(d):
            asig = b.split(" · ")[0]
            por_asig[asig][0] += 1
            if f"estudio|{d.isoformat()}|{b}" in hechos:
                por_asig[asig][1] += 1
            elif d <= ref:
                pendientes.append(f"- {fecha_corta(d)}: {b}")
    total = [sum(v[0] for v in por_asig.values()), sum(v[1] for v in por_asig.values())]
    S.append(f"Total: {total[1]}/{total[0]} bloques marcados.")
    S += [f"- {a}: {h}/{p}" for a, (p, h) in sorted(por_asig.items())]
    if pendientes:
        S += ["", "Bloques no marcados (se replanifican el domingo a las 21:00):"] + pendientes

    prox = uni.recoger(ref, dias=14)["entregas"]
    S += ["", "## Entregas en los próximos 14 días"]
    S += [f"- {e['fecha']}: {e['texto']}" for e in prox if not e["hecho"]] or ["- Ninguna"]

    S += ["", "## Gym: esta semana vs la anterior"]
    todas = gym.sesiones()
    semana = [s for s in todas if lunes.isoformat() <= s["fecha"] <= (lunes + timedelta(days=6)).isoformat()]
    hechas = {s["sesion"].lower() for s in semana}
    faltan = [v for k, v in gym.RUTINA.items() if lunes + timedelta(days=k) <= ref and v.lower() not in hechas]
    if faltan:
        S.append(f"Sesiones sin registrar: {', '.join(faltan)}")
    for s in semana:
        previas = [p for p in todas if p["fecha"] < s["fecha"] and p["sesion"].lower() == s["sesion"].lower()]
        ant = max(previas, key=lambda p: p["fecha"]) if previas else None
        S += ["", f"### {s['sesion']} ({s['fecha']})" + (f" vs {ant['fecha']}" if ant else " (sin referencia)")]
        antes = dict(series(l) for l in ant["lineas"] if l.startswith("- ")) if ant else {}
        for l in s["lineas"]:
            if not l.startswith("- "):
                continue
            nombre, ss = series(l)
            linea = f"- {nombre}: {resumen_ejercicio(ss)}"
            if nombre in antes:
                a = antes.pop(nombre)
                va, vn = (e1rm(*a[0]) if a else 0), (e1rm(*ss[0]) if ss else 0)
                tendencia = "↑" if vn > va * 1.01 else "↓" if vn < va * 0.99 else "="
                linea += f" | antes: {resumen_ejercicio(a)} | {tendencia}"
            else:
                linea += " | nuevo"
            S.append(linea)
        for nombre in antes:
            S.append(f"- {nombre}: no se hizo esta vez")

    write_atomic(SALIDA, "\n".join(S) + "\n")
    print(f"Resumen semanal generado: {SALIDA}")


if __name__ == "__main__":
    main(date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else datetime.now().date())
