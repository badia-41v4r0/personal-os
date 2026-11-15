"""Radar de ofertas (sin IA): lee las alertas de empleo de LinkedIn en Gmail, las puntúa y detecta reclutadores.

- Reglas editables en Jarvis/Sistema/ofertas.md (puestos, descartes, lugares, reclutadores).
- Enlaces limpios: https://www.linkedin.com/jobs/view/<id>/ (el del correo lleva un token que inicia sesión).
- Vistas en Sistema/ofertas-vistas.json (id -> datos y fecha en que se vio por primera vez).
- Genera Jarvis/Areas/Ofertas.md con las de los últimos 14 días.

Uso: python3 ofertas.py [--dias N]   (por defecto 2; build.py lo llama cada mañana)
"""
import re
import sys
from datetime import date, timedelta

import correo
from lib import JARVIS, SISTEMA, fecha_corta, load_json, save_json, write_atomic

REGLAS = SISTEMA / "ofertas.md"
VISTAS = SISTEMA / "ofertas-vistas.json"
SALIDA = JARVIS / "Areas" / "Ofertas.md"
MINIMO = 2
SEPARADOR = re.compile(r"\n-{10,}\n")
ENLACE = re.compile(r"linkedin\.com/comm/jobs/view/(\d+)")


def reglas() -> dict:
    secciones, actual = {}, None
    for linea in REGLAS.read_text(encoding="utf-8").splitlines():
        if linea.startswith("## "):
            actual = linea[3:].split("(")[0].strip().lower()
            secciones[actual] = []
        elif actual and linea.startswith("- "):
            secciones[actual].append(linea[2:].strip().lower())
    return secciones


def _patron(terminos):
    """Inicio de palabra; los términos cortos (tam, fde) también deben acabar en límite de palabra."""
    partes = [re.escape(t) + (r"\b" if len(t) <= 4 else "") for t in terminos if t]
    return re.compile(r"\b(" + "|".join(partes) + ")", re.I) if partes else re.compile(r"(?!)")


def puntuar(o: dict, r: dict) -> int:
    titulo, lugar = o["titulo"], o["lugar"]
    if _patron(r.get("descartar", [])).search(titulo):
        return -9
    if _patron(r.get("puestos objetivo", [])).search(titulo):
        p = 4
    elif _patron(r.get("puestos cercanos", [])).search(titulo):
        p = 2 + (1 if _patron(r.get("extra ia", [])).search(titulo) else 0)
    else:
        p = 0
    if _patron(r.get("lugar bueno", [])).search(lugar):
        p += 1
    elif lugar and not _patron(r.get("lugar neutro", [])).search(lugar):
        p -= 2
    return p


def parsear(texto: str) -> list[dict]:
    """Bloques de la alerta en texto plano: título, empresa, lugar, ..., 'View job: URL'."""
    out = []
    for bloque in SEPARADOR.split(texto):
        m = ENLACE.search(bloque)
        if not m:
            continue
        lineas = [l.strip() for l in bloque.splitlines() if l.strip()]
        lineas = [l for l in lineas if not l.lower().startswith(("your job alert", "new jobs match", "view job"))]
        if len(lineas) < 2:
            continue
        out.append({"id": m[1], "titulo": correo._corto(lineas[0], 120), "empresa": correo._corto(lineas[1], 60),
                    "lugar": correo._corto(lineas[2], 60) if len(lineas) > 2 and not lineas[2][0].isdigit() else "",
                    "enlace": f"https://www.linkedin.com/jobs/view/{m[1]}/"})
    return out


def recoger(hoy: date, dias: int = 2) -> dict:
    r = reglas()
    vistas = load_json(VISTAS, {})
    t = correo._gmail_token()
    alertas = correo.gmail_listar(f"from:jobalerts-noreply@linkedin.com newer_than:{dias}d", 50)
    for a in alertas:
        d = correo._http("GET", f"{correo.GMAIL}/messages/{a['id']}?format=full", t)
        cuerpo, es_html = correo._gmail_cuerpo(d["payload"])
        if es_html:
            continue  # las alertas traen versión de texto; si algún día no, se ignoran
        for o in parsear(cuerpo.replace("\r", "")):
            if o["id"] not in vistas:
                o["visto"] = hoy.isoformat()
                o["puntos"] = puntuar(o, r)
                vistas[o["id"]] = o
    limite = (hoy - timedelta(days=60)).isoformat()
    vistas = {k: v for k, v in vistas.items() if v["visto"] >= limite}
    save_json(VISTAS, vistas)

    recientes = [v for v in vistas.values() if v["visto"] >= (hoy - timedelta(days=14)).isoformat()]
    for v in recientes:  # si cambian las reglas, se repuntúa
        v["puntos"] = puntuar(v, r)
    buenas = sorted([v for v in recientes if v["puntos"] >= MINIMO], key=lambda v: (v["visto"], v["puntos"]), reverse=True)
    nuevas = sorted([v for v in buenas if v["visto"] == hoy.isoformat()], key=lambda v: -v["puntos"])
    escribir(hoy, buenas, len(recientes))

    rec = _patron(r.get("reclutadores", []))
    reclutadores = [c for c in correo.gmail_listar("newer_than:2d in:inbox -from:linkedin.com -category:promotions -category:social", 30)
                    if rec.search(c["de"]) or rec.search(c["asunto"])]
    return {"nuevas": nuevas, "reclutadores": reclutadores}


def escribir(hoy: date, buenas: list, total: int):
    L = ["# 💼 Ofertas (radar)", "",
         f"_Generado por `collectors/ofertas.py` el {hoy.isoformat()}; no lo edites (las reglas están en [[Sistema/ofertas]])._",
         f"_Últimos 14 días: {len(buenas)} de {total} ofertas de las alertas de LinkedIn pasan el filtro._", "",
         "| Visto | Pts | Puesto | Empresa | Lugar | ID |", "|---|---|---|---|---|---|"]
    for v in buenas:
        esc = lambda s: s.replace("|", "/")
        L.append(f"| {fecha_corta(date.fromisoformat(v['visto']))} | {v['puntos']} | [{esc(v['titulo'])}]({v['enlace']}) "
                 f"| {esc(v['empresa'])} | {esc(v['lugar'])} | {v['id']} |")
    if not buenas:
        L.append("| | | Nada que pase el filtro | | | |")
    write_atomic(SALIDA, "\n".join(L) + "\n")


if __name__ == "__main__":
    dias = int(sys.argv[sys.argv.index("--dias") + 1]) if "--dias" in sys.argv else 2
    res = recoger(date.today(), dias)
    for v in res["nuevas"]:
        print(f"{v['puntos']:>2}  {v['titulo']} · {v['empresa']} · {v['lugar']}")
    print(f"\n{len(res['nuevas'])} nuevas hoy · reclutadores: {[c['de'] + ' — ' + c['asunto'] for c in res['reclutadores']]}")
