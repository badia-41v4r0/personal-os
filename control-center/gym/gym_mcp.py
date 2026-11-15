#!/usr/bin/env python3
"""Servidor MCP (stdio, solo librería estándar) con las herramientas del Coach del gym.

Corre dentro del contenedor efímero de la conversación del Coach. Calcula con el mismo motor que el panel y Jarvis
(collectors/gym_stats.py y gym_coach.py, montados en solo lectura en /opt/gym):
- Entrenos: /vault/Jarvis/Areas/Gym.md (vault en solo lectura).
- Estado del entrenador (rutina, planificación, ajustes, sensaciones, decisiones): /gym/estado.json, que escribe el
  panel antes de cada turno.
- Las herramientas proponer_* NO cambian nada: dejan un JSON en /gym/salida que el panel convierte en una decisión
  «propuesta» que el usuario acepta o rechaza.
No hay herramientas para ejecutar código, leer otros archivos ni salir a internet.
"""
import json
import os
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

LIB = Path(os.environ.get("GYM_MCP_LIB", "/opt/gym"))
ESTADO = Path(os.environ.get("GYM_MCP_ESTADO", "/gym/estado.json"))
SALIDA = Path(os.environ.get("GYM_MCP_SALIDA", "/gym/salida"))
MAX = 40_000

TOOLS = [
    {"name": "resumen", "description": "Sesiones, series efectivas, volumen y series por músculo de los últimos N días (datos registrados y calculados).",
     "inputSchema": {"type": "object", "properties": {"dias": {"type": "integer", "default": 7}}}},
    {"name": "historial", "description": "Lista de entrenos (fecha, sesión, series, volumen, duración si se importó de Hevy). Filtros opcionales.",
     "inputSchema": {"type": "object", "properties": {"desde": {"type": "string"}, "hasta": {"type": "string"},
                                                     "sesion": {"type": "string", "description": "Push, Pull, Leg day…"},
                                                     "ejercicio": {"type": "string"}, "limite": {"type": "integer", "default": 20}}}},
    {"name": "sesion", "description": "Detalle de un entreno: ejercicios y series con su papel (top set, back-off, aproximación inferida, calentamiento), y la comparación con lo planificado si existe.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}, "fecha": {"type": "string"}}}},
    {"name": "ejercicio", "description": "Historial de un ejercicio (búsqueda aproximada por nombre), configuración (rango, incremento, método), objetivo del próximo entreno, estancamiento y récords.",
     "inputSchema": {"type": "object", "properties": {"nombre": {"type": "string"}, "dias": {"type": "integer"}}, "required": ["nombre"]}},
    {"name": "progresion", "description": "Estado de cada ejercicio activo: progresa, estable, estancado o retroceso, con confianza, evidencia y propuestas.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "records", "description": "Récords personales: reales (peso máximo, reps con un peso, volumen) y estimados (e1RM). Últimos N días o de un ejercicio.",
     "inputSchema": {"type": "object", "properties": {"dias": {"type": "integer", "default": 30}, "ejercicio": {"type": "string"}}}},
    {"name": "musculos", "description": "Series directas e indirectas por grupo muscular y semana, frecuencia, tendencia y última vez entrenado.",
     "inputSchema": {"type": "object", "properties": {"semanas": {"type": "integer", "default": 4}, "musculo": {"type": "string"}}}},
    {"name": "planificacion", "description": "Rutina activa, sesiones planificadas (con cumplimiento si ya se hicieron), calendario de esta semana y propuestas de reprogramación.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "siguiente_sesion", "description": "Próxima sesión recomendada por el motor: ejercicios, series, reps y peso objetivo, descanso y por qué. Es una recomendación hasta que el usuario la acepta en el panel.",
     "inputSchema": {"type": "object", "properties": {"fecha": {"type": "string"}, "nombre": {"type": "string"}}}},
    {"name": "recuperacion", "description": "Orientativo: carga reciente frente a la habitual por músculo, sensaciones registradas, molestias y correlaciones con el rendimiento. No mide la recuperación ni diagnostica.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "decisiones", "description": "Historial de decisiones del entrenador (motor, coach y el usuario) con su evaluación posterior cuando ya se puede medir.",
     "inputSchema": {"type": "object", "properties": {"limite": {"type": "integer", "default": 20}, "ejercicio": {"type": "string"}}}},
    {"name": "proponer_cambio", "description": "Registra una PROPUESTA (no la aplica): el usuario la verá en el panel para aceptarla o rechazarla. Úsala para cambios de carga, volumen, ejercicio, frecuencia o descarga. Incluye los datos que la justifican.",
     "inputSchema": {"type": "object", "required": ["tipo", "recomendacion", "motivo", "datos"], "properties": {
         "tipo": {"type": "string", "enum": ["subir_peso", "mantener", "bajar_peso", "mas_reps", "reducir_volumen", "cambiar_ejercicio", "frecuencia", "descarga", "otro"]},
         "alcance": {"type": "string", "enum": ["ejercicio", "musculo", "rutina", "general"], "default": "ejercicio"},
         "objetivo_de": {"type": "string", "description": "Ejercicio o grupo muscular afectado"},
         "ejercicio": {"type": "string", "description": "Nombre del ejercicio si aplica (se resuelve a su id)"},
         "situacion": {"type": "string"}, "datos": {"type": "array", "items": {"type": "string"}},
         "recomendacion": {"type": "string"}, "motivo": {"type": "string"}, "resultado_esperado": {"type": "string"},
         "peso": {"type": "number"}, "reps": {"type": "integer"}, "fecha_aplicacion": {"type": "string"}}}},
    {"name": "proponer_rutina", "description": "Propone una rutina completa o una versión nueva de la activa (no la aplica). dias: {\"0\": {\"nombre\": \"Leg day\", \"ejercicios\": [{\"nombre\", \"series\", \"rep_min\", \"rep_max\", \"descanso_s\", \"metodo\": \"top_set|doble_progresion\"}]}, …} con 0 = lunes.",
     "inputSchema": {"type": "object", "required": ["nombre", "motivo", "dias", "datos"], "properties": {
         "nombre": {"type": "string"}, "motivo": {"type": "string"}, "datos": {"type": "array", "items": {"type": "string"}},
         "resultado_esperado": {"type": "string"}, "dias": {"type": "object"}}}},
]


def _motor():
    sys.path.insert(0, str(LIB))
    import gym_coach as gc
    import gym_stats as gs
    return gc, gs


def _estado() -> dict:
    try:
        return json.loads(ESTADO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _ctx():
    gc, gs = _motor()
    est = _estado()
    gm = Path(os.environ["GYM_MD"]) if os.environ.get("GYM_MD") else gs.gym_md()
    ses = gs.cargar(gm, est.get("extra") or {})
    hoy = date.fromisoformat(est["hoy"]) if est.get("hoy") else date.today()
    perf = gc.perfil(gm)
    return gc, gs, est, ses, hoy, perf


def _ses_d(s, dur):
    return {"id": s.id, "fecha": s.fecha, "sesion": s.nombre, "series_efectivas": s.series, "volumen_kg": s.volumen,
            "ejercicios": [e.nombre for e in s.ejercicios], "duracion_min": dur.get(s.id)}


def call(name: str, a: dict) -> dict:
    gc, gs, est, ses, hoy, perf = _ctx()
    dur = est.get("duraciones") or {}
    logs = est.get("logs") or []
    if name == "resumen":
        r = gs.resumen(ses, int(a.get("dias") or 7), hoy)
        r["nota"] = "Series efectivas = no marcadas como calentamiento. Músculos: principal 1, secundario 0,5."
        return r
    if name == "historial":
        out = []
        for s in reversed(ses):
            if a.get("desde") and s.fecha < a["desde"] or a.get("hasta") and s.fecha > a["hasta"]:
                continue
            if a.get("sesion") and not gc.mismo_nombre(s.nombre, a["sesion"]):
                continue
            if a.get("ejercicio"):
                d = gs.buscar_ejercicio(ses, a["ejercicio"])
                if not d or not any(e.id == d["id"] for e in s.ejercicios):
                    continue
            out.append(_ses_d(s, dur))
            if len(out) >= int(a.get("limite") or 20):
                break
        return {"entrenos": out, "total_en_gym_md": len(ses)}
    if name == "sesion":
        s = next((x for x in ses if x.id == a.get("id") or x.fecha == a.get("fecha")), None)
        if not s:
            return {"error": "No encuentro ese entreno"}
        ejs = []
        for e in s.ejercicios:
            rs = gc.roles(e.series)
            ejs.append({"nombre": e.nombre, "id": e.id, "notas": e.notas, "volumen_kg": e.volumen,
                        "series": [gc._fmt({"peso": x.peso, "reps": x.reps, "rol": r}) + (f" [{r}]" if r else "") for x, r in zip(e.series, rs)],
                        "principales": e.principales, "secundarios": e.secundarios})
        plan = next((p for p in est.get("planificadas", []) if p.get("workout_id") == s.id), None)
        return {**_ses_d(s, dur), "detalle": ejs, "comparacion_plan": gc.comparar(plan, s) if plan else None,
                "nota": "aproximacion e intento son inferencias del método (top set + back-offs); calentamiento está marcado en Hevy."}
    if name == "ejercicio":
        d = gs.buscar_ejercicio(ses, a.get("nombre", ""))
        if not d:
            return {"error": f"No encuentro «{a.get('nombre')}» en Gym.md"}
        hist = gc.historial(ses, d["id"])
        if a.get("dias"):
            hist = [h for h in hist if h["fecha"] >= (hoy - timedelta(days=int(a["dias"]))).isoformat()]
        cfg = gc.config(d["id"], d["nombre"], gc.apariciones(ses, d["id"]), (est.get("ajustes") or {}).get(d["id"]))
        zona = gc.afectado(d["principales"], d["secundarios"], gc.molestias(perf, logs, hoy))
        rec = gc.records(ses, d["id"])["ejercicios"].get(d["id"])
        return {"ejercicio": d["nombre"], "id": d["id"], "config": cfg, "objetivo_siguiente": gc.objetivo(hist, cfg, zona),
                "estancamiento": gc.estancamiento(hist[-8:], hoy), "records": rec,
                "historial": [{"fecha": h["fecha"], "sesion": h["sesion"], "series": [gc._fmt(x) for x in h["series"]],
                               "top": gc._fmt(h["top"]), "volumen_kg": h["volumen"], "avisos": h["avisos"], "notas": h["notas"]}
                              for h in hist[-12:]]}
    if name == "progresion":
        return {"ejercicios": [{k: e[k] for k in ("nombre", "estado", "confianza", "evidencia", "propuestas")}
                               for e in gc.estancamientos(ses, hoy)]}
    if name == "records":
        if a.get("ejercicio"):
            d = gs.buscar_ejercicio(ses, a["ejercicio"])
            if not d:
                return {"error": "No encuentro ese ejercicio"}
            r = gc.records(ses, d["id"])
            return {"records": r["ejercicios"].get(d["id"]), "eventos": r["eventos"][-15:]}
        r = gc.records(ses)
        desde = (hoy - timedelta(days=int(a.get("dias") or 30))).isoformat()
        return {"eventos": [e for e in r["eventos"] if e["fecha"] >= desde][-40:],
                "nota": "nivel registrado = marca real; estimacion = e1RM (Epley), no levantado."}
    if name == "musculos":
        m = gc.musculos(ses, hoy, int(a.get("semanas") or 4))
        if a.get("musculo"):
            q = gs.norm(a["musculo"])
            m["musculos"] = [x for x in m["musculos"] if q in x["musculo"]]
        return m
    if name == "planificacion":
        rut = est.get("rutina")
        lunes = hoy - timedelta(days=hoy.weekday())
        pls = est.get("planificadas") or []
        sesmap = {s.id: s for s in ses}
        return {"rutina_activa": rut, "dias_rutina": gc.dias_rutina(rut),
                "planificadas": [{k: p.get(k) for k in ("id", "fecha", "nombre", "estado", "version", "workout_id", "origen_fecha")}
                                 | {"cumplimiento": gc.comparar(p, sesmap.get(p["workout_id"]))["cumplimiento"] if p.get("workout_id") in sesmap else None}
                                 for p in pls[-20:]],
                "semana": gc.calendario(ses, lunes, lunes + timedelta(days=6), hoy, rut, pls, est.get("pausas")),
                "reprogramar": gc.reprogramar(ses, hoy, rut, pls, est.get("pausas")),
                "pausas": (est.get("pausas") or [])[-10:],
                "versiones_rutina": (est.get("versiones_rutina") or [])[-10:]}
    if name == "siguiente_sesion":
        f = date.fromisoformat(a["fecha"]) if a.get("fecha") and a.get("nombre") else None
        p = gc.proponer_sesion(ses, hoy, est.get("rutina"), est.get("ajustes"), logs, perf, fecha=f,
                               nombre=a.get("nombre") if f else None, planificadas=est.get("planificadas"), duraciones=dur,
                               pausas=est.get("pausas"))
        if not p:
            return {"error": "No hay una próxima sesión en la rutina"}
        for e in p["ejercicios"]:
            e.pop("config", None)
        return p
    if name == "recuperacion":
        return gc.recuperacion(ses, logs, hoy, gc.molestias(perf, logs, hoy)) | {"pausas": est.get("pausas") or []}
    if name == "decisiones":
        ds = est.get("decisiones") or []
        if a.get("ejercicio"):
            d = gs.buscar_ejercicio(ses, a["ejercicio"])
            ds = [x for x in ds if d and x.get("ejercicio_id") == d["id"]]
        return {"decisiones": ds[: int(a.get("limite") or 20)]}
    if name in ("proponer_cambio", "proponer_rutina"):
        return _proponer(name, a, gc, gs, ses)
    return {"error": f"Herramienta desconocida: {name}"}


def _proponer(name: str, a: dict, gc, gs, ses) -> dict:
    datos = [str(x)[:300] for x in (a.get("datos") or [])][:20]
    if not datos:
        return {"error": "Incluye los datos que justifican la propuesta (campo datos)."}
    if name == "proponer_cambio":
        eid, objetivo_de = None, str(a.get("objetivo_de") or "")[:160]
        if a.get("ejercicio"):
            d = gs.buscar_ejercicio(ses, a["ejercicio"])
            if not d:
                return {"error": f"No encuentro el ejercicio «{a['ejercicio']}»"}
            eid, objetivo_de = d["id"], objetivo_de or d["nombre"]
        x = {"alcance": a.get("alcance") or ("ejercicio" if eid else "general"), "objetivo_de": objetivo_de,
             "ejercicio_id": eid, "tipo": a.get("tipo"), "situacion": str(a.get("situacion") or "")[:2000], "datos": datos,
             "recomendacion": str(a.get("recomendacion") or "")[:2000], "motivo": str(a.get("motivo") or "")[:2000],
             "resultado_esperado": str(a.get("resultado_esperado") or "")[:1000], "peso": a.get("peso"), "reps": a.get("reps"),
             "fecha_aplicacion": a.get("fecha_aplicacion")}
    else:
        dias = a.get("dias") or {}
        if not isinstance(dias, dict) or not dias:
            return {"error": "dias debe ser un objeto {\"0\": {\"nombre\", \"ejercicios\": [...]}}"}
        x = {"alcance": "rutina", "objetivo_de": str(a.get("nombre") or "Rutina")[:160], "tipo": "reorganizar",
             "situacion": "", "datos": datos, "recomendacion": f"Rutina «{a.get('nombre')}»",
             "motivo": str(a.get("motivo") or "")[:2000], "resultado_esperado": str(a.get("resultado_esperado") or "")[:1000],
             "rutina": {"dias": dias, "notas": str(a.get("motivo") or "")[:2000]}, "nombre_rutina": str(a.get("nombre") or "")[:120]}
    SALIDA.mkdir(parents=True, exist_ok=True)
    f = SALIDA / f"{uuid.uuid4().hex}.json"
    f.write_text(json.dumps(x, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "estado": "propuesta",
            "nota": "Guardada como propuesta. el usuario la verá en Gym → Coach para aceptarla o rechazarla; no se ha aplicado nada."}


def send(msg: dict) -> None:
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle(req: dict) -> dict | None:
    m, rid = req.get("method"), req.get("id")
    if rid is None:
        return None
    if m == "initialize":
        ver = (req.get("params") or {}).get("protocolVersion", "2025-06-18")
        return {"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": ver, "capabilities": {"tools": {}},
                                                         "serverInfo": {"name": "gym", "version": "1.0"}}}
    if m == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    if m == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}
    if m == "tools/call":
        p = req.get("params") or {}
        try:
            out = call(p.get("name", ""), p.get("arguments") or {})
            txt = json.dumps(out, ensure_ascii=False, default=str)
            if len(txt) > MAX:
                txt = txt[:MAX] + "… [recortado]"
            err = isinstance(out, dict) and "error" in out
        except Exception as e:  # noqa: BLE001
            txt, err = json.dumps({"error": f"{e.__class__.__name__}: {e}"}), True
        return {"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": txt}], "isError": err}}
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "Método no soportado"}}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            r = handle(json.loads(line))
        except ValueError:
            continue
        if r is not None:
            send(r)


if __name__ == "__main__":
    main()
