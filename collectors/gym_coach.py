"""Motor del entrenador (Gym 2.0). Determinista, solo librería estándar y probado (control-center/backend/tests).

Lo usan el Control Center, el Coach (servidor MCP `gym`) y Jarvis por línea de comandos. Los datos de los entrenos
salen de Areas/Gym.md (gym_stats.cargar); la planificación, los ajustes y las sensaciones los pasa quien llama
(el panel los guarda en su SQLite). Aquí no se lee ni se escribe nada más.

Cada resultado indica de qué tipo es cada dato (ver `NIVELES`): registrado, calculado, estimación, inferencia o
recomendación. Fórmulas y criterios: control-center/docs/gym.md.

CLI para Jarvis:
  python3 gym_coach.py siguiente [--json]          próxima sesión: ejercicios, series, reps, peso objetivo y por qué
  python3 gym_coach.py objetivo "press inclinado"  objetivo del próximo entreno de un ejercicio
  python3 gym_coach.py estancados                  estancamientos y retrocesos (con confianza y evidencia)
  python3 gym_coach.py records [--dias 30]         récords personales (reales) y e1RM (estimado)
  python3 gym_coach.py musculos [--semanas 4]      series directas e indirectas, frecuencia y tendencia
  python3 gym_coach.py recuperacion                carga reciente por músculo (orientativo)
  python3 gym_coach.py analisis                    observaciones con su evidencia
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gym_stats as gs  # noqa: E402

NIVELES = {
    "registrado": "Dato registrado en Hevy/Gym.md",
    "calculado": "Cálculo exacto sobre datos registrados",
    "estimacion": "Estimación con una fórmula (p. ej. e1RM de Epley)",
    "inferencia": "Deducción del motor a partir de patrones; puede fallar",
    "recomendacion": "Propuesta del entrenador; no es un dato",
}
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
RUTINA_DEFECTO = dict(gs.RUTINA)  # 0=lunes … 4=viernes

# ---------- categorías y configuración por ejercicio ----------

AISLAMIENTO = ("extension", "curl", "elevacion", "aperturas", "cruzados", "abduccion", "aduccion", "pantorrilla",
               "gemelo", "vuelos", "pullover", "jalon de triceps", "rotacion", "face pull", "encogimiento", "patada")
COMPUESTO = ("sentadilla", "hack", "press de piernas", "prensa", "press de banca", "press de pecho", "press de hombros",
             "press militar", "remo", "jalon al pecho", "dominada", "peso muerto", "hip thrust", "zancada", "fondos")
PESO_CORPORAL = ("dominada", "fondos", "flexiones")

DEFAULTS = {
    # Rangos del método del usuario (Sistema/gym.md): compuestos 6–10, aislamiento 10–15
    "compuesto": {"rep_min": 6, "rep_max": 10, "series": 3, "descanso_s": 180},
    "maquina": {"rep_min": 6, "rep_max": 10, "series": 3, "descanso_s": 120},
    "aislamiento": {"rep_min": 10, "rep_max": 15, "series": 3, "descanso_s": 75},
    "peso_corporal": {"rep_min": 5, "rep_max": 10, "series": 3, "descanso_s": 120},
    "cardio": {"rep_min": 0, "rep_max": 0, "series": 0, "descanso_s": 0},
}
INCREMENTO = {"barra": 2.5, "mancuerna": 2.0, "maquina": 5.0, "polea": 2.5, "peso_corporal": 2.5, "otro": 2.5}
METODOS = {
    "top_set": "Top set al fallo (RIR 0) + back-offs −10 % a RIR 1–2; doble progresión en el top set",
    "doble_progresion": "Series rectas con el mismo peso; +1 rep por serie hasta el tope del rango y entonces sube peso",
}
METODO_DEFECTO = "top_set"  # el del usuario (Gym.md → Perfil)

ZONAS = {  # molestia → músculos cuyo patrón no se fuerza
    "hombro": ["hombros", "pecho"], "codo": ["biceps", "triceps"], "muneca": ["biceps", "triceps", "pecho"],
    "rodilla": ["cuadriceps", "isquiotibiales"], "lumbar": ["lumbar", "isquiotibiales", "gluteos"],
    "espalda baja": ["lumbar", "isquiotibiales", "gluteos"], "cadera": ["gluteos", "aductores"],
    "cuello": ["espalda", "hombros"], "tobillo": ["gemelos"], "pecho": ["pecho"], "espalda": ["espalda"],
}


def categoria(nombre: str, series: list | None = None, tipo: str = "fuerza") -> str:
    n = gs.norm(nombre)
    if tipo == "cardio":
        return "cardio"
    if any(k in n for k in PESO_CORPORAL) or (series and all(s.peso is None for s in series)):
        return "peso_corporal"
    if any(k in n for k in AISLAMIENTO):
        return "aislamiento"
    if any(k in n for k in COMPUESTO):
        if "maquina" in n or "cable" in n or "hack" in n or "press de piernas" in n or "prensa" in n or "jalon" in n:
            return "maquina"
        return "compuesto"
    return "aislamiento" if "maquina" in n or "cable" in n else "compuesto"


def equipo(nombre: str) -> str:
    n = gs.norm(nombre)
    if any(k in n for k in PESO_CORPORAL):
        return "peso_corporal"
    for k, v in (("mancuerna", "mancuerna"), ("barra", "barra"), ("maquina", "maquina"), ("cable", "polea"),
                 ("polea", "polea"), ("hack", "maquina"), ("press de piernas", "maquina")):
        if k in n:
            return v
    return "otro"


def paso_observado(pesos: list[float]) -> float | None:
    """Incremento más frecuente entre los pesos distintos que ha usado (así respeta las placas de su gym)."""
    ws = sorted({round(p, 2) for p in pesos if p})
    difs = [round(b - a, 2) for a, b in zip(ws, ws[1:]) if 1.0 <= b - a <= 20]
    if len(difs) < 2:
        return None
    c = Counter(difs)
    top = max(c.values())
    return min(d for d, n in c.items() if n == top)


def config(eid: str, nombre: str, apariciones: list | None = None, ajustes: dict | None = None) -> dict:
    """Configuración efectiva: ajustes del panel > valores por categoría; incremento: ajuste > observado > equipo."""
    series = [s for _, e in (apariciones or []) for s in e.series]
    tipo = apariciones[-1][1].tipo if apariciones else "fuerza"
    cat = categoria(nombre, series or None, tipo)
    eq = equipo(nombre)
    base = dict(DEFAULTS[cat])
    obs = paso_observado([s.peso for s in series if s.peso])
    cfg = {"ejercicio_id": eid, "nombre": nombre, "categoria": cat, "equipo": eq, "metodo": METODO_DEFECTO,
           "incremento_kg": obs or INCREMENTO[eq], "incremento_origen": "observado" if obs else "equipo",
           "rir_top": 0, "rir_backoff": "1–2", **base, "origen": "categoria"}
    if cat == "peso_corporal":
        cfg["metodo"] = "top_set"
    for k, v in (ajustes or {}).items():
        if v is not None and k in ("rep_min", "rep_max", "series", "descanso_s", "metodo", "incremento_kg", "categoria",
                                   "rir_top", "rir_backoff", "notas"):
            cfg[k] = v
            cfg["origen"] = "ajuste"
            if k == "incremento_kg":
                cfg["incremento_origen"] = "ajuste"
    if cfg["rep_min"] > cfg["rep_max"]:
        cfg["rep_min"], cfg["rep_max"] = cfg["rep_max"], cfg["rep_min"]
    return cfg


def redondear(peso: float, paso: float, modo: str = "cerca") -> float:
    if not paso:
        return round(peso, 2)
    f = {"cerca": round, "abajo": math.floor, "arriba": math.ceil}[modo]
    return round(f(peso / paso + (1e-9 if modo != "cerca" else 0)) * paso, 2)


# ---------- series: top set, back-offs y aproximaciones ----------

def roles(series: list) -> list[str]:
    """Papel de cada serie según el método (top set + back-offs):
    calentamiento (marcado en Hevy) · aproximacion (inferida: sin marcar, antes del top set y más ligera) ·
    intento (inferido: ≤2 reps y más pesada que el top set) · top · backoff."""
    out = ["calentamiento" if s.calentamiento else "" for s in series]
    ef = [i for i, s in enumerate(series) if not s.calentamiento]
    if not ef:
        return out
    if all(series[i].peso is None for i in ef):  # peso corporal: la primera serie efectiva es el top set
        for n, i in enumerate(ef):
            out[i] = "top" if n == 0 else "backoff"
        return out
    cands = [i for i in ef if series[i].peso and series[i].reps >= 3] or [i for i in ef if series[i].peso]
    if not cands:
        for i in ef:
            out[i] = "backoff"
        return out
    wmax = max(series[i].peso for i in cands)
    top = next(i for i in cands if series[i].peso == wmax)
    for i in ef:
        s = series[i]
        if i == top:
            out[i] = "top"
        elif s.peso and s.peso > wmax and s.reps <= 2:
            out[i] = "intento"
        elif i < top and (s.peso or 0) < wmax:
            out[i] = "aproximacion"
        else:
            out[i] = "backoff"
    return out


def _serie_d(s, rol: str) -> dict:
    return {"peso": s.peso, "reps": s.reps, "rol": rol, "e1rm": s.e1rm, "volumen": s.volumen, "fallo": s.fallo,
            "rpe": s.rpe, "calentamiento": s.calentamiento, "drop": s.drop,
            "rol_nivel": "registrado" if rol == "calentamiento" else "inferencia"}


def apariciones(sesiones: list, eid: str) -> list[tuple]:
    return [(s, e) for s in sesiones for e in s.ejercicios if e.id == eid and e.series]


def historial(sesiones: list, eid: str) -> list[dict]:
    out = []
    for s, e in apariciones(sesiones, eid):
        rs = roles(e.series)
        series = [_serie_d(x, r) for x, r in zip(e.series, rs)]
        top = next((d for d in series if d["rol"] == "top"), None)
        avisos = []
        if top and top["peso"]:
            bos = [d for d in series if d["rol"] == "backoff" and d["peso"]]
            for a, b in zip(bos, bos[1:]):
                if b["peso"] > a["peso"]:
                    avisos.append(f"back-off que sube ({a['peso']:g}→{b['peso']:g} kg)")
            for b in bos:
                if b["peso"] < 0.7 * top["peso"]:
                    avisos.append(f"back-off de {b['peso']:g} kg < 70 % del top set ({top['peso']:g} kg)")
            avisos = list(dict.fromkeys(avisos))  # sin repetir el mismo aviso
        out.append({"fecha": s.fecha, "sesion": s.nombre, "sesion_id": s.id, "nombre": e.nombre, "series": series,
                    "top": top, "backoffs": [d for d in series if d["rol"] == "backoff"],
                    "series_efectivas": len(e.efectivas),
                    "series_trabajo": sum(1 for d in series if d["rol"] in ("top", "backoff", "intento")),
                    "volumen": e.volumen, "peso_max": max((x.peso for x in e.efectivas if x.peso), default=None),
                    "reps_total": sum(x.reps for x in e.efectivas), "notas": e.notas, "avisos": avisos})
    return out


def rendimiento(top: dict | None) -> float | None:
    """Comparable entre sesiones: e1RM del top set (estimación) o reps si es peso corporal."""
    if not top:
        return None
    if top["peso"] is None:
        return float(top["reps"])
    return top["e1rm"] or round(top["peso"] * (1 + top["reps"] / 30), 1)


# ---------- perfil (Gym.md → ## Perfil) ----------

def perfil(path: Path | None = None) -> dict:
    p = path or gs.gym_md()
    out = {"lesiones": "", "no_quiero": [], "objetivo": "", "peso_corporal": None, "ejercicios_clave": [], "zonas": []}
    if not p.exists():
        return out
    txt = p.read_text(encoding="utf-8")
    m = re.search(r"^## Perfil\s*$(.*?)^## ", txt, re.S | re.M)
    if not m:
        return out
    for line in m.group(1).splitlines():
        mm = re.match(r"^-\s*\*\*(.+?):\*\*\s*(.*)$", line.strip())
        if not mm:
            continue
        k, v = gs.norm(mm[1]), mm[2].strip().strip("_").strip()
        if k.startswith("lesiones"):
            out["lesiones"] = v
        elif k.startswith("no quiero"):
            out["no_quiero"] = [x.strip() for x in re.split(r"[,;]", v) if x.strip()]
        elif k.startswith("objetivo"):
            out["objetivo"] = v
        elif k.startswith("peso corporal"):
            n = re.search(r"\d+(?:[.,]\d+)?", v)
            out["peso_corporal"] = float(n[0].replace(",", ".")) if n else None
        elif k.startswith("ejercicios clave"):
            out["ejercicios_clave"] = [x.strip() for x in v.split(",") if x.strip()]
    les = gs.norm(out["lesiones"])
    if les and not re.match(r"^(ninguna|no|-|—|sin)\b", les):
        out["zonas"] = [z for z in ZONAS if z in les]
    return out


def molestias(perf: dict, logs: list[dict], hoy: date) -> list[dict]:
    """Zonas con molestia activa: las del Perfil y las anotadas en sensaciones en los últimos 10 días."""
    out = [{"zona": z, "fuente": "Perfil de Gym.md", "detalle": perf.get("lesiones", "")} for z in perf.get("zonas", [])]
    for l in logs:
        if l.get("molestia_zona") and l.get("fecha", "") >= (hoy - timedelta(days=10)).isoformat():
            z = gs.norm(l["molestia_zona"])
            zona = next((k for k in ZONAS if k in z), z)
            if not any(o["zona"] == zona for o in out):
                out.append({"zona": zona, "fuente": f"Sensaciones {l['fecha']}", "detalle": l.get("notas", "")})
    return out


def afectado(principales: list[str], secundarios: list[str], zonas: list[dict]) -> dict | None:
    for z in zonas:
        mus = ZONAS.get(z["zona"], [z["zona"]])
        if set(mus) & set(principales) or set(mus) & set(secundarios):
            return z
    return None


# ---------- pausas (enfermedad, lesión, vacaciones) ----------

PAUSA_MIN_DIAS = 4   # una pausa más corta no cambia nada: es un descanso normal
VUELTA_DIAS = 21     # ventana tras la pausa en la que se aplica la vuelta prudente
VUELTA_CARGA = 0.9   # primera sesión de cada ejercicio tras la pausa: ~90 % del último top set
MOTIVOS_PAUSA = {"enfermedad": "enfermedad", "lesion": "lesión", "vacaciones": "vacaciones", "otro": "pausa"}


def _d(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def dias_pausa(p: dict, hasta: date | None = None) -> int:
    fin = _d(p.get("hasta")) or hasta or date.today()
    return (fin - _d(p["desde"])).days + 1


def pausa_en(pausas: list[dict] | None, fecha: date) -> dict | None:
    """La pausa que cubre ese día (sin fin = en curso)."""
    for p in pausas or []:
        d, h = _d(p["desde"]), _d(p.get("hasta"))
        if d <= fecha and (h is None or fecha <= h):
            return p
    return None


def pausa_reciente(pausas: list[dict] | None, fecha: date) -> dict | None:
    """La última pausa de PAUSA_MIN_DIAS o más que terminó en los VUELTA_DIAS anteriores a `fecha`."""
    cand = [p for p in pausas or [] if p.get("hasta") and _d(p["hasta"]) < fecha
            and (fecha - _d(p["hasta"])).days <= VUELTA_DIAS and dias_pausa(p) >= PAUSA_MIN_DIAS]
    return max(cand, key=lambda p: p["hasta"], default=None)


def dias_laborables_en_pausa(pausas: list[dict] | None, desde: date, hasta: date) -> int:
    """Días de lunes a viernes entre `desde` y `hasta` cubiertos por alguna pausa (para no contarlos como perdidos)."""
    n, d = 0, desde
    while d <= hasta:
        if d.weekday() < 5 and pausa_en(pausas, d):
            n += 1
        d += timedelta(days=1)
    return n


def _txt_pausa(p: dict) -> str:
    h = p.get("hasta")
    return f"{MOTIVOS_PAUSA.get(p.get('motivo'), 'pausa')}, {p['desde'][8:10]}/{p['desde'][5:7]}" + (f"–{h[8:10]}/{h[5:7]}" if h else " en adelante")


def vuelta_de_pausa(obj: dict, hist: list[dict], cfg: dict, pausa: dict) -> dict:
    """Ajusta el objetivo de un ejercicio tras una pausa larga (es una RECOMENDACIÓN, como el resto).
    - 1.ª vez tras la pausa: ~90 % del último top set de antes, mismas reps, sin fallo (RIR 2).
    - 2.ª vez: vuelve a la carga de antes de la pausa (sin pedir más reps) si la primera fue bien (≥ 85 % del rendimiento previo).
    - Después: progresión normal."""
    if obj.get("accion") in ("sin_datos", "sin_objetivo") or not hist:
        return obj
    antes = [h for h in hist if h["fecha"] < pausa["desde"] and h["top"]]
    despues = [h for h in hist if h["fecha"] > (pausa.get("hasta") or "9999")]
    if not antes or len(despues) >= 2:
        return obj
    ref = antes[-1]["top"]
    w, r, paso = ref["peso"], ref["reps"], cfg["incremento_kg"]
    lo, hi = cfg["rep_min"], cfg["rep_max"]
    etiqueta = _txt_pausa(pausa)
    n_back = max(0, cfg["series"] - 1)
    if not despues:  # primera sesión tras la pausa
        tw = redondear(w * VUELTA_CARGA, paso, "abajo") if w is not None else None
        if w is not None and tw >= w:
            tw = round(w - paso, 2)
        tr = r if w is not None else max(1, r - 2)
        top = {"peso": tw, "reps": tr, "rir": 2}
        if cfg["metodo"] == "doble_progresion":
            so = [{"peso": tw, "reps": tr, "rir": 2} for _ in range(cfg["series"])]
        else:
            bw = (redondear(tw * 0.9, paso, "abajo") if tw else None)
            so = [top] + [{"peso": bw, "reps": f"{lo}–{hi}", "rir": 3} for _ in range(n_back)]
        motivo = (f"Vuelves de una pausa ({etiqueta}): primera vez tras la pausa al ~{int(VUELTA_CARGA * 100)} % "
                  f"de tu último top set ({_fmt(ref)}), mismas reps y sin llegar al fallo (RIR 2). "
                  "La próxima vez se recupera la carga de antes.")
        accion = "vuelta"
    else:  # segunda sesión: recuperar la carga de antes si la primera fue bien
        a, b = rendimiento(ref), rendimiento(despues[-1]["top"]) if despues[-1]["top"] else None
        if not (a and b and b >= a * 0.85):
            return obj | {"motivo": f"Tras la pausa ({etiqueta}) la primera sesión costó: " + obj["motivo"]}
        top = {"peso": w, "reps": r, "rir": cfg["rir_top"]}
        if cfg["metodo"] == "doble_progresion":
            so = [{"peso": w, "reps": r, "rir": cfg["rir_backoff"]} for _ in range(cfg["series"])]
        else:
            bw = redondear(w * 0.9, paso, "abajo") if w is not None else None
            so = [top] + [{"peso": bw, "reps": f"{lo}–{hi}", "rir": cfg["rir_backoff"]} for _ in range(n_back)]
        motivo = (f"Segunda sesión tras la pausa ({etiqueta}): la primera fue bien, así que vuelve a la carga de antes "
                  f"({_fmt(ref)}). Desde la siguiente, progresión normal.")
        accion = "retomar"
    if obj.get("precaucion"):  # con molestia manda la precaución: nunca más carga que la que proponía ella
        return obj | {"motivo": f"{obj['motivo']} (Además vuelves de una pausa: {etiqueta}.)"}
    return obj | {"accion": accion, "motivo": motivo, "top": so[0], "backoffs": so[1:], "series_objetivo": so,
                  "pausa": {"desde": pausa["desde"], "hasta": pausa.get("hasta"), "motivo": pausa.get("motivo")}}


# ---------- objetivo de progresión ----------

def objetivo(hist: list[dict], cfg: dict, zona: dict | None = None) -> dict:
    """Objetivo del siguiente entreno de un ejercicio (recomendación) y por qué."""
    lo, hi, paso = cfg["rep_min"], cfg["rep_max"], cfg["incremento_kg"]
    base = {"ejercicio_id": cfg["ejercicio_id"], "nombre": cfg["nombre"], "categoria": cfg["categoria"],
            "metodo": cfg["metodo"], "rango": [lo, hi], "series": cfg["series"], "descanso_s": cfg["descanso_s"],
            "incremento_kg": paso, "nivel": "recomendacion", "evidencia": [], "precaucion": None}
    if cfg["categoria"] == "cardio":
        return base | {"accion": "sin_objetivo", "motivo": "Cardio: sin objetivo de carga.", "top": None, "backoffs": [],
                       "series_objetivo": []}
    if not hist:
        return base | {"accion": "sin_datos", "top": None, "backoffs": [], "series_objetivo": [],
                       "motivo": f"Sin historial: elige un peso con el que llegues a {lo}–{hi} reps con 1–2 en recámara. "
                                 "Ese día marca la referencia."}
    last = hist[-1]
    top = last["top"]
    prev = next((h for h in reversed(hist[:-1]) if h["top"]), None)
    ev = [f"Último ({last['fecha']}): " + ", ".join(_fmt(d) for d in last["series"])]
    if top is None:
        return base | {"accion": "sin_datos", "top": None, "backoffs": [], "series_objetivo": [], "evidencia": ev,
                       "motivo": "La última vez no hubo series efectivas que sirvan de referencia."}
    if prev:
        ev.append(f"Anterior ({prev['fecha']}): top set {_fmt(prev['top'])}")
    w, r = top["peso"], top["reps"]
    accion, motivo = "mas_reps", ""

    if cfg["metodo"] == "doble_progresion" and w is not None:
        return base | _doble(hist, cfg, ev, zona)

    if w is None:  # peso corporal
        if r >= hi:
            tw, tr, accion = paso, lo, "lastre"
            motivo = f"Llegaste a {r} reps con tu peso (tope {hi}): añade {paso:g} kg de lastre y vuelve a {lo}."
        else:
            tw, tr = None, r + 1
            motivo = f"{r} reps con tu peso: objetivo {r + 1} en la primera serie al fallo."
    elif r >= hi:
        tw, tr, accion = redondear(w + paso, paso), lo, "subir_peso"
        motivo = f"Top set {w:g}×{r}: tope del rango ({hi}). Sube a {tw:g} kg y trabaja desde {lo} reps."
    elif r >= lo:
        tw, tr = w, r + 1
        motivo = f"Top set {w:g}×{r}, dentro del rango {lo}–{hi}: mismo peso, objetivo {r + 1} reps."
    else:
        prev_bajo = prev and prev["top"]["peso"] is not None and prev["top"]["peso"] >= w and prev["top"]["reps"] < lo
        if r <= lo - 3 and not prev_bajo:
            # Muy por debajo del rango: el método dice mismo peso; objetivo realista (+1) y la alternativa calculada
            alt = redondear(w * (1 + r / 30) / (1 + lo / 30), paso, "abajo")
            tw, tr, accion = w, r + 1, "mantener"
            motivo = (f"Top set {w:g}×{r}, muy por debajo del rango {lo}–{hi}: mismo peso, objetivo {r + 1}. "
                      f"Alternativa: ~{alt:g} kg te dejaría en {lo} reps (según el e1RM estimado), o cambia el rango "
                      "del ejercicio en sus ajustes si quieres trabajarlo más pesado.")
        elif prev_bajo:
            tw, tr, accion = redondear(w * 0.92, paso, "abajo"), lo, "bajar_peso"
            if tw >= w:
                tw = round(w - paso, 2)
            motivo = (f"Dos sesiones seguidas por debajo de {lo} reps ({prev['top']['peso']:g}×{prev['top']['reps']}, "
                      f"{w:g}×{r}): baja a {tw:g} kg (−5–10 %) y busca {lo}+ reps.")
        else:
            tw, tr, accion = w, lo, "mantener"
            motivo = f"Top set {w:g}×{r}, por debajo de {lo}: mismo peso y aprieta hasta {lo}."

    # Si el rendimiento ha caído claramente, no se sube la carga automáticamente
    if accion in ("subir_peso", "lastre") and prev:
        a, b = rendimiento(prev["top"]), rendimiento(top)
        if a and b and b < a * 0.95:
            tw, tr, accion = w, min(r + 1, hi) if w is not None else r + 1, "mantener"
            motivo = (f"Llegaste al tope, pero el rendimiento bajó respecto al {prev['fecha']} "
                      f"({a:g} → {b:g}{' kg e1RM' if w is not None else ' reps'}): consolida {w if w is not None else 'tu peso'} antes de subir.")
            ev.append("Bajada > 5 % entre las dos últimas sesiones (e1RM estimado)")
    prec = None
    if zona:
        prec = (f"Molestia en {zona['zona']} ({zona['fuente']}): no lo lleves al fallo (RIR 2–3), no subas carga "
                "y si duele, sáltalo o cambia a una variante sin dolor.")
        if accion != "bajar_peso":  # con molestia no se busca más carga ni más reps: mismo top set, sin fallo
            tw, tr, accion = w if w is not None else None, r, "precaucion"
            motivo = (f"Última vez {_fmt(top)}. Repite {'ese peso' if w is not None else 'con tu peso'} y esas reps "
                      "sin llegar al fallo; la progresión se retoma cuando la molestia desaparezca.")
        motivo = prec + " " + motivo
    backoffs = []
    if tw is not None and cfg["series"] > 1:
        bw = redondear(tw * 0.9, paso, "abajo")
        if bw >= tw:
            bw = round(tw - paso, 2)
        backoffs = [{"peso": bw, "reps": f"{lo}–{hi}", "rir": cfg["rir_backoff"]} for _ in range(cfg["series"] - 1)]
    elif cfg["series"] > 1:
        backoffs = [{"peso": None, "reps": f"{max(1, r - 2)}+", "rir": cfg["rir_backoff"]} for _ in range(cfg["series"] - 1)]
    top_obj = {"peso": tw, "reps": tr, "rir": 2 if zona else cfg["rir_top"]}
    return base | {"accion": accion, "motivo": motivo, "evidencia": ev, "precaucion": prec, "top": top_obj,
                   "backoffs": backoffs, "series_objetivo": [top_obj] + backoffs,
                   "ultimo": {"fecha": last["fecha"], "top": top, "series": [_fmt(d) for d in last["series"]]},
                   "avisos": last["avisos"]}


def _doble(hist: list[dict], cfg: dict, ev: list[str], zona: dict | None) -> dict:
    """Doble progresión clásica con series rectas (el ejemplo 60×10, 60×9, 60×8 → 60×10, 60×10, 60×9)."""
    lo, hi, n, paso = cfg["rep_min"], cfg["rep_max"], cfg["series"], cfg["incremento_kg"]
    last = hist[-1]

    def trabajo(h):
        pesos = [d["peso"] for d in h["series"] if d["rol"] in ("top", "backoff") and d["peso"]]
        if not pesos:
            return None, []
        w = max(pesos)
        return w, [d["reps"] for d in h["series"] if d["peso"] == w and d["rol"] in ("top", "backoff")]

    w, reps = trabajo(last)
    if w is None:
        return {"accion": "sin_datos", "top": None, "backoffs": [], "series_objetivo": [], "evidencia": ev,
                "motivo": "Sin series de trabajo con peso en la última sesión."}
    accion = "mas_reps"
    if len(reps) >= n and all(x >= hi for x in reps[:n]):
        tw, objetivo_reps, accion = redondear(w + paso, paso), [lo] * n, "subir_peso"
        motivo = f"Todas las series a {w:g} kg en el tope ({hi}): sube a {tw:g} kg y empieza en {lo}."
    else:
        tw = w
        objetivo_reps = [min(hi, (reps[i] if i < len(reps) else lo) + 1) for i in range(n)]
        motivo = f"{w:g} kg × {'/'.join(map(str, reps))}: +1 rep por serie hasta {hi}."
    prev = next((h for h in reversed(hist[:-1]) if trabajo(h)[0] == w), None)
    if prev and accion == "mas_reps" and sum(trabajo(prev)[1][:n]) > sum(reps[:n]):
        objetivo_reps, accion = [min(hi, x) for x in (trabajo(prev)[1][:n] + [lo] * n)[:n]], "mantener"
        motivo = (f"Has hecho menos reps que el {prev['fecha']} con {w:g} kg: repite el objetivo de entonces "
                  f"({'/'.join(map(str, objetivo_reps))}) antes de seguir.")
    prec = None
    if zona:
        prec = f"Molestia en {zona['zona']} ({zona['fuente']}): sin fallo, sin subir carga."
        tw, objetivo_reps, accion = w, reps[:n] or [lo] * n, "precaucion"
        motivo = prec + " " + motivo
    so = [{"peso": tw, "reps": x, "rir": cfg["rir_backoff"]} for x in objetivo_reps]
    return {"accion": accion, "motivo": motivo, "evidencia": ev, "precaucion": prec, "top": so[0] if so else None,
            "backoffs": so[1:], "series_objetivo": so,
            "ultimo": {"fecha": last["fecha"], "top": last["top"], "series": [_fmt(d) for d in last["series"]]},
            "avisos": last["avisos"]}


def _fmt(d: dict | None) -> str:
    if not d:
        return "—"
    p = "PC" if d.get("peso") is None else f"{d['peso']:g}"
    extra = {"calentamiento": " cal.", "aproximacion": " aprox.", "intento": " intento"}.get(d.get("rol", ""), "")
    return f"{p}×{d['reps']}{extra}"


# ---------- estancamientos ----------

def estancamiento(hist: list[dict], hoy: date | None = None) -> dict:
    """Ventana de las últimas sesiones con top set. Nunca por una sola mala sesión.
    - estancado: 3+ sesiones seguidas sin superar el mejor rendimiento previo (+1 %), en ≥ 10 días.
    - retroceso: 2 bajadas seguidas de ≥ 3 % en el rendimiento del top set.
    Confianza: alta con 4+ sesiones en la ventana y sin huecos > 21 días; media con 3; baja si hay huecos."""
    pts = [(h["fecha"], rendimiento(h["top"]), h["top"]) for h in hist if h["top"]]
    res = {"estado": "sin_datos", "confianza": None, "sesiones": len(pts), "evidencia": [], "propuestas": [],
           "nivel": "inferencia"}
    if len(pts) < 3:
        res["estado"] = "pocos_datos"
        res["evidencia"].append(f"{len(pts)} sesiones con top set; hacen falta 3 para valorar.")
        return res
    ev = [f"{f}: {_fmt(t)} → {v:g}{' kg e1RM (est.)' if t['peso'] is not None else ' reps'}" for f, v, t in pts[-5:]]
    res["evidencia"] = ev
    # retroceso
    if len(pts) >= 3 and pts[-1][1] < pts[-2][1] * 0.97 and pts[-2][1] < pts[-3][1] * 0.97:
        res |= {"estado": "retroceso", "confianza": "media" if len(pts) < 5 else "alta"}
        res["propuestas"] = ["Reducir temporalmente el volumen (−1 serie) y mantener la carga",
                             "Revisar sueño, descanso entre series y sensaciones de esos días",
                             "Si se repite, semana de descarga (−40 % series, RIR 3)"]
        return res
    # ventana de estancamiento: cuántas sesiones finales no superan el mejor anterior a ellas
    k = 0
    for i in range(len(pts) - 1, 0, -1):
        mejor_antes = max(v for _, v, _ in pts[:i])
        if pts[i][1] <= mejor_antes * 1.01:
            k += 1
        else:
            break
    if k >= 3:
        f0 = date.fromisoformat(pts[-k][0])
        dias = (date.fromisoformat(pts[-1][0]) - f0).days
        if dias >= 10:
            fechas = [date.fromisoformat(f) for f, _, _ in pts[-k - 1:]]
            hueco = max((b - a).days for a, b in zip(fechas, fechas[1:]))
            conf = "baja" if hueco > 21 else "alta" if k >= 4 else "media"
            res |= {"estado": "estancado", "confianza": conf, "ventana": k, "dias": dias}
            mismo_peso = len({t["peso"] for _, _, t in pts[-k:]}) == 1
            props = []
            if mismo_peso:
                props.append("Mantener la carga e intentar +1 rep en el top set")
                props.append("Revisar el descanso antes del top set (2–3 min en compuestos)")
            props.append("Semana de descarga en este ejercicio (−40 % series, RIR 3) y volver a apretar")
            if k >= 5:
                props.append("Cambiar el rango de repeticiones o sustituirlo por una variante durante 6 semanas")
            res["propuestas"] = props
            return res
    mejora = pts[-1][1] > max(v for _, v, _ in pts[:-1]) * 1.01
    res |= {"estado": "progresa" if mejora else "estable", "confianza": "media"}
    return res


# ---------- récords ----------

def records(sesiones: list, eid: str | None = None) -> dict:
    """Récords por ejercicio. Reales: peso máximo, más reps con un peso, mayor volumen en una serie y en una sesión.
    Estimado: mejor e1RM (Epley). La primera sesión de un ejercicio fija la marca, pero no cuenta como récord nuevo."""
    por: dict[str, dict] = {}
    eventos: list[dict] = []
    for s in sesiones:
        for e in s.ejercicios:
            if eid and e.id != eid:
                continue
            ef = [x for x in e.efectivas if x.reps]
            if not ef:
                continue
            r = por.setdefault(e.id, {"ejercicio_id": e.id, "nombre": e.nombre, "peso_max": None, "reps_por_peso": {},
                                      "volumen_serie": None, "volumen_sesion": None, "e1rm": None, "primera": s.fecha})
            nueva = r["primera"] == s.fecha

            def ev(tipo, valor, detalle, nivel="registrado"):
                if not nueva:
                    eventos.append({"fecha": s.fecha, "sesion_id": s.id, "ejercicio_id": e.id, "nombre": e.nombre,
                                    "tipo": tipo, "valor": valor, "detalle": detalle, "nivel": nivel})
            con_peso = [x for x in ef if x.peso]
            if con_peso:
                m = max(con_peso, key=lambda x: (x.peso, x.reps))
                if r["peso_max"] is None or m.peso > r["peso_max"]["peso"]:
                    if r["peso_max"]:
                        ev("peso_max", m.peso, f"{m.peso:g}×{m.reps} (antes {r['peso_max']['peso']:g} kg)")
                    r["peso_max"] = {"peso": m.peso, "reps": m.reps, "fecha": s.fecha}
                fuertes = [x for x in con_peso if x.reps >= 3] or con_peso
                wtop = max(x.peso for x in fuertes)
                for x in con_peso:
                    k = f"{x.peso:g}"
                    antes = r["reps_por_peso"].get(k)
                    # más reps con este peso que nunca con ese peso o uno mayor
                    mejor_igual_o_mas = max((v["reps"] for p, v in r["reps_por_peso"].items() if float(p) >= x.peso), default=None)
                    if antes is None or x.reps > antes["reps"]:
                        if mejor_igual_o_mas is not None and x.reps > mejor_igual_o_mas and x.peso == wtop:
                            ev("reps_con_peso", x.reps, f"{x.peso:g}×{x.reps} (antes {mejor_igual_o_mas} reps con ≥{x.peso:g} kg)")
                        r["reps_por_peso"][k] = {"reps": x.reps, "fecha": s.fecha}
                b = max(con_peso, key=lambda x: x.peso * x.reps)
                if r["volumen_serie"] is None or b.peso * b.reps > r["volumen_serie"]["valor"]:
                    if r["volumen_serie"]:
                        ev("volumen_serie", round(b.peso * b.reps, 1), f"{b.peso:g}×{b.reps} = {b.peso * b.reps:g} kg")
                    r["volumen_serie"] = {"valor": round(b.peso * b.reps, 1), "peso": b.peso, "reps": b.reps, "fecha": s.fecha}
                if r["volumen_sesion"] is None or e.volumen > r["volumen_sesion"]["valor"]:
                    if r["volumen_sesion"]:
                        ev("volumen_sesion", e.volumen, f"{e.volumen:g} kg en la sesión")
                    r["volumen_sesion"] = {"valor": e.volumen, "fecha": s.fecha}
                best = e.mejor
                if best and (r["e1rm"] is None or best.e1rm > r["e1rm"]["valor"]):
                    if r["e1rm"]:
                        ev("e1rm", best.e1rm, f"{best.peso:g}×{best.reps} ≈ {best.e1rm:g} kg", "estimacion")
                    r["e1rm"] = {"valor": best.e1rm, "peso": best.peso, "reps": best.reps, "fecha": s.fecha,
                                 "nivel": "estimacion", "formula": "Epley, 1–12 reps"}
            else:  # peso corporal
                m = max(ef, key=lambda x: x.reps)
                antes = r["reps_por_peso"].get("PC")
                if antes is None or m.reps > antes["reps"]:
                    if antes:
                        ev("reps_con_peso", m.reps, f"PC×{m.reps} (antes {antes['reps']})")
                    r["reps_por_peso"]["PC"] = {"reps": m.reps, "fecha": s.fecha}
    return {"ejercicios": por, "eventos": eventos}


# ---------- músculos ----------

def _semana(d: date) -> date:
    return d - timedelta(days=d.weekday())


def musculos(sesiones: list, hoy: date, semanas: int = 4, peso_secundario: float = 0.5) -> dict:
    """Series directas (músculo principal) e indirectas (secundario) por semana, frecuencia y tendencia.
    Aproximación analítica: principal 1, secundario `peso_secundario`. No es una medida fisiológica."""
    grupos = gs._reglas()["grupos"]
    lunes = _semana(hoy)
    sem = [lunes - timedelta(weeks=i) for i in range(semanas - 1, -1, -1)]
    datos = {g: {"musculo": g, "semanas": [], "ultima": None, "ejercicios": Counter()} for g in grupos}
    for g in grupos:
        for ini in sem:
            per = gs.en_periodo(sesiones, ini, ini + timedelta(days=6))
            d = i = 0.0
            freq = set()
            for s in per:
                for e in s.ejercicios:
                    n = len(e.efectivas)
                    if g in e.principales and n:
                        d += n
                        freq.add(s.fecha)
                    elif g in e.secundarios and n:
                        i += n
            datos[g]["semanas"].append({"semana": ini.isoformat(), "directas": d, "indirectas": i,
                                        "ponderadas": round(d + peso_secundario * i, 1), "frecuencia": len(freq)})
    for s in sesiones:
        for e in s.ejercicios:
            for g in e.principales:
                if g in datos and e.efectivas:
                    datos[g]["ultima"] = max(datos[g]["ultima"] or "", s.fecha)
                    if s.fecha >= sem[0].isoformat():
                        datos[g]["ejercicios"][e.nombre] += 1
    out = []
    for g, d in datos.items():
        w = d["semanas"]
        actual = w[-1]["ponderadas"]
        completas = w[:-1] if hoy.weekday() < 6 else w  # la semana en curso aún no ha terminado
        media = round(sum(x["ponderadas"] for x in completas) / len(completas), 1) if completas else 0
        if len(completas) >= 2:
            a = sum(x["ponderadas"] for x in completas[-2:]) / 2
            b = sum(x["ponderadas"] for x in completas[:-2]) / max(1, len(completas) - 2) if len(completas) > 2 else None
            tend = None if b is None else ("sube" if a > b * 1.15 else "baja" if a < b * 0.85 else "estable")
        else:
            tend = None
        out.append({"musculo": g, "semanas": w, "actual": actual, "media_semanal": media, "tendencia": tend,
                    "frecuencia_media": round(sum(x["frecuencia"] for x in completas) / len(completas), 1) if completas else 0,
                    "ultima": d["ultima"], "ejercicios": [n for n, _ in d["ejercicios"].most_common(4)]})
    return {"musculos": out, "peso_secundario": peso_secundario, "nivel": "calculado",
            "criterio": f"Directas = series efectivas donde es principal; indirectas = donde es secundario (×{peso_secundario:g}). "
                        "Aproximación analítica, no una medida fisiológica."}


# ---------- recuperación (orientativa) ----------

CAMPOS_SENSACIONES = ("energia", "sueno", "agujetas", "motivacion", "estres")


def recuperacion(sesiones: list, logs: list[dict], hoy: date, zonas: list[dict] | None = None) -> dict:
    """Carga reciente frente a la habitual por músculo (7 días frente a la media semanal de los 21 anteriores).
    No mide la recuperación muscular: es una señal para decidir con cabeza."""
    out = []
    grupos = gs._reglas()["grupos"]
    for g in grupos:
        def series(d0, d1):
            t = 0.0
            for s in gs.en_periodo(sesiones, d0, d1):
                for e in s.ejercicios:
                    if g in e.principales:
                        t += len(e.efectivas)
                    elif g in e.secundarios:
                        t += 0.5 * len(e.efectivas)
            return t
        agudo = series(hoy - timedelta(days=6), hoy)
        cronico = series(hoy - timedelta(days=27), hoy - timedelta(days=7)) / 3
        ult = None
        for s in reversed(sesiones):
            if any(g in e.principales and e.efectivas for e in s.ejercicios):
                ult = s.fecha
                break
        dias = (hoy - date.fromisoformat(ult)).days if ult else None
        ratio = round(agudo / cronico, 2) if cronico else None
        if not ult:
            estado = "sin_datos"
        elif ratio is not None and ratio > 1.5 and agudo >= 6:
            estado = "carga_alta"
        elif dias is not None and dias <= 1:
            estado = "reciente"
        elif dias is not None and dias > 10:
            estado = "sin_trabajar"
        elif ratio is not None and ratio < 0.5:
            estado = "carga_baja"
        else:
            estado = "normal"
        out.append({"musculo": g, "ultima": ult, "dias": dias, "series_7d": round(agudo, 1),
                    "media_semanal_previa": round(cronico, 1), "ratio": ratio, "estado": estado})
    # sensaciones
    recientes = sorted([l for l in logs if l.get("fecha", "") >= (hoy - timedelta(days=13)).isoformat()],
                       key=lambda l: l["fecha"])
    medias = {}
    for c in CAMPOS_SENSACIONES:
        v = [l[c] for l in recientes if l.get(c) is not None]
        medias[c] = round(sum(v) / len(v), 1) if v else None
    # distribución: días seguidos con los mismos músculos principales
    seguidos = []
    ult14 = gs.en_periodo(sesiones, hoy - timedelta(days=13), hoy)
    for a, b in zip(ult14, ult14[1:]):
        if (date.fromisoformat(b.fecha) - date.fromisoformat(a.fecha)).days == 1:
            ma = {m for e in a.ejercicios for m in e.principales}
            mb = {m for e in b.ejercicios for m in e.principales}
            if ma & mb:
                seguidos.append({"fechas": [a.fecha, b.fecha], "musculos": sorted(ma & mb)})
    return {"musculos": out, "sensaciones": recientes, "medias_14d": medias, "molestias": zonas or [],
            "dias_seguidos_mismo_musculo": seguidos, "correlaciones": correlaciones(sesiones, logs),
            "nivel": "inferencia",
            "aviso": "Orientativo: compara la carga reciente con la habitual. No mide la recuperación ni es un diagnóstico."}


def indice_rendimiento(sesiones: list) -> dict[str, float]:
    """Por sesión: media del cambio del top set (e1RM estimado o reps) frente a la sesión anterior del mismo ejercicio."""
    ultimo: dict[str, float] = {}
    out = {}
    for s in sesiones:
        cambios = []
        for e in s.ejercicios:
            if not e.series:
                continue
            rs = roles(e.series)
            top = next((x for x, r in zip(e.series, rs) if r == "top"), None)
            if not top:
                continue
            v = float(top.reps) if top.peso is None else top.peso * (1 + top.reps / 30)
            if e.id in ultimo and ultimo[e.id]:
                cambios.append(v / ultimo[e.id] - 1)
            ultimo[e.id] = v
        if cambios:
            out[s.fecha] = round(100 * sum(cambios) / len(cambios), 2)
    return out


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if not sx or not sy:
        return None
    return round(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy), 2)


def correlaciones(sesiones: list, logs: list[dict], minimo: int = 6) -> dict:
    """Relación entre sensaciones (del mismo día) y el índice de rendimiento de la sesión. Con menos de `minimo`
    pares no se calcula. Correlación no implica causa."""
    idx = indice_rendimiento(sesiones)
    por_fecha = {l["fecha"]: l for l in logs}
    res = {}
    for c in CAMPOS_SENSACIONES:
        pares = [(por_fecha[f][c], v) for f, v in idx.items() if f in por_fecha and por_fecha[f].get(c) is not None]
        if len(pares) < minimo:
            res[c] = {"n": len(pares), "r": None, "texto": f"Datos insuficientes ({len(pares)}/{minimo} días con sensaciones y entreno)"}
        else:
            r = _pearson([a for a, _ in pares], [b for _, b in pares])
            fuerza = "sin relación clara" if r is None or abs(r) < 0.3 else ("relación moderada" if abs(r) < 0.6 else "relación fuerte")
            res[c] = {"n": len(pares), "r": r, "texto": f"{fuerza} (r={r}, n={len(pares)})"}
    return {"por_campo": res, "nivel": "inferencia", "minimo": minimo,
            "criterio": "Pearson entre la sensación del día y el cambio medio del top set frente a la sesión anterior."}


# ---------- plantilla de sesión, rutina y propuesta ----------

def mismo_nombre(a: str, b: str) -> bool:
    a, b = gs.norm(a), gs.norm(b)
    return a == b or a.startswith(b + " ") or b.startswith(a + " ")


def plantilla(sesiones: list, nombre: str, n: int = 3) -> dict:
    """Ejercicios habituales de una sesión: los que aparecen en ≥2 de las últimas `n` con ese nombre, en su orden medio."""
    ult = [s for s in sesiones if mismo_nombre(s.nombre, nombre)][-n:]
    if not ult:
        return {"sesiones": [], "ejercicios": []}
    pos: dict[str, list[int]] = defaultdict(list)
    nombres: dict[str, str] = {}
    for s in ult:
        for i, e in enumerate([e for e in s.ejercicios if e.series and e.tipo != "cardio"]):
            pos[e.id].append(i)
            nombres[e.id] = e.nombre
    minimo = 2 if len(ult) >= 2 else 1
    ids = [k for k, v in pos.items() if len(v) >= minimo] or list(pos)
    ids.sort(key=lambda k: sum(pos[k]) / len(pos[k]))
    resto = sorted((k for k in pos if k not in ids), key=lambda k: -max(i for i, s in enumerate(ult)
                                                                      for e in s.ejercicios if e.id == k))
    return {"sesiones": [s.fecha for s in ult],
            "ejercicios": [{"id": k, "nombre": nombres[k], "veces": len(pos[k])} for k in ids],
            "opcionales": [{"id": k, "nombre": nombres[k], "veces": len(pos[k])} for k in resto]}


def rutina_desde_historial(sesiones: list, dias: dict[int, str] | None = None) -> dict:
    """Borrador de rutina a partir de lo que hace de verdad (no se activa solo)."""
    dias = dias or RUTINA_DEFECTO
    spec = {"dias": {}, "notas": "Generada a partir de las últimas 3 sesiones de cada día."}
    for wd, nombre in dias.items():
        pl = plantilla(sesiones, nombre)
        ej = []
        for x in pl["ejercicios"]:
            ap = apariciones(sesiones, x["id"])
            c = config(x["id"], x["nombre"], ap)
            ej.append({"id": x["id"], "nombre": x["nombre"], "series": c["series"], "rep_min": c["rep_min"],
                       "rep_max": c["rep_max"], "descanso_s": c["descanso_s"], "metodo": c["metodo"],
                       "incremento_kg": c["incremento_kg"]})
        spec["dias"][str(wd)] = {"nombre": nombre, "ejercicios": ej}
    return spec


def dias_rutina(rutina: dict | None) -> dict[int, str]:
    if rutina and rutina.get("dias"):
        return {int(k): v["nombre"] for k, v in rutina["dias"].items() if v.get("nombre")}
    return dict(RUTINA_DEFECTO)


def proxima_fecha(sesiones: list, hoy: date, rutina: dict | None = None, planificadas: list[dict] | None = None) -> tuple[date, str] | None:
    dias = dias_rutina(rutina)
    hechas = {s.fecha for s in sesiones}
    for p in planificadas or []:
        if p.get("estado") in ("aceptada", "propuesta") and p["fecha"] >= hoy.isoformat() and p["fecha"] not in hechas:
            return date.fromisoformat(p["fecha"]), p["nombre"]
    for i in range(0, 8):
        d = hoy + timedelta(days=i)
        if d.weekday() in dias and d.isoformat() not in hechas:
            return d, dias[d.weekday()]
    return None


def minutos_por_serie(sesiones: list, duraciones: dict | None) -> float | None:
    """Mediana de minutos por serie registrada (incluidas aproximaciones) en las sesiones con duración de Hevy."""
    v = sorted(duraciones[s.id] / n for s in sesiones if duraciones and duraciones.get(s.id)
               and (n := sum(len(e.series) for e in s.ejercicios)) > 0)
    return round(v[len(v) // 2], 2) if v else None


def _duracion(ejercicios: list[dict], mps: float | None = None) -> int:
    if mps:
        return round(sum((e.get("series") or 3) + e.get("aprox", 0) for e in ejercicios) * mps)
    seg = 0
    for i, e in enumerate(ejercicios):
        n = e.get("series") or 3
        seg += n * 45 + max(0, n - 1) * (e.get("descanso_s") or 90) + 60
        if i == 0 and e.get("categoria") in ("compuesto", "maquina"):
            seg += 300  # aproximaciones del primer compuesto
    return round(seg / 60)


def proponer_sesion(sesiones: list, hoy: date, rutina: dict | None = None, ajustes: dict | None = None,
                    logs: list[dict] | None = None, perf: dict | None = None, fecha: date | None = None,
                    nombre: str | None = None, planificadas: list[dict] | None = None,
                    duraciones: dict | None = None, pausas: list[dict] | None = None) -> dict | None:
    """Siguiente sesión recomendada. Si hay rutina activa usa sus ejercicios; si no, los habituales de esa sesión.
    Es una RECOMENDACIÓN hasta que el usuario la acepta (entonces se guarda como sesión planificada)."""
    perf = perf or {}
    ajustes = ajustes or {}
    if fecha is None or nombre is None:
        pf = proxima_fecha(sesiones, hoy, rutina, planificadas)
        if not pf:
            return None
        fecha, nombre = pf
    zonas = molestias(perf, logs or [], hoy)
    pausa = pausa_reciente(pausas, fecha)
    en_pausa = pausa_en(pausas, fecha)
    dia = (rutina or {}).get("dias", {}).get(str(fecha.weekday()))
    if dia and mismo_nombre(dia.get("nombre", ""), nombre) and dia.get("ejercicios"):
        lista = [{"id": x["id"], "nombre": x["nombre"], "ajuste": {k: x.get(k) for k in
                  ("series", "rep_min", "rep_max", "descanso_s", "metodo", "incremento_kg")}} for x in dia["ejercicios"]]
        origen = f"Rutina «{rutina.get('nombre', 'activa')}» v{rutina.get('version', '?')}"
        pl = None
    else:
        pl = plantilla(sesiones, nombre)
        lista = [{"id": x["id"], "nombre": x["nombre"], "ajuste": {}, "veces": x["veces"]} for x in pl["ejercicios"]]
        cubiertos = {m for x in lista for _, e in apariciones(sesiones, x["id"])[-1:] for m in e.principales}
        for x in pl.get("opcionales", []):
            ap = apariciones(sesiones, x["id"])
            nuevos = set(ap[-1][1].principales) - cubiertos if ap else set()
            if nuevos:
                cubiertos |= nuevos
                lista.append({"id": x["id"], "nombre": x["nombre"], "ajuste": {}, "veces": x["veces"],
                              "opcional": f"Opcional: es lo único de tus últimas {nombre} que trabaja {', '.join(sorted(nuevos))}"})
        origen = (f"Tus últimas {len(pl['sesiones'])} sesiones de {nombre} ({', '.join(pl['sesiones'])})"
                  if pl["sesiones"] else "Sin historial de esta sesión")
    excl = [gs.norm(x) for x in perf.get("no_quiero", [])]
    clave = [gs.norm(x) for x in perf.get("ejercicios_clave", [])]
    ejercicios = []
    for x in lista:
        if any(k and k in gs.norm(x["nombre"]) for k in excl):
            continue
        ap = apariciones(sesiones, x["id"])
        aj = ajustes.get(x["id"], {}) | {k: v for k, v in x["ajuste"].items() if v is not None}
        cfg = config(x["id"], x["nombre"], ap, aj)
        hist = historial(sesiones, x["id"])
        nom_ap = ap[-1][1] if ap else None
        pri = nom_ap.principales if nom_ap else gs.clasificar(x["nombre"])[1]
        sec = nom_ap.secundarios if nom_ap else gs.clasificar(x["nombre"])[2]
        zona = afectado(pri, sec, zonas)
        obj = objetivo(hist, cfg, zona)
        if pausa:
            obj = vuelta_de_pausa(obj, hist, cfg, pausa)
        mejor = max((h for h in hist if h["top"]), key=lambda h: rendimiento(h["top"]) or 0, default=None)
        porque = []
        if x.get("opcional"):
            porque.append(x["opcional"])
        elif pl is not None and x.get("veces"):
            porque.append(f"Fijo en tu {nombre}: {x['veces']}/{len(pl['sesiones'])} últimas sesiones")
        elif pl is None:
            porque.append(f"Está en la rutina activa ({origen})")
        if any(k and (k in gs.norm(x["nombre"]) or gs.norm(x["nombre"]).startswith(k)) for k in clave):
            porque.append("Ejercicio clave de tu Perfil")
        if cfg["categoria"] in ("compuesto", "maquina"):
            porque.append("Compuesto: aquí se decide la progresión")
        aprox = [sum(1 for d in h["series"] if d["rol"] in ("aproximacion", "calentamiento")) for h in hist[-3:]]
        ejercicios.append({"id": x["id"], "nombre": x["nombre"], "principales": pri, "secundarios": sec,
                           "opcional": bool(x.get("opcional")), "aprox": round(sum(aprox) / len(aprox)) if aprox else 0,
                           "categoria": cfg["categoria"], "series": cfg["series"], "rango": [cfg["rep_min"], cfg["rep_max"]],
                           "descanso_s": cfg["descanso_s"], "metodo": cfg["metodo"], "objetivo": obj,
                           "ultimo": obj.get("ultimo"),
                           "mejor": {"fecha": mejor["fecha"], "top": mejor["top"]} if mejor else None,
                           "instrucciones": _instrucciones(cfg, obj),
                           "por_que": porque, "config": cfg})
    acciones = Counter(e["objetivo"]["accion"] for e in ejercicios)
    resumen = []
    if acciones.get("subir_peso"):
        resumen.append(f"subir peso en {acciones['subir_peso']}")
    if acciones.get("mas_reps"):
        resumen.append(f"+1 rep en {acciones['mas_reps']}")
    if acciones.get("mantener") or acciones.get("bajar_peso"):
        resumen.append(f"consolidar o bajar en {acciones.get('mantener', 0) + acciones.get('bajar_peso', 0)}")
    if acciones.get("precaucion"):
        resumen.append(f"precaución por molestias en {acciones['precaucion']}")
    if acciones.get("vuelta"):
        resumen.append(f"vuelta prudente tras la pausa en {acciones['vuelta']}")
    if acciones.get("retomar"):
        resumen.append(f"recuperar la carga de antes de la pausa en {acciones['retomar']}")
    aviso_pausa = (f"Estás en pausa ({_txt_pausa(en_pausa)}): esta propuesta es para cuando vuelvas. " if en_pausa else "")
    return {"fecha": fecha.isoformat(), "dia": DIAS[fecha.weekday()], "nombre": nombre, "origen": origen,
            "estado": "recomendacion", "nivel": "recomendacion", "ejercicios": ejercicios,
            "duracion_estimada_min": _duracion([{"series": e["series"], "descanso_s": e["descanso_s"], "aprox": e["aprox"],
                                                  "categoria": e["categoria"]} for e in ejercicios],
                                                minutos_por_serie(sesiones, duraciones)),
            "duracion_criterio": ("Mediana de minutos por serie de tus sesiones con duración de Hevy"
                                  if minutos_por_serie(sesiones, duraciones) else
                                  "45 s por serie + descansos + 1 min por ejercicio (sin duraciones de Hevy para calibrar)"),
            "objetivo": "Progresar en el top set de los compuestos manteniendo la técnica"
                        + (" y sin forzar la zona con molestias" if acciones.get("precaucion") else ""),
            "justificacion": aviso_pausa + ((f"{origen}. Plan: " + ", ".join(resumen) + ".") if resumen else origen),
            "molestias": zonas if acciones.get("precaucion") else [],
            "pausa": ({"desde": en_pausa["desde"], "hasta": en_pausa.get("hasta"), "motivo": en_pausa.get("motivo"), "en_curso": True}
                      if en_pausa else {"desde": pausa["desde"], "hasta": pausa["hasta"], "motivo": pausa.get("motivo"), "en_curso": False}
                      if pausa else None)}


def _instrucciones(cfg: dict, obj: dict) -> str:
    if cfg["categoria"] == "cardio":
        return "Cardio a ritmo cómodo."
    if cfg["metodo"] == "doble_progresion":
        return f"Series rectas con el mismo peso, {cfg['rep_min']}–{cfg['rep_max']} reps a RIR {cfg['rir_backoff']}. Descanso {cfg['descanso_s']} s."
    t = ("Aproximaciones marcadas como warm up en Hevy; top set al fallo (RIR 0) en "
         f"{cfg['rep_min']}–{cfg['rep_max']} reps; back-offs −10 % a RIR {cfg['rir_backoff']}, siempre bajando.")
    if obj.get("precaucion"):
        t = "Sin fallo (RIR 2–3). " + t.replace("al fallo (RIR 0)", "controlado")
    return t + f" Descanso {cfg['descanso_s'] // 60}–{cfg['descanso_s'] // 60 + 1} min." if cfg["descanso_s"] >= 120 else t + f" Descanso {cfg['descanso_s']} s."


# ---------- plan frente a realizado ----------

def buscar_sesion(sesiones: list, fecha: str, nombre: str):
    """Asociación automática solo si coinciden fecha y nombre de la sesión. Si no, se deja sin asociar."""
    c = [s for s in sesiones if s.fecha == fecha and mismo_nombre(s.nombre, nombre)]
    return c[0] if len(c) == 1 else None


def comparar(plan: dict, sesion) -> dict:
    """plan: {"ejercicios": [{"id","nombre","series","objetivo":{"top":{peso,reps},"backoffs":[...]}}]}"""
    if sesion is None:
        return {"estado": "sin_asociar", "cumplimiento": None, "ejercicios": [], "anadidos": []}
    hechos = {e.id: e for e in sesion.ejercicios if e.series}
    filas, puntos = [], []
    vol_prev = vol_real = 0.0
    for p in plan.get("ejercicios", []):
        o = p.get("objetivo") or {}
        top_o = o.get("top") or {}
        series_o = p.get("series") or len(o.get("series_objetivo") or []) or 0
        for so in o.get("series_objetivo") or []:
            reps = so.get("reps")
            if isinstance(reps, str):
                reps = int(re.match(r"\d+", reps)[0]) if re.match(r"\d+", reps) else 0
            vol_prev += (so.get("peso") or 0) * (reps or 0)
        e = hechos.get(p["id"])
        if not e:
            filas.append({"id": p["id"], "nombre": p["nombre"], "estado": "omitido", "series_previstas": series_o,
                          "series_hechas": 0, "objetivo": top_o, "real": None})
            puntos.append(0)
            continue
        rs = roles(e.series)
        top = next((x for x, r in zip(e.series, rs) if r == "top"), None)
        hechas = sum(1 for r in rs if r in ("top", "backoff", "intento"))
        real = {"peso": top.peso, "reps": top.reps} if top else None
        vol_real += e.volumen
        if not top_o or not real:
            est, pt = "hecho", 1
        else:
            pw, pr = top_o.get("peso"), top_o.get("reps") or 0
            ok_peso = pw is None or (real["peso"] or 0) >= pw
            if ok_peso and real["reps"] >= pr:
                est, pt = "cumplido", 1
            elif ok_peso or (pw and real["peso"] and real["peso"] * (1 + real["reps"] / 30) >= pw * (1 + pr / 30) * 0.97):
                est, pt = "parcial", 0.5
            else:
                est, pt = "no_cumplido", 0.25
        filas.append({"id": p["id"], "nombre": p["nombre"], "estado": est, "series_previstas": series_o,
                      "series_hechas": hechas, "objetivo": top_o, "real": real, "volumen": e.volumen,
                      "diferencia_peso": round((real["peso"] or 0) - (top_o.get("peso") or 0), 2) if real and top_o.get("peso") is not None and real["peso"] is not None else None,
                      "diferencia_reps": (real["reps"] - (top_o.get("reps") or 0)) if real and top_o.get("reps") else None})
        puntos.append(pt)
    previstos = {p["id"] for p in plan.get("ejercicios", [])}
    anadidos = [{"id": e.id, "nombre": e.nombre, "series": len(e.efectivas), "volumen": e.volumen}
                for e in sesion.ejercicios if e.series and e.id not in previstos]
    cum = round(100 * sum(puntos) / len(puntos)) if puntos else None
    return {"estado": "asociada", "sesion_id": sesion.id, "fecha": sesion.fecha, "cumplimiento": cum,
            "ejercicios": filas, "anadidos": anadidos,
            "omitidos": [f["nombre"] for f in filas if f["estado"] == "omitido"],
            "volumen_previsto": round(vol_prev, 1), "volumen_real": round(sesion.volumen, 1),
            "criterio": "cumplido = top set con el peso y las reps objetivo; parcial = peso o e1RM a ≤3 %; omitido = 0.",
            "nivel": "calculado"}


# ---------- calendario y reprogramación ----------

def musculos_sesion(sesiones: list, nombre: str) -> set[str]:
    pl = plantilla(sesiones, nombre)
    out = set()
    for x in pl["ejercicios"]:
        ap = apariciones(sesiones, x["id"])
        if ap:
            out |= set(ap[-1][1].principales)
    return out


def calendario(sesiones: list, desde: date, hasta: date, hoy: date, rutina: dict | None = None,
               planificadas: list[dict] | None = None, pausas: list[dict] | None = None) -> list[dict]:
    dias = dias_rutina(rutina)
    por_fecha = defaultdict(list)
    for s in sesiones:
        por_fecha[s.fecha].append(s)
    plan = {p["fecha"]: p for p in (planificadas or []) if p.get("estado") not in ("descartada", "sustituida")}
    movidas = {p.get("origen_fecha") for p in (planificadas or []) if p.get("origen_fecha")}
    out = []
    d = desde
    while d <= hasta:
        f = d.isoformat()
        prevista = plan.get(f, {}).get("nombre") if f in plan else (dias.get(d.weekday()) if f not in movidas else None)
        hechas = por_fecha.get(f, [])
        if hechas:
            estado = "hecho" if prevista else "extra"
        elif f in movidas:
            estado = "reprogramado"
        elif not prevista:
            estado = "descanso"
        elif plan.get(f, {}).get("estado") == "pospuesta":
            estado = "pospuesto"
        elif pausa_en(pausas, d):
            estado = "pausa"  # enfermedad, lesión o vacaciones: no es una sesión perdida ni se reprograma
        elif d < hoy:
            estado = "perdido"
        else:
            estado = "pendiente"
        out.append({"fecha": f, "dia": DIAS[d.weekday()], "prevista": prevista, "estado": estado,
                    "planificada_id": plan.get(f, {}).get("id"),
                    "hechas": [{"id": s.id, "nombre": s.nombre, "series": s.series, "volumen": s.volumen} for s in hechas]})
        d += timedelta(days=1)
    return out


def reprogramar(sesiones: list, hoy: date, rutina: dict | None = None, planificadas: list[dict] | None = None,
               pausas: list[dict] | None = None) -> list[dict]:
    """Para cada sesión perdida esta semana, busca un hueco hasta el domingo sin pegarla a otra que trabaje los mismos
    músculos principales el día antes o el día después. Si no hay hueco, propone no recuperarla."""
    lunes = _semana(hoy)
    cal = calendario(sesiones, lunes, lunes + timedelta(days=6), hoy, rutina, planificadas, pausas)
    hechas_nombres = {gs.norm(h["nombre"]) for c in cal for h in c["hechas"]}
    perdidas = [c for c in cal if c["estado"] == "perdido" and gs.norm(c["prevista"]) not in hechas_nombres]
    ocupado = {c["fecha"]: (c["prevista"] if c["estado"] in ("pendiente", "pospuesto") else
                            (c["hechas"][0]["nombre"] if c["hechas"] else None)) for c in cal}
    if any(h for c in cal if c["fecha"] == hoy.isoformat() for h in c["hechas"]):
        ocupado[hoy.isoformat()] = ocupado.get(hoy.isoformat()) or "hecho"
    props = []
    for p in perdidas:
        mus = musculos_sesion(sesiones, p["prevista"])
        hueco, motivo = None, ""
        for i in range(0, 7):
            d = hoy + timedelta(days=i)
            if d > lunes + timedelta(days=6):
                break
            f = d.isoformat()
            if ocupado.get(f):
                continue
            vecinos = [ocupado.get((d + timedelta(days=k)).isoformat()) for k in (-1, 1)]
            choque = [v for v in vecinos if v and v != "hecho" and mus & musculos_sesion(sesiones, v)]
            if choque:
                continue
            hueco = f
            motivo = (f"{DIAS[d.weekday()].capitalize()} está libre y no va pegado a otra sesión con "
                      f"{', '.join(sorted(mus)) or 'los mismos músculos'}.")
            break
        if hueco:
            ocupado[hueco] = p["prevista"]
            props.append({"tipo": "reprogramar", "sesion": p["prevista"], "desde": p["fecha"], "hasta": hueco,
                          "motivo": motivo, "nivel": "recomendacion"})
        else:
            props.append({"tipo": "omitir", "sesion": p["prevista"], "desde": p["fecha"], "hasta": None, "nivel": "recomendacion",
                          "motivo": "No hay un hueco esta semana sin juntarla con sesiones de los mismos músculos: "
                                    "mejor no recuperarla y seguir con la rutina la semana que viene."})
    return props


# ---------- observaciones (análisis de Jarvis) ----------

def ejercicios_activos(sesiones: list, hoy: date, dias: int = 42) -> list[tuple[str, str]]:
    per = gs.en_periodo(sesiones, hoy - timedelta(days=dias), hoy)
    vistos = {}
    for s in per:
        for e in s.ejercicios:
            if e.series and e.tipo != "cardio":
                vistos[e.id] = e.nombre
    return list(vistos.items())


def estancamientos(sesiones: list, hoy: date) -> list[dict]:
    out = []
    for eid, nombre in ejercicios_activos(sesiones, hoy):
        h = historial(sesiones, eid)
        h = [x for x in h if x["fecha"] >= (hoy - timedelta(weeks=10)).isoformat()]
        r = estancamiento(h, hoy)
        out.append({"id": eid, "nombre": nombre, **r})
    orden = {"retroceso": 0, "estancado": 1, "estable": 2, "progresa": 3, "pocos_datos": 4, "sin_datos": 5}
    return sorted(out, key=lambda x: (orden.get(x["estado"], 9), x["nombre"]))


def observaciones(sesiones: list, hoy: date, logs: list[dict] | None = None, perf: dict | None = None) -> list[dict]:
    obs = []
    rec = records(sesiones)
    recientes = [e for e in rec["eventos"] if e["fecha"] >= (hoy - timedelta(days=14)).isoformat()
                 and e["tipo"] in ("peso_max", "reps_con_peso")]
    if recientes:
        n_ej = len({e["ejercicio_id"] for e in recientes})
        obs.append({"id": "records", "tipo": "records", "nivel": "registrado",
                    "titulo": f"Récords reales en {n_ej} ejercicio{'s' if n_ej != 1 else ''} (14 días)",
                    "detalle": "; ".join(f"{e['nombre']}: {e['detalle']}" for e in recientes[-4:]),
                    "evidencia": [f"{e['fecha']} · {e['nombre']} · {e['detalle']}" for e in recientes]})
    est = estancamientos(sesiones, hoy)
    malos = [e for e in est if e["estado"] in ("estancado", "retroceso") and e["confianza"] != "baja"]
    for e in malos[:4]:
        obs.append({"id": f"estanc-{e['id']}", "tipo": e["estado"], "nivel": "inferencia",
                    "titulo": f"{e['nombre']}: {'estancado' if e['estado'] == 'estancado' else 'retroceso'} (confianza {e['confianza']})",
                    "detalle": e["propuestas"][0] if e["propuestas"] else "", "evidencia": e["evidencia"],
                    "propuestas": e["propuestas"], "ejercicio_id": e["id"]})
    buenos = [e for e in est if e["estado"] == "progresa"]
    if buenos:
        obs.append({"id": "progresos", "tipo": "progreso", "nivel": "calculado",
                    "titulo": f"Progresan {len(buenos)} ejercicios",
                    "detalle": ", ".join(e["nombre"] for e in buenos[:6]),
                    "evidencia": [f"{e['nombre']}: {e['evidencia'][-1]}" for e in buenos[:6] if e["evidencia"]]})
    mus = musculos(sesiones, hoy, 4)
    completas = [m for m in mus["musculos"] if m["media_semanal"]]
    if completas:
        bajos = sorted(completas, key=lambda m: m["media_semanal"])[:3]
        obs.append({"id": "musculos-bajos", "tipo": "musculos", "nivel": "calculado",
                    "titulo": "Grupos menos trabajados (media de las semanas completas)",
                    "detalle": ", ".join(f"{m['musculo']} {m['media_semanal']:g} series/sem" for m in bajos),
                    "evidencia": [f"{m['musculo']}: " + ", ".join(f"{w['semana'][5:]} {w['ponderadas']:g}" for w in m["semanas"]) for m in bajos]})
    sin = [m for m in mus["musculos"] if m["ultima"] and (hoy - date.fromisoformat(m["ultima"])).days > 10]
    if sin:
        obs.append({"id": "sin-trabajar", "tipo": "musculos", "nivel": "calculado",
                    "titulo": "Más de 10 días sin trabajar como principal",
                    "detalle": ", ".join(f"{m['musculo']} (desde {m['ultima']})" for m in sin),
                    "evidencia": [f"{m['musculo']}: última vez {m['ultima']}" for m in sin]})
    # cambios de volumen
    sem = []
    for i in range(4, 0, -1):
        ini = _semana(hoy) - timedelta(weeks=i)
        sem.append(round(sum(s.volumen for s in gs.en_periodo(sesiones, ini, ini + timedelta(days=6))), 1))
    if all(sem[:3]) and sem[3]:
        media = sum(sem[:3]) / 3
        cambio = round(100 * (sem[3] - media) / media)
        if abs(cambio) >= 25:
            obs.append({"id": "volumen", "tipo": "volumen", "nivel": "calculado",
                        "titulo": f"Volumen de la semana del {(_semana(hoy) - timedelta(weeks=1)).strftime('%d/%m')}: "
                                  f"{'+' if cambio > 0 else ''}{cambio} % frente a las 3 anteriores",
                        "detalle": "Un salto brusco de volumen dificulta recuperar; una bajada puede ser descarga o semana incompleta.",
                        "evidencia": [f"Semanas: {', '.join(f'{v:g} kg' for v in sem)}"]})
    # variabilidad de ejercicios
    for nombre in set(RUTINA_DEFECTO.values()):
        ult = [s for s in sesiones if mismo_nombre(s.nombre, nombre)][-3:]
        if len(ult) == 3:
            sets = [{e.id for e in s.ejercicios if e.series} for s in ult]
            comunes = set.intersection(*sets)
            total = set.union(*sets)
            if total and len(comunes) / len(total) < 0.5:
                obs.append({"id": f"variacion-{gs.slug(nombre)}", "tipo": "rutina", "nivel": "inferencia",
                            "titulo": f"{nombre}: muchos cambios de ejercicios",
                            "detalle": f"Solo {len(comunes)} de {len(total)} ejercicios se repiten en las últimas 3 sesiones. "
                                       "Fija 1–2 compuestos y 3–4 accesorios 6 semanas para poder medir la progresión.",
                            "evidencia": [f"{s.fecha}: " + ", ".join(e.nombre for e in s.ejercicios if e.series) for s in ult]})
    zonas = molestias(perf or {}, logs or [], hoy)
    if zonas:
        obs.append({"id": "molestias", "tipo": "recuperacion", "nivel": "registrado",
                    "titulo": "Molestias activas: " + ", ".join(z["zona"] for z in zonas),
                    "detalle": "Los objetivos de los ejercicios que cargan esa zona van sin fallo y sin subir carga.",
                    "evidencia": [f"{z['fuente']}: {z['detalle']}" for z in zonas]})
    rc = recuperacion(sesiones, logs or [], hoy)
    altos = [m for m in rc["musculos"] if m["estado"] == "carga_alta"]
    if altos:
        obs.append({"id": "carga-alta", "tipo": "recuperacion", "nivel": "inferencia",
                    "titulo": "Carga reciente alta en " + ", ".join(m["musculo"] for m in altos),
                    "detalle": "Más de 1,5× la media de las 3 semanas anteriores. Vigila sensaciones y rendimiento.",
                    "evidencia": [f"{m['musculo']}: {m['series_7d']:g} series en 7 días frente a {m['media_semanal_previa']:g}/semana" for m in altos]})
    return obs


def consistencia(sesiones: list, hoy: date, rutina: dict | None = None, semanas: int = 4) -> dict:
    previstas_sem = len(dias_rutina(rutina))
    out = []
    for i in range(semanas, 0, -1):
        ini = _semana(hoy) - timedelta(weeks=i)
        n = len(gs.en_periodo(sesiones, ini, ini + timedelta(days=6)))
        out.append({"semana": ini.isoformat(), "hechas": n, "previstas": previstas_sem})
    hechas = sum(x["hechas"] for x in out)
    return {"semanas": out, "porcentaje": round(100 * min(hechas, previstas_sem * semanas) / (previstas_sem * semanas)) if previstas_sem else None,
            "media_semanal": round(hechas / semanas, 1), "nivel": "calculado",
            "criterio": f"Sesiones hechas frente a las {previstas_sem} previstas por semana (semanas completas)."}


# ---------- decisiones: evaluación posterior ----------

def evaluar_decision(dec: dict, sesiones: list) -> dict | None:
    """Comprueba si una decisión sobre un ejercicio funcionó, con la primera sesión de ese ejercicio desde su fecha."""
    eid = dec.get("ejercicio_id")
    obj = (dec.get("objetivo") or {})
    if not eid or not obj:
        return None
    desde = dec.get("fecha_aplicacion") or dec.get("fecha")
    h = [x for x in historial(sesiones, eid) if x["fecha"] >= desde and x["top"]]
    if not h:
        return {"estado": "pendiente", "texto": "Aún no hay una sesión de ese ejercicio después de la decisión."}
    t = h[0]["top"]
    pw, pr = obj.get("peso"), obj.get("reps") or 0
    if (pw is None or (t["peso"] or 0) >= pw) and t["reps"] >= pr:
        est = "cumplido"
    elif pw is not None and t["peso"] is not None and t["peso"] >= pw:
        est = "parcial"
    else:
        est = "no_cumplido"
    return {"estado": est, "fecha": h[0]["fecha"], "real": {"peso": t["peso"], "reps": t["reps"]},
            "texto": f"{h[0]['fecha']}: {_fmt(t)} frente al objetivo {pw if pw is not None else 'PC'}×{pr}"}


# ---------- informes ----------

def informe(sesiones: list, tipo: str, desde: date, hasta: date, rutina: dict | None = None,
            planificadas: list[dict] | None = None, decisiones: list[dict] | None = None,
            versiones_rutina: list[dict] | None = None, logs: list[dict] | None = None, perf: dict | None = None,
            pausas: list[dict] | None = None) -> dict:
    per = gs.en_periodo(sesiones, desde, hasta)
    antes = [s for s in sesiones if s.fecha < desde.isoformat()]
    cal = calendario(sesiones, desde, hasta, hasta + timedelta(days=1), rutina, planificadas, pausas)
    previstas = sum(1 for c in cal if c["prevista"] and c["estado"] != "pausa")  # los días de pausa no cuentan
    hechas_previstas = sum(1 for c in cal if c["prevista"] and c["hechas"])
    musc = gs.series_por_musculo(per)
    # progresos y retrocesos: última del periodo frente a la anterior a esa
    prog, retro = [], []
    for eid, nombre in {(e.id, e.nombre) for s in per for e in s.ejercicios if e.series and e.tipo != "cardio"}:
        h = [x for x in historial(sesiones, eid) if x["fecha"] <= hasta.isoformat() and x["top"]]
        dentro = [x for x in h if x["fecha"] >= desde.isoformat()]
        fuera = [x for x in h if x["fecha"] < desde.isoformat()]
        if not dentro or not fuera:
            continue
        a, b = rendimiento(fuera[-1]["top"]), rendimiento(dentro[-1]["top"])
        if not a or not b:
            continue
        pct = round(100 * (b - a) / a, 1)
        fila = {"id": eid, "nombre": nombre, "antes": _fmt(fuera[-1]["top"]), "ahora": _fmt(dentro[-1]["top"]), "cambio_pct": pct}
        if pct >= 1:
            prog.append(fila)
        elif pct <= -3:
            retro.append(fila)
    rec = [e for e in records(sesiones)["eventos"] if desde.isoformat() <= e["fecha"] <= hasta.isoformat()]
    est = [e for e in estancamientos([s for s in sesiones if s.fecha <= hasta.isoformat()], hasta)
           if e["estado"] in ("estancado", "retroceso")]
    sig = proponer_sesion([s for s in sesiones if s.fecha <= hasta.isoformat()], hasta + timedelta(days=1), rutina,
                          logs=logs, perf=perf, pausas=pausas)
    data = {
        "tipo": tipo, "desde": desde.isoformat(), "hasta": hasta.isoformat(),
        "sesiones_hechas": len(per), "sesiones_previstas": previstas,
        "dias_en_pausa": sum(1 for c in cal if c["estado"] == "pausa"),
        "pausas": [{"desde": p["desde"], "hasta": p.get("hasta"), "motivo": p.get("motivo")} for p in pausas or []
                   if p["desde"] <= hasta.isoformat() and (p.get("hasta") or "9999-12-31") >= desde.isoformat()],
        "cumplimiento": round(100 * hechas_previstas / previstas) if previstas else None,
        "sesiones": [{"id": s.id, "fecha": s.fecha, "nombre": s.nombre, "series": s.series, "volumen": s.volumen} for s in per],
        "volumen_kg": round(sum(s.volumen for s in per), 1), "series": sum(s.series for s in per),
        "series_por_musculo": {k: round(v, 1) for k, v in sorted(musc.items(), key=lambda kv: -kv[1])},
        "progresos": sorted(prog, key=lambda x: -x["cambio_pct"]), "retrocesos": sorted(retro, key=lambda x: x["cambio_pct"]),
        "records": rec, "estancados": [{"id": e["id"], "nombre": e["nombre"], "estado": e["estado"],
                                        "confianza": e["confianza"]} for e in est],
        "analisis": observaciones([s for s in sesiones if s.fecha <= hasta.isoformat()], hasta, logs, perf),
        "recomendaciones": [f"{e['nombre']}: {e['objetivo']['motivo']}" for e in (sig or {}).get("ejercicios", [])
                            if e["categoria"] in ("compuesto", "maquina")][:4],
    }
    if tipo == "mensual":
        prev_ini = (desde - timedelta(days=1)).replace(day=1)
        prev = gs.en_periodo(sesiones, prev_ini, desde - timedelta(days=1))
        mp = gs.series_por_musculo(prev)
        semanas = []
        d = _semana(desde)
        while d <= hasta:
            p = gs.en_periodo(sesiones, max(d, desde), min(d + timedelta(days=6), hasta))
            semanas.append({"semana": d.isoformat(), "sesiones": len(p), "series": sum(s.series for s in p),
                            "volumen": round(sum(s.volumen for s in p), 1)})
            d += timedelta(weeks=1)
        data |= {
            "semanas": semanas,
            "evolucion_muscular": {g: {"mes": round(musc.get(g, 0), 1), "mes_anterior": round(mp.get(g, 0), 1)}
                                   for g in gs._reglas()["grupos"]},
            "volumen_mes_anterior": round(sum(s.volumen for s in prev), 1),
            "cambios_rutina": [v for v in (versiones_rutina or []) if desde.isoformat() <= v.get("fecha", "")[:10] <= hasta.isoformat()],
            "decisiones": [d | {"evaluacion": evaluar_decision(d, sesiones)} for d in (decisiones or [])
                           if desde.isoformat() <= (d.get("fecha") or "")[:10] <= hasta.isoformat()],
            "objetivos_proximo_mes": _objetivos_mes(prog, retro, est, previstas, len(per)),
        }
    data["texto"] = texto_informe(data)
    return data


def _objetivos_mes(prog, retro, est, previstas, hechas) -> list[str]:
    o = []
    if previstas and hechas < previstas:
        o.append(f"Consistencia: completar las sesiones previstas (este mes {hechas}/{previstas}).")
    for e in est[:3]:
        o.append(f"{e['nombre']}: romper el {e['estado']} ({e['propuestas'][0].lower() if e.get('propuestas') else 'revisar'}).")
    for p in prog[:2]:
        o.append(f"{p['nombre']}: mantener la progresión (ahora {p['ahora']}).")
    return o or ["Mantener la rutina y la doble progresión en los compuestos."]


def texto_informe(d: dict) -> str:
    """Resumen corto (para Telegram), solo con datos del informe."""
    t = "Semana" if d["tipo"] == "semanal" else "Mes"
    lin = [f"🏋️ {t} {d['desde']} → {d['hasta']}",
           f"Sesiones: {d['sesiones_hechas']}" + (f"/{d['sesiones_previstas']} ({d['cumplimiento']} %)" if d["sesiones_previstas"] else ""),
           f"Series efectivas: {d['series']} · volumen: {d['volumen_kg']:g} kg"]
    if d["records"]:
        lin.append("Récords: " + "; ".join(f"{r['nombre']} {r['detalle']}" for r in d["records"][:3]))
    if d["progresos"]:
        lin.append("Suben: " + ", ".join(f"{p['nombre']} {p['cambio_pct']:+g} %" for p in d["progresos"][:3]))
    if d["retrocesos"]:
        lin.append("Bajan: " + ", ".join(f"{p['nombre']} {p['cambio_pct']:+g} %" for p in d["retrocesos"][:3]))
    if d["estancados"]:
        lin.append("Estancados: " + ", ".join(e["nombre"] for e in d["estancados"][:3]))
    if d.get("recomendaciones"):
        lin.append("Siguiente: " + d["recomendaciones"][0])
    return "\n".join(lin)


# ---------- resumen general (Overview) ----------

def overview(sesiones: list, hoy: date, rutina: dict | None = None, ajustes: dict | None = None,
             logs: list[dict] | None = None, perf: dict | None = None, planificadas: list[dict] | None = None,
             duraciones: dict | None = None) -> dict:
    lunes = _semana(hoy)
    mes = hoy.replace(day=1)
    sem = gs.en_periodo(sesiones, lunes, hoy)
    mes_s = gs.en_periodo(sesiones, mes, hoy)
    ult7 = gs.en_periodo(sesiones, hoy - timedelta(days=6), hoy)
    rec = records(sesiones)
    est = estancamientos(sesiones, hoy)
    return {
        "hoy": hoy.isoformat(),
        "ultima": ({"id": sesiones[-1].id, "fecha": sesiones[-1].fecha, "nombre": sesiones[-1].nombre,
                    "series": sesiones[-1].series, "volumen": sesiones[-1].volumen,
                    "duracion_min": (duraciones or {}).get(sesiones[-1].id)} if sesiones else None),
        "semana": {"sesiones": len(sem), "previstas": len(dias_rutina(rutina)), "series": sum(s.series for s in sem),
                   "volumen": round(sum(s.volumen for s in sem), 1), "desde": lunes.isoformat()},
        "mes": {"sesiones": len(mes_s), "series": sum(s.series for s in mes_s),
                "volumen": round(sum(s.volumen for s in mes_s), 1), "desde": mes.isoformat()},
        "mes_anterior": (lambda p: {"sesiones": len(p), "series": sum(s.series for s in p),
                                    "volumen": round(sum(s.volumen for s in p), 1),
                                    "desde": (mes - timedelta(days=1)).replace(day=1).isoformat()})(
            gs.en_periodo(sesiones, (mes - timedelta(days=1)).replace(day=1), mes - timedelta(days=1))),
        "ultimos_7": {"sesiones": len(ult7), "series": sum(s.series for s in ult7), "volumen": round(sum(s.volumen for s in ult7), 1)},
        "records_recientes": [e for e in rec["eventos"] if e["fecha"] >= (hoy - timedelta(days=30)).isoformat()][-8:][::-1],
        "progresan": [{"id": e["id"], "nombre": e["nombre"]} for e in est if e["estado"] == "progresa"],
        "estancados": [{"id": e["id"], "nombre": e["nombre"], "estado": e["estado"], "confianza": e["confianza"]}
                       for e in est if e["estado"] in ("estancado", "retroceso")],
        "consistencia": consistencia(sesiones, hoy, rutina),
        "siguiente": proponer_sesion(sesiones, hoy, rutina, ajustes, logs, perf, planificadas=planificadas,
                                     duraciones=duraciones),
        "analisis": observaciones(sesiones, hoy, logs, perf),
        "niveles": NIVELES,
    }


# ---------- CLI para Jarvis ----------

def _cli(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Entrenador del gym (datos de Gym.md)")
    ap.add_argument("comando", choices=["siguiente", "objetivo", "estancados", "records", "musculos", "recuperacion", "analisis"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--dias", type=int, default=30)
    ap.add_argument("--semanas", type=int, default=4)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    hoy = datetime.now().date()
    ses = gs.cargar()
    perf = perfil()
    if not ses:
        sys.exit("No hay sesiones en Gym.md")
    out = None
    if a.comando == "siguiente":
        out = proponer_sesion(ses, hoy, perf=perf)
        if not a.json and out:
            print(f"{out['nombre']} · {out['dia']} {out['fecha']} · ~{out['duracion_estimada_min']} min (estimación). {out['justificacion']}")
            for e in out["ejercicios"]:
                o = e["objetivo"]
                t = o.get("top") or {}
                bo = ", ".join(f"{b['peso']:g}×{b['reps']}" for b in o.get("backoffs", []) if b.get("peso"))
                peso = "PC" if t.get("peso") is None else f"{t['peso']:g}"
                print(f"- {e['nombre']}: top {peso}×{t.get('reps', '?')}"
                      + (f", back-offs {bo}" if bo else "") + f". {o['motivo']}")
            print("Recomendación del motor (no planificada hasta que la aceptes en el panel).")
            return
    elif a.comando == "objetivo":
        if not a.arg:
            sys.exit("Falta el ejercicio")
        d = gs.buscar_ejercicio(ses, a.arg)
        if not d:
            sys.exit(f"No encuentro «{a.arg}»")
        ap_ = apariciones(ses, d["id"])
        cfg = config(d["id"], d["nombre"], ap_)
        zona = afectado(d["principales"], d["secundarios"], molestias(perf, [], hoy))
        out = objetivo(historial(ses, d["id"]), cfg, zona)
        if not a.json:
            print(f"{d['nombre']} ({cfg['categoria']}, {cfg['rep_min']}–{cfg['rep_max']} reps, +{cfg['incremento_kg']:g} kg): {out['motivo']}")
            return
    elif a.comando == "estancados":
        out = [e for e in estancamientos(ses, hoy) if e["estado"] in ("estancado", "retroceso", "progresa")]
        if not a.json:
            for e in out:
                print(f"- {e['nombre']}: {e['estado']} (confianza {e['confianza']}). " + (e["propuestas"][0] if e["propuestas"] else ""))
            return
    elif a.comando == "records":
        r = records(ses)
        out = [e for e in r["eventos"] if e["fecha"] >= (hoy - timedelta(days=a.dias)).isoformat()]
        if not a.json:
            for e in out:
                print(f"- {e['fecha']} {e['nombre']}: {e['detalle']}{' (estimado)' if e['nivel'] == 'estimacion' else ''}")
            return
    elif a.comando == "musculos":
        out = musculos(ses, hoy, a.semanas)
        if not a.json:
            for m in out["musculos"]:
                print(f"- {m['musculo']}: {m['media_semanal']:g} series/sem (directas+0,5×indirectas), "
                      f"frecuencia {m['frecuencia_media']:g}/sem, tendencia {m['tendencia'] or '—'}, última {m['ultima'] or '—'}")
            return
    elif a.comando == "recuperacion":
        out = recuperacion(ses, [], hoy, molestias(perf, [], hoy))
        if not a.json:
            print(out["aviso"])
            for m in out["musculos"]:
                print(f"- {m['musculo']}: {m['estado']}, {m['series_7d']:g} series en 7 días (media previa {m['media_semanal_previa']:g}), "
                      f"última {m['ultima'] or '—'}")
            return
    elif a.comando == "analisis":
        out = observaciones(ses, hoy, [], perf)
        if not a.json:
            for o in out:
                print(f"- [{o['nivel']}] {o['titulo']}: {o['detalle']}")
            return
    print(json.dumps(out, ensure_ascii=False, default=str))


if __name__ == "__main__":
    _cli()
