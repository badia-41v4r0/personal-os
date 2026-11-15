"""Importa entrenos del CSV que exporta Hevy a Jarvis/Areas/Gym.md.

Uso: python3 hevy_import.py workout_data.csv --desde 2026-09-14 [--dry-run] [--json]
Es idempotente: no duplica sesiones cuya fecha ya está en el registro (si Hevy trae dos entrenos el mismo día y uno
ya está, el otro se informa como «misma fecha» y no se añade solo).

Las funciones `leer`, `planificar` y `aplicar` las usa también el Control Center, que además guarda la trazabilidad
(id externo = hash de título + inicio, duración, filas originales) en su base de datos.
"""
import argparse
import csv
import hashlib
import io
import json
import sys
from collections import OrderedDict
from datetime import date, datetime
from pathlib import Path

from gym import GYM, RUTINA, sesiones

MESES = {m: i for i, m in enumerate(["ene", "feb", "mar", "abr", "may", "jun",
                                     "jul", "ago", "sep", "oct", "nov", "dic"], 1)}
MESES_EN = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun",
                                        "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
# Rutinas de Hevy -> sesión (Leg Day depende del día: lunes = Leg day, jueves = Lower)
NOMBRES = {"pechotriceps": "Push", "chest & triceps": "Push", "back & biceps": "Pull"}
COLUMNAS = {"title", "start_time", "exercise_title", "set_type", "weight_kg", "reps"}
TIPOS = {"normal", "warmup", "failure", "dropset"}


def fecha_hevy(s: str) -> datetime:
    """'30 sep 2026, 08:11' -> datetime (también acepta meses en inglés e ISO)."""
    s = s.strip()
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        pass
    dia, mes, resto = s.replace(",", "").split(" ", 2)
    anio, hora = resto.split()
    h, m = hora.split(":")[:2]
    k = mes.lower()[:3]
    return datetime(int(anio), MESES.get(k) or MESES_EN[k], int(dia), int(h), int(m))


def sesion_de(titulo: str, d: date) -> str:
    t = titulo.strip().lower()
    if t in NOMBRES:
        return NOMBRES[t]
    if t == "leg day":
        return "Lower" if d.weekday() == 3 else "Leg day"
    return RUTINA.get(d.weekday(), titulo.strip())


def num(x: str) -> str:
    return f"{float(x):g}" if x else ""


def serie(r: dict) -> str:
    peso, reps = num(r["weight_kg"]), r["reps"]
    if peso and reps:
        s = f"{peso}×{reps}"
    elif reps:
        s = f"PC×{reps}"  # peso corporal
    elif r.get("duration_seconds"):
        s = f"{r['duration_seconds']}s"
    else:
        s = f"{num(r.get('distance_km', ''))} km"
    if r["set_type"] == "warmup":
        s += " (cal.)"
    elif r["set_type"] == "failure":
        s += " (fallo)"
    elif r["set_type"] == "dropset":
        s += " (drop)"
    if r.get("rpe"):
        s += f" RPE {num(r['rpe'])}"
    return s


def external_id(titulo: str, inicio: str) -> str:
    return hashlib.sha1(f"{titulo.strip()}|{inicio.strip()}".encode()).hexdigest()[:16]


def leer(fuente, desde: date | None = None) -> dict:
    """fuente: ruta o texto del CSV. Devuelve {"entrenos": [...], "errores": [...], "avisos": [...]}.
    No inventa nada: una fila que no se entiende se informa y no se importa."""
    es_ruta = isinstance(fuente, Path) or (isinstance(fuente, str) and "\n" not in fuente and len(fuente) < 4096
                                           and Path(fuente).is_file())
    texto = Path(fuente).read_text(encoding="utf-8-sig") if es_ruta else str(fuente).lstrip("﻿")
    rd = csv.DictReader(io.StringIO(texto))
    faltan = COLUMNAS - set(rd.fieldnames or [])
    if faltan:
        return {"entrenos": [], "errores": [f"No parece un CSV de Hevy: faltan columnas {', '.join(sorted(faltan))}"], "avisos": []}
    entrenos: OrderedDict = OrderedDict()
    errores, avisos = [], []
    for n, r in enumerate(rd, 2):
        try:
            inicio = fecha_hevy(r["start_time"])
        except Exception:  # noqa: BLE001
            errores.append(f"Fila {n}: fecha de inicio ilegible «{r.get('start_time', '')}»")
            continue
        if desde and inicio.date() < desde:
            continue
        if not (r.get("exercise_title") or "").strip():
            errores.append(f"Fila {n}: sin nombre de ejercicio")
            continue
        try:
            peso = float(r["weight_kg"]) if r["weight_kg"] else None
            reps = int(float(r["reps"])) if r["reps"] else None
            if (peso is not None and peso < 0) or (reps is not None and reps < 0):
                raise ValueError
        except ValueError:
            errores.append(f"Fila {n}: peso o repeticiones no válidos ({r['weight_kg']!r}, {r['reps']!r})")
            continue
        if r["set_type"] not in TIPOS:
            avisos.append(f"Fila {n}: tipo de serie desconocido «{r['set_type']}»; se trata como normal")
            r = dict(r, set_type="normal")
        if reps is None and not r.get("duration_seconds") and not r.get("distance_km"):
            avisos.append(f"Fila {n}: {r['exercise_title']} sin reps, tiempo ni distancia; se omite")
            continue
        clave = (r["start_time"].strip(), r["title"].strip())
        w = entrenos.get(clave)
        if w is None:
            fin = None
            try:
                fin = fecha_hevy(r["end_time"]) if r.get("end_time") else None
            except Exception:  # noqa: BLE001
                avisos.append(f"Fila {n}: hora de fin ilegible; sin duración")
            dur = round((fin - inicio).total_seconds() / 60) if fin and fin > inicio else None
            w = entrenos[clave] = {
                "external_id": external_id(r["title"], r["start_time"]), "titulo": r["title"].strip(),
                "inicio": inicio.isoformat(timespec="minutes"), "fin": fin.isoformat(timespec="minutes") if fin else "",
                "fecha": inicio.date().isoformat(), "duracion_min": dur, "sesion": sesion_de(r["title"], inicio.date()),
                "ejercicios": OrderedDict(), "filas": []}
        ej = w["ejercicios"].setdefault(r["exercise_title"].strip(), {"series": [], "nota": (r.get("exercise_notes") or "").strip()})
        ej["series"].append(serie(r))
        w["filas"].append({k: r.get(k, "") for k in rd.fieldnames})
    out = sorted(entrenos.values(), key=lambda w: w["inicio"])
    for w in out:
        if not w["ejercicios"]:
            avisos.append(f"{w['fecha']} {w['titulo']}: sin ejercicios válidos")
    return {"entrenos": out, "errores": errores, "avisos": avisos}


def bloque(w: dict) -> str:
    lineas = [f"### {w['fecha']} · {w['sesion']}", f"_Hevy: {w['titulo']}_"]
    for nombre, e in w["ejercicios"].items():
        nota = f" ({e['nota']})" if e["nota"] else ""
        lineas.append(f"- {nombre}: {', '.join(e['series'])}{nota}")
    return "\n".join(lineas)


def planificar(entrenos: list[dict], existentes: set[str] | None = None) -> dict:
    """Qué se añadiría a Gym.md. Clave de idempotencia: la fecha (como siempre). Devuelve nuevos y ya registrados."""
    existentes = set(existentes if existentes is not None else {s["fecha"] for s in sesiones()})
    nuevos, ya, misma_fecha = [], [], []
    vistas: set[str] = set()
    for w in entrenos:
        if not w["ejercicios"]:
            continue
        if w["fecha"] in existentes:
            ya.append(w)
        elif w["fecha"] in vistas:
            misma_fecha.append(w)  # dos entrenos de Hevy el mismo día: no se fusionan solos
        else:
            nuevos.append(w)
            vistas.add(w["fecha"])
    return {"nuevos": nuevos, "ya_registrados": ya, "misma_fecha": misma_fecha}


def aplicar(nuevos: list[dict], path: Path = GYM) -> int:
    if not nuevos:
        return 0
    # Jarvis y Syncthing también escriben aquí: si el archivo cambia mientras se prepara, se rehace sobre lo nuevo
    tmp = path.with_suffix(".md.tmp")
    for _ in range(5):
        orig = path.read_text(encoding="utf-8")
        tmp.write_text(orig.rstrip() + "\n\n" + "\n\n".join(bloque(w) for w in nuevos) + "\n", encoding="utf-8")
        if path.read_text(encoding="utf-8") == orig:
            tmp.replace(path)
            return len(nuevos)
    tmp.unlink(missing_ok=True)
    raise RuntimeError("Gym.md cambia sin parar: no se ha importado nada")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--desde", required=True, help="AAAA-MM-DD")
    ap.add_argument("--dry-run", action="store_true", help="solo enseña qué haría")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    r = leer(args.csv, date.fromisoformat(args.desde))
    p = planificar(r["entrenos"])
    if args.json:
        print(json.dumps({"nuevos": [w["fecha"] + " " + w["sesion"] for w in p["nuevos"]],
                          "ya_registrados": len(p["ya_registrados"]), "misma_fecha": [w["fecha"] + " " + w["titulo"] for w in p["misma_fecha"]],
                          "errores": r["errores"], "avisos": r["avisos"]}, ensure_ascii=False))
        if args.dry_run:
            return
    for e in r["errores"] + r["avisos"]:
        print("·", e)
    if args.dry_run:
        print(f"Se añadirían {len(p['nuevos'])} sesiones.")
        return
    if not p["nuevos"]:
        print("Nada nuevo que importar.")
        return
    if (Path(__file__).resolve().parent.parent / "data/control-center/fuente-gym-bd").exists():
        sys.exit("Los entrenos mandan en la base del panel desde el 07/11: sube el CSV en Entrenamiento → History. "
                 "Escribir aquí en Gym.md se descartaría.")
    n = aplicar(p["nuevos"])
    print(f"Importadas {n} sesiones desde {args.desde}.")


if __name__ == "__main__":
    main()
