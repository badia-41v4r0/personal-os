"""Análisis del gym a partir de Jarvis/Areas/Gym.md (la fuente de verdad). Solo librería estándar.

Lo usan el Control Center (importando el módulo) y Jarvis (por línea de comandos):
  python3 gym_stats.py resumen [--dias 7]          sesiones, series, volumen y músculos del periodo
  python3 gym_stats.py ejercicio "press banca"     historial y progresión de un ejercicio (búsqueda aproximada)
  python3 gym_stats.py musculo pecho               última vez y series de las últimas 1 y 4 semanas
  python3 gym_stats.py progreso [--dias 28]        qué ejercicios mejoran, se estancan o empeoran (e1RM)
  python3 gym_stats.py hoy                         sesión de hoy según la rutina y músculos menos trabajados
  Añade --json para la salida estructurada.

Reglas (documentadas también en control-center/docs/gym.md):
- Serie efectiva = toda serie no marcada como calentamiento «(cal.)».
- Volumen (tonelaje) = Σ peso×reps de las series efectivas con peso. Las de peso corporal (PC) no suman kg.
- Series por músculo: 1 por serie efectiva para los principales y 0,5 para los secundarios (gym_musculos.json).
- e1RM (estimación, fórmula de Epley) = peso × (1 + reps/30), solo con 1–12 reps. Es una ESTIMACIÓN.
- No se rellena nada: si una línea no se entiende, se conserva tal cual en `raw` y no suma.
"""
import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
MUSCULOS = HERE / "gym_musculos.json"
RUTINA = {0: "Leg day", 1: "Push", 2: "Pull", 3: "Lower", 4: "Upper"}

SESION_RE = re.compile(r"^###\s*(\d{4}-\d{2}-\d{2})\s*·\s*(.+?)\s*$")
EJ_RE = re.compile(r"^-\s+([^:*][^:]*?):\s*(.*)$")
SERIE_RE = re.compile(
    r"(?P<peso>PC|\d+(?:[.,]\d+)?)\s*[×x]\s*(?P<reps>\d+)"
    r"(?P<flags>(?:\s*\((?:cal\.|fallo|drop)\))*)"
    r"(?:\s*RPE\s*(?P<rpe>\d+(?:[.,]\d+)?))?",
    re.I,
)


def gym_md() -> Path:
    try:
        from lib import JARVIS  # contenedor o host, según lib.py
        return JARVIS / "Areas" / "Gym.md"
    except Exception:  # noqa: BLE001
        return HERE.parent / "Jarvis-Vault/Jarvis/Areas/Gym.md"


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s.lower()).strip()


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", norm(s)).strip("-")


@dataclass
class Serie:
    peso: float | None  # None = peso corporal
    reps: int
    calentamiento: bool = False
    fallo: bool = False
    drop: bool = False
    rpe: float | None = None

    @property
    def efectiva(self) -> bool:
        return not self.calentamiento

    @property
    def volumen(self) -> float:
        return (self.peso or 0) * self.reps if self.efectiva else 0.0

    @property
    def e1rm(self) -> float | None:
        if not self.efectiva or not self.peso or not 1 <= self.reps <= 12:
            return None
        return round(self.peso * (1 + self.reps / 30), 1)


@dataclass
class Ejercicio:
    nombre: str
    id: str
    series: list[Serie]
    notas: str
    raw: str
    principales: list[str] = field(default_factory=list)
    secundarios: list[str] = field(default_factory=list)
    tipo: str = "fuerza"

    @property
    def efectivas(self) -> list[Serie]:
        return [s for s in self.series if s.efectiva]

    @property
    def volumen(self) -> float:
        return round(sum(s.volumen for s in self.series), 1)

    @property
    def mejor(self) -> Serie | None:
        cands = [s for s in self.efectivas if s.e1rm]
        return max(cands, key=lambda s: s.e1rm) if cands else None


@dataclass
class Sesion:
    fecha: str
    nombre: str
    hevy: str
    ejercicios: list[Ejercicio]
    id: str = ""
    fuente: str = "Jarvis/Areas/Gym.md"
    linea: int = 0

    @property
    def series(self) -> int:
        return sum(len(e.efectivas) for e in self.ejercicios)

    @property
    def volumen(self) -> float:
        return round(sum(e.volumen for e in self.ejercicios), 1)


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def _reglas() -> dict:
    return json.loads(MUSCULOS.read_text(encoding="utf-8"))


def clasificar(nombre: str, cfg: dict | None = None) -> tuple[str, list[str], list[str]]:
    cfg = cfg or _reglas()
    n = norm(nombre)
    for r in cfg["reglas"]:
        if r["contiene"] in n:
            return r.get("tipo", "fuerza"), r["principales"], r["secundarios"]
    return "fuerza", [], []


def parse_ejercicio(nombre: str, resto: str, cfg: dict) -> Ejercicio:
    series, fin = [], 0
    for m in SERIE_RE.finditer(resto):
        # Solo series al principio o separadas por comas (no números sueltos dentro de las notas)
        if resto[fin:m.start()].strip(" ,") and series:
            break
        if not series and resto[:m.start()].strip():
            break
        flags = (m["flags"] or "").lower()
        series.append(Serie(peso=None if m["peso"].upper() == "PC" else _num(m["peso"]), reps=int(m["reps"]),
                            calentamiento="cal." in flags, fallo="fallo" in flags, drop="drop" in flags,
                            rpe=_num(m["rpe"]) if m["rpe"] else None))
        fin = m.end()
    notas = resto[fin:].strip(" ,") if series else resto.strip()
    notas = re.sub(r"^\((.*)\)$", r"\1", notas).strip()
    canon = norm(nombre)
    canon = cfg.get("alias", {}).get(canon, canon)
    # Correcciones del panel: alias_id (nombre normalizado -> id de ejercicio) y músculos por id
    eid = cfg.get("alias_id", {}).get(norm(nombre)) or slug(canon)
    tipo, pri, sec = clasificar(nombre, cfg)
    if eid in cfg.get("musculos_id", {}):
        o = cfg["musculos_id"][eid]
        pri, sec = list(o.get("principales", pri)), list(o.get("secundarios", sec))
    return Ejercicio(nombre=nombre.strip(), id=eid, series=series, notas=notas,
                     raw=f"{nombre}: {resto}", principales=pri, secundarios=sec,
                     tipo=tipo if series or tipo == "cardio" else "otro")


def cargar(path: Path | None = None, extra: dict | None = None) -> list[Sesion]:
    """extra: correcciones del panel ({"alias_id": {...}, "musculos_id": {...}}), se suman a gym_musculos.json."""
    path = path or gym_md()
    if not path.exists():
        return []
    cfg = _reglas() | (extra or {})
    out: list[Sesion] = []
    actual: Sesion | None = None
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        m = SESION_RE.match(line)
        if m:
            actual = Sesion(fecha=m[1], nombre=m[2], hevy="", ejercicios=[], linea=i)
            out.append(actual)
        elif line.startswith("#"):
            actual = None
        elif actual is not None:
            s = line.strip()
            if s.startswith("_Hevy:"):
                actual.hevy = s.strip("_").removeprefix("Hevy:").strip()
            elif (e := EJ_RE.match(s)):
                actual.ejercicios.append(parse_ejercicio(e[1], e[2], cfg))
    # Id estable: fecha + nombre (+ n si hubiera dos el mismo día). Sin duplicados.
    vistos: dict[str, int] = defaultdict(int)
    for s in out:
        base = f"{s.fecha}-{slug(s.nombre)}"
        vistos[base] += 1
        s.id = base if vistos[base] == 1 else f"{base}-{vistos[base]}"
    return sorted(out, key=lambda s: s.fecha)


# ---------- análisis ----------

def en_periodo(sesiones: list[Sesion], desde: date, hasta: date | None = None) -> list[Sesion]:
    h = (hasta or date.max).isoformat()
    return [s for s in sesiones if desde.isoformat() <= s.fecha <= h]


def series_por_musculo(sesiones: list[Sesion]) -> dict[str, float]:
    tot: dict[str, float] = defaultdict(float)
    for s in sesiones:
        for e in s.ejercicios:
            n = len(e.efectivas)
            for m in e.principales:
                tot[m] += n
            for m in e.secundarios:
                tot[m] += 0.5 * n
    return dict(tot)


def ejercicios_indice(sesiones: list[Sesion]) -> list[dict]:
    idx: dict[str, dict] = {}
    for s in sesiones:
        for e in s.ejercicios:
            d = idx.setdefault(e.id, {"id": e.id, "nombre": e.nombre, "nombres": set(), "sesiones": 0, "series": 0,
                                      "volumen": 0.0, "ultima": s.fecha, "principales": e.principales,
                                      "secundarios": e.secundarios, "tipo": e.tipo, "mejor_e1rm": None})
            d["nombres"].add(e.nombre)
            d["sesiones"] += 1
            d["series"] += len(e.efectivas)
            d["volumen"] = round(d["volumen"] + e.volumen, 1)
            d["ultima"] = max(d["ultima"], s.fecha)
            b = e.mejor
            if b and (d["mejor_e1rm"] is None or b.e1rm > d["mejor_e1rm"]):
                d["mejor_e1rm"] = b.e1rm
    for d in idx.values():
        d["nombres"] = sorted(d["nombres"])
    return sorted(idx.values(), key=lambda d: (-d["sesiones"], d["nombre"]))


def historial_ejercicio(sesiones: list[Sesion], ej_id: str) -> list[dict]:
    out = []
    for s in sesiones:
        for e in s.ejercicios:
            if e.id != ej_id:
                continue
            b = e.mejor
            ef = e.efectivas
            out.append({"fecha": s.fecha, "sesion": s.nombre, "sesion_id": s.id, "nombre": e.nombre,
                        "series": [asdict(x) | {"e1rm": x.e1rm, "volumen": x.volumen} for x in e.series],
                        "series_efectivas": len(ef), "volumen": e.volumen,
                        "peso_max": max((x.peso for x in ef if x.peso), default=None),
                        "reps_total": sum(x.reps for x in ef),
                        "mejor_serie": asdict(b) | {"e1rm": b.e1rm} if b else None, "notas": e.notas})
    return out


def tendencia(hist: list[dict]) -> dict:
    pts = [(h["fecha"], h["mejor_serie"]["e1rm"]) for h in hist if h["mejor_serie"]]
    if len(pts) < 2:
        return {"estado": "pocos datos", "cambio_pct": None, "desde": pts[0][0] if pts else None}
    first, last = pts[0][1], pts[-1][1]
    pct = round(100 * (last - first) / first, 1)
    estado = "mejora" if pct >= 2.5 else "empeora" if pct <= -2.5 else "estable"
    return {"estado": estado, "cambio_pct": pct, "desde": pts[0][0], "hasta": pts[-1][0],
            "e1rm_inicio": first, "e1rm_fin": last}


def buscar_ejercicio(sesiones: list[Sesion], texto: str) -> dict | None:
    q = set(norm(texto).split())
    q |= {w[:-1] for w in q if w.endswith("s") and len(w) > 3}  # plurales: «dominadas» → «dominada»
    best, score = None, 0
    for d in ejercicios_indice(sesiones):
        palabras = set(norm(" ".join(d["nombres"])).replace("(", " ").replace(")", " ").split())
        # coincidencias, +2 si el texto está entero en el nombre, −0,1 por cada palabra de más (así «press de
        # banca» prefiere «Press de Banca (Barra)» a «Press de Banca Inclinado (Mancuerna)»)
        nom = set(norm(d["nombre"]).replace("(", " ").replace(")", " ").split())
        sc = len(q & palabras) + (2 if norm(texto) in norm(d["nombre"]) else 0) - 0.1 * len(nom - q) if q & palabras else 0
        if sc > score or (sc == score and best and d["sesiones"] > best["sesiones"]):
            best, score = d, sc
    return best if score else None


def resumen(sesiones: list[Sesion], dias: int, hoy: date) -> dict:
    per = en_periodo(sesiones, hoy - timedelta(days=dias - 1), hoy)
    musc = series_por_musculo(per)
    grupos = _reglas()["grupos"]
    return {"desde": (hoy - timedelta(days=dias - 1)).isoformat(), "hasta": hoy.isoformat(), "sesiones": len(per),
            "series": sum(s.series for s in per), "volumen_kg": round(sum(s.volumen for s in per), 1),
            "musculos": {g: round(musc.get(g, 0), 1) for g in grupos},
            "ultima": per[-1].fecha if per else (sesiones[-1].fecha if sesiones else None),
            "duracion": None, "nota_duracion": "Gym.md no guarda la duración de las sesiones"}


def ultima_vez(sesiones: list[Sesion], musculo: str) -> dict:
    m = norm(musculo)
    for s in reversed(sesiones):
        for e in s.ejercicios:
            if m in e.principales and e.efectivas:
                return {"fecha": s.fecha, "sesion": s.nombre, "ejercicio": e.nombre}
    return {}


def progreso(sesiones: list[Sesion], dias: int, hoy: date) -> list[dict]:
    per = en_periodo(sesiones, hoy - timedelta(days=dias - 1), hoy)
    out = []
    for d in ejercicios_indice(per):
        t = tendencia(historial_ejercicio(per, d["id"]))
        if t["cambio_pct"] is not None:
            out.append({"id": d["id"], "nombre": d["nombre"], **t})
    return sorted(out, key=lambda x: -x["cambio_pct"])


def sugerencia_hoy(sesiones: list[Sesion], hoy: date) -> dict:
    sesion = RUTINA.get(hoy.weekday())
    semana = resumen(sesiones, 7, hoy)["musculos"]
    menos = sorted(semana.items(), key=lambda kv: kv[1])[:4]
    anterior = next((s for s in reversed(sesiones) if s.nombre.lower() == (sesion or "").lower() and s.fecha < hoy.isoformat()), None)
    return {"rutina": sesion or "descanso", "anterior": anterior.fecha if anterior else None,
            "menos_trabajados_7d": [{"musculo": k, "series": v} for k, v in menos]}


def firma(path: Path | None = None) -> str:
    p = path or gym_md()
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.exists() else ""


# ---------- CLI para Jarvis ----------

def _fmt_serie(s: dict) -> str:
    p = "PC" if s["peso"] is None else f"{s['peso']:g}"
    return f"{p}×{s['reps']}"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("comando", choices=["resumen", "ejercicio", "musculo", "progreso", "hoy"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--dias", type=int, default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    hoy = date.today()
    ses = cargar()
    if not ses:
        sys.exit("No hay sesiones en Gym.md")

    if a.comando == "resumen":
        r = resumen(ses, a.dias or 7, hoy)
        if a.json:
            return print(json.dumps(r, ensure_ascii=False))
        mus = ", ".join(f"{k} {v:g}" for k, v in sorted(r["musculos"].items(), key=lambda kv: -kv[1]))
        print(f"{r['desde']} → {r['hasta']}: {r['sesiones']} sesiones, {r['series']} series efectivas, "
              f"{r['volumen_kg']:g} kg de volumen. Series por músculo (secundarios ×0,5): {mus}. "
              "Duración: no registrada.")
    elif a.comando == "ejercicio":
        if not a.arg:
            sys.exit("Falta el nombre del ejercicio")
        d = buscar_ejercicio(ses, a.arg)
        if not d:
            sys.exit(f"No encuentro «{a.arg}» en Gym.md")
        per = en_periodo(ses, hoy - timedelta(days=a.dias - 1)) if a.dias else ses
        h = historial_ejercicio(per, d["id"])
        t = tendencia(h)
        if a.json:
            return print(json.dumps({"ejercicio": d, "historial": h, "tendencia": t}, ensure_ascii=False))
        print(f"{d['nombre']} — {len(h)} sesiones, última {d['ultima']}. "
              f"Tendencia del e1RM estimado: {t['estado']}" + (f" ({t['cambio_pct']:+g} %)" if t["cambio_pct"] is not None else ""))
        for x in h[-8:]:
            b = x["mejor_serie"]
            print(f"- {x['fecha']} ({x['sesion']}): {', '.join(_fmt_serie(s) + (' cal.' if s['calentamiento'] else '') for s in x['series'])}"
                  + (f" · mejor {_fmt_serie(b)} ≈ e1RM {b['e1rm']:g} kg" if b else ""))
    elif a.comando == "musculo":
        if not a.arg:
            sys.exit("Falta el grupo muscular")
        u = ultima_vez(ses, a.arg)
        s7 = resumen(ses, 7, hoy)["musculos"].get(norm(a.arg), 0)
        s28 = resumen(ses, 28, hoy)["musculos"].get(norm(a.arg), 0)
        if a.json:
            return print(json.dumps({"ultima": u, "series_7d": s7, "series_28d": s28}, ensure_ascii=False))
        print((f"Última vez como músculo principal: {u['fecha']} ({u['sesion']}, {u['ejercicio']}). " if u else "Sin registros como músculo principal. ")
              + f"Series: {s7:g} en 7 días, {s28:g} en 28 días.")
    elif a.comando == "progreso":
        p = progreso(ses, a.dias or 28, hoy)
        if a.json:
            return print(json.dumps(p, ensure_ascii=False))
        for x in p:
            print(f"- {x['nombre']}: {x['estado']} ({x['cambio_pct']:+g} %, e1RM {x['e1rm_inicio']:g} → {x['e1rm_fin']:g} kg, {x['desde']}→{x['hasta']})")
    elif a.comando == "hoy":
        r = sugerencia_hoy(ses, hoy)
        if a.json:
            return print(json.dumps(r, ensure_ascii=False))
        menos = ", ".join(f"{m['musculo']} ({m['series']:g})" for m in r["menos_trabajados_7d"])
        print(f"Hoy toca: {r['rutina']}" + (f" (la anterior fue el {r['anterior']})" if r["anterior"] else "")
              + f". Menos trabajados en 7 días: {menos}.")


if __name__ == "__main__":
    main()
