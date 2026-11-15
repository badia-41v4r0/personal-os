"""Motor del entrenador (collectors/gym_coach.py) e importador de Hevy: cálculos deterministas con fixtures."""
import json
import sys
from datetime import date, timedelta

from app.config import ROOT

sys.path.insert(0, str(ROOT / "collectors"))
import gym_coach as gc  # noqa: E402
import gym_stats as gs  # noqa: E402
import hevy_import as hv  # noqa: E402

LUNES = date(2026, 10, 5)


def gym(tmp_path, bloques: list[tuple[date, str, list[str]]], perfil: str = "") -> list:
    txt = "# Gym\n## Perfil\n" + perfil + "\n## Registro\n"
    for d, nombre, ejs in bloques:
        txt += f"\n### {d.isoformat()} · {nombre}\n" + "\n".join(f"- {e}" for e in ejs) + "\n"
    p = tmp_path / "Gym.md"
    p.write_text(txt, encoding="utf-8")
    return gs.cargar(p)


def semanas(n: int, banca: list[str], extra: list[str] | None = None):
    """n martes seguidos (Push) con las series de banca dadas en orden."""
    return [(LUNES + timedelta(days=1, weeks=i), "Push", [f"Press de Banca (Barra): {banca[i]}"] + (extra or [])) for i in range(n)]


# ---------- volumen, músculos y e1RM ----------

def test_volumen_y_musculos(tmp_path):
    s = gym(tmp_path, [(LUNES, "Leg day", ["Sentadilla Hack (Máquina): 40×10 (cal.), 70×8, 60×10",
                                           "Dominada: PC×8, PC×6"])])
    e = s[0].ejercicios[0]
    assert e.volumen == 70 * 8 + 60 * 10  # el calentamiento no suma
    assert s[0].ejercicios[1].volumen == 0  # peso corporal: sin kg
    m = gs.series_por_musculo(s)
    assert m["cuadriceps"] == 2 and m["gluteos"] == 1.0  # secundario ×0,5
    assert m["espalda"] == 2


def test_e1rm_solo_hasta_12_reps():
    assert gs.Serie(100, 5).e1rm == round(100 * (1 + 5 / 30), 1)
    assert gs.Serie(50, 15).e1rm is None  # demasiadas reps: no fiable
    assert gs.Serie(50, 5, calentamiento=True).e1rm is None


# ---------- papeles de las series ----------

def test_roles_top_backoff_aproximacion():
    ser = [gs.Serie(40, 10), gs.Serie(80, 10), gs.Serie(140, 10), gs.Serie(130, 10), gs.Serie(160, 1), gs.Serie(20, 10, calentamiento=True)]
    assert gc.roles(ser) == ["aproximacion", "aproximacion", "top", "backoff", "intento", "calentamiento"]


# ---------- objetivos de progresión ----------

def cfg(**k):
    base = {"ejercicio_id": "x", "nombre": "X", "categoria": "compuesto", "metodo": "top_set", "rep_min": 6, "rep_max": 10,
            "series": 3, "descanso_s": 180, "incremento_kg": 2.5, "rir_top": 0, "rir_backoff": "1–2"}
    return base | k


def test_doble_progresion_ejemplo(tmp_path):
    # 60×10, 60×9, 60×8 → 60×10, 60×10, 60×9
    s = gym(tmp_path, semanas(1, ["60×10, 60×9, 60×8"]))
    o = gc.objetivo(gc.historial(s, "press-de-banca-barra"), cfg(metodo="doble_progresion", rep_min=8, rep_max=10))
    assert [x["reps"] for x in o["series_objetivo"]] == [10, 10, 9] and o["series_objetivo"][0]["peso"] == 60
    s = gym(tmp_path, semanas(1, ["60×10, 60×10, 60×10"]))
    o = gc.objetivo(gc.historial(s, "press-de-banca-barra"), cfg(metodo="doble_progresion", rep_min=8, rep_max=10))
    assert o["accion"] == "subir_peso" and o["top"]["peso"] == 62.5 and o["top"]["reps"] == 8


def test_top_set_dentro_tope_y_debajo(tmp_path):
    h = lambda b: gc.historial(gym(tmp_path, semanas(len(b), b)), "press-de-banca-barra")  # noqa: E731
    assert gc.objetivo(h(["60×7, 55×8"]), cfg())["top"] == {"peso": 60, "reps": 8, "rir": 0}
    o = gc.objetivo(h(["60×10, 55×10"]), cfg())
    assert o["accion"] == "subir_peso" and o["top"]["peso"] == 62.5 and o["top"]["reps"] == 6
    assert o["backoffs"][0]["peso"] < o["top"]["peso"]
    o = gc.objetivo(h(["60×5, 55×6"]), cfg())
    assert o["accion"] == "mantener" and o["top"]["peso"] == 60
    o = gc.objetivo(h(["60×5", "60×5"]), cfg())  # dos sesiones por debajo → baja 5–10 %
    assert o["accion"] == "bajar_peso" and 54 <= o["top"]["peso"] < 60


def test_muy_por_debajo_objetivo_realista(tmp_path):
    s = gym(tmp_path, semanas(1, ["90×6"]))
    o = gc.objetivo(gc.historial(s, "press-de-banca-barra"), cfg(rep_min=10, rep_max=15))
    assert o["accion"] == "mantener" and o["top"]["reps"] == 7  # no «aprieta hasta 10»
    assert "Alternativa" in o["motivo"]


def test_no_sube_si_baja_el_rendimiento(tmp_path):
    s = gym(tmp_path, semanas(2, ["70×9", "60×10"]))
    o = gc.objetivo(gc.historial(s, "press-de-banca-barra"), cfg())
    assert o["accion"] == "mantener" and o["top"]["peso"] == 60


def test_molestia_no_fuerza(tmp_path):
    s = gym(tmp_path, semanas(1, ["60×10"]))
    zona = {"zona": "hombro", "fuente": "Perfil", "detalle": ""}
    o = gc.objetivo(gc.historial(s, "press-de-banca-barra"), cfg(), zona)
    assert o["accion"] == "precaucion" and o["top"]["peso"] == 60 and o["top"]["reps"] == 10 and o["top"]["rir"] == 2
    assert o["precaucion"]


def test_peso_corporal_lastre(tmp_path):
    s = gym(tmp_path, [(LUNES, "Pull", ["Dominada: PC×10, PC×8"])])
    c = gc.config("dominada", "Dominada", gc.apariciones(s, "dominada"))
    assert c["categoria"] == "peso_corporal"
    o = gc.objetivo(gc.historial(s, "dominada"), c)
    assert o["accion"] == "lastre" and o["top"]["peso"] == c["incremento_kg"]


def test_incremento_observado_y_categorias(tmp_path):
    assert gc.categoria("Curl de Bíceps (Cable)") == "aislamiento"
    assert gc.categoria("Sentadilla Hack (Máquina)") == "maquina"
    assert gc.categoria("Press de Banca (Barra)") == "compuesto"
    assert gc.paso_observado([50, 52.5, 55, 57.5, 60]) == 2.5
    assert gc.config("x", "Curl (Mancuerna)", [], {"rep_min": 12, "rep_max": 8})["rep_min"] == 8  # rango corregido


# ---------- estancamientos ----------

def test_una_mala_sesion_no_es_estancamiento(tmp_path):
    s = gym(tmp_path, semanas(4, ["60×6", "60×7", "60×8", "60×6"]))
    assert gc.estancamiento(gc.historial(s, "press-de-banca-barra"))["estado"] not in ("estancado", "retroceso")


def test_estancado_y_retroceso(tmp_path):
    s = gym(tmp_path, semanas(5, ["60×8", "60×8", "60×7", "60×8", "60×8"]))
    r = gc.estancamiento(gc.historial(s, "press-de-banca-barra"))
    assert r["estado"] == "estancado" and r["confianza"] in ("media", "alta") and r["evidencia"] and r["propuestas"]
    s = gym(tmp_path, semanas(3, ["70×8", "65×8", "60×8"]))
    assert gc.estancamiento(gc.historial(s, "press-de-banca-barra"))["estado"] == "retroceso"
    s = gym(tmp_path, semanas(2, ["60×8", "60×8"]))
    assert gc.estancamiento(gc.historial(s, "press-de-banca-barra"))["estado"] == "pocos_datos"


# ---------- récords ----------

def test_records_reales_y_estimados(tmp_path):
    s = gym(tmp_path, semanas(3, ["60×8", "62.5×6", "60×10"]))
    r = gc.records(s, "press-de-banca-barra")
    ej = r["ejercicios"]["press-de-banca-barra"]
    assert ej["peso_max"]["peso"] == 62.5 and ej["e1rm"]["nivel"] == "estimacion"
    tipos = {(e["tipo"], e["fecha"]) for e in r["eventos"]}
    assert ("peso_max", semanas(3, ["", "", ""])[1][0].isoformat()) in tipos
    assert all(e["fecha"] != LUNES.isoformat() for e in r["eventos"])  # la primera sesión no es récord
    assert all(e["nivel"] == "estimacion" for e in r["eventos"] if e["tipo"] == "e1rm")


# ---------- plan frente a realizado ----------

def test_comparar_plan(tmp_path):
    s = gym(tmp_path, [(LUNES, "Push", ["Press de Banca (Barra): 60×8, 55×8", "Curl de Bíceps (Cable): 20×12"])])
    plan = {"ejercicios": [
        {"id": "press-de-banca-barra", "nombre": "Press", "series": 2, "objetivo": {"top": {"peso": 60, "reps": 8}, "series_objetivo": [{"peso": 60, "reps": 8}, {"peso": 55, "reps": "6–10"}]}},
        {"id": "aperturas-maquina", "nombre": "Aperturas", "series": 3, "objetivo": {"top": {"peso": 40, "reps": 12}}}]}
    c = gc.comparar(plan, s[0])
    est = {f["id"]: f["estado"] for f in c["ejercicios"]}
    assert est == {"press-de-banca-barra": "cumplido", "aperturas-maquina": "omitido"}
    assert [a["id"] for a in c["anadidos"]] == ["curl-de-biceps-cable"] and c["cumplimiento"] == 50
    assert gc.comparar(plan, None)["estado"] == "sin_asociar"
    # Solo se asocia automáticamente con misma fecha y nombre
    assert gc.buscar_sesion(s, LUNES.isoformat(), "Push") is s[0]
    assert gc.buscar_sesion(s, LUNES.isoformat(), "Pull") is None


# ---------- recomendación, reprogramación, recuperación e informes ----------

def bloque_semana(ini: date, banca: str):
    return [(ini, "Leg day", ["Sentadilla Hack (Máquina): 70×8, 60×10"]), (ini + timedelta(1), "Push", [f"Press de Banca (Barra): {banca}"]),
            (ini + timedelta(2), "Pull", ["Jalón al Pecho (Cable): 50×10"]), (ini + timedelta(3), "Lower", ["Extensión de Pierna: 60×12"]),
            (ini + timedelta(4), "Upper", ["Press de Hombros Sentado (Barra): 40×8"])]


def test_proponer_sesion(tmp_path):
    s = gym(tmp_path, bloque_semana(LUNES, "60×8") + bloque_semana(LUNES + timedelta(7), "60×9"), "- **No quiero hacer:** _Búlgaras_")
    hoy = LUNES + timedelta(15)  # martes
    p = gc.proponer_sesion(s, hoy, perf=gc.perfil(tmp_path / "Gym.md"))
    assert p["nombre"] == "Push" and p["fecha"] == hoy.isoformat() and p["estado"] == "recomendacion"
    e = p["ejercicios"][0]
    assert e["objetivo"]["top"] == {"peso": 60, "reps": 10, "rir": 0} and e["por_que"]
    assert p["duracion_estimada_min"] > 0


def test_reprogramar_sesion_perdida(tmp_path):
    ini = LUNES
    s = gym(tmp_path, [b for b in bloque_semana(ini, "60×8") if b[1] != "Pull"])
    props = gc.reprogramar(s, ini + timedelta(4), None, [])  # viernes; el miércoles (Pull) se perdió
    assert props and props[0]["sesion"] == "Pull"
    assert props[0]["hasta"] in ((ini + timedelta(5)).isoformat(), (ini + timedelta(6)).isoformat(), None)


def test_recuperacion_y_correlacion(tmp_path):
    s = gym(tmp_path, bloque_semana(LUNES, "60×8"))
    r = gc.recuperacion(s, [{"fecha": LUNES.isoformat(), "energia": 4}], LUNES + timedelta(5))
    assert r["nivel"] == "inferencia" and "No mide" in r["aviso"]
    assert r["correlaciones"]["por_campo"]["energia"]["r"] is None  # pocos datos: no se calcula
    assert {m["musculo"] for m in r["musculos"]} >= {"pecho", "cuadriceps"}
    perf = {"zonas": [], "lesiones": ""}
    z = gc.molestias(perf, [{"fecha": LUNES.isoformat(), "molestia_zona": "Hombro derecho"}], LUNES + timedelta(2))
    assert z[0]["zona"] == "hombro"
    assert gc.afectado(["pecho"], [], z)


def test_informe_semanal_y_mensual(tmp_path):
    s = gym(tmp_path, bloque_semana(LUNES, "60×8") + bloque_semana(LUNES + timedelta(7), "62.5×8"))
    w = gc.informe(s, "semanal", LUNES + timedelta(7), LUNES + timedelta(13))
    assert w["sesiones_hechas"] == 5 and w["sesiones_previstas"] == 5 and w["cumplimiento"] == 100
    assert any(p["nombre"] == "Press de Banca (Barra)" for p in w["progresos"]) and "🏋️" in w["texto"]
    m = gc.informe(s, "mensual", date(2026, 10, 1), date(2026, 10, 31))
    assert "objetivos_proximo_mes" in m and m["semanas"]


def test_evaluar_decision(tmp_path):
    s = gym(tmp_path, semanas(2, ["60×8", "62.5×7"]))
    d = {"ejercicio_id": "press-de-banca-barra", "objetivo": {"peso": 62.5, "reps": 6}, "fecha": (LUNES + timedelta(2)).isoformat()}
    assert gc.evaluar_decision(d, s)["estado"] == "cumplido"
    d["objetivo"] = {"peso": 65, "reps": 6}
    assert gc.evaluar_decision(d, s)["estado"] == "no_cumplido"
    d["fecha"] = "2027-01-01"
    assert gc.evaluar_decision(d, s)["estado"] == "pendiente"


# ---------- importación de Hevy ----------

CSV = """title,start_time,end_time,description,exercise_title,superset_id,exercise_notes,set_index,set_type,weight_kg,reps,distance_km,duration_seconds,rpe
PechoTriceps,"6 oct 2026, 18:00","6 oct 2026, 19:10",,Press de Banca (Barra),,,0,warmup,40,10,,,
PechoTriceps,"6 oct 2026, 18:00","6 oct 2026, 19:10",,Press de Banca (Barra),,,1,failure,60,8,,,
PechoTriceps,"6 oct 2026, 18:00","6 oct 2026, 19:10",,Press de Banca (Barra),,,2,normal,55,9,,,8.5
PechoTriceps,"6 oct 2026, 18:00","6 oct 2026, 19:10",,Fondos,,,0,normal,,10,,,
Back & Biceps,"7 oct 2026, 18:00","7 oct 2026, 19:00",,Remo con Barra,,,0,normal,abc,10,,,
Back & Biceps,"7 oct 2026, 18:00","7 oct 2026, 19:00",,Remo con Barra,,,1,normal,50,10,,,
"""


def test_hevy_leer_normaliza_y_registra_errores():
    r = hv.leer(CSV)
    assert len(r["entrenos"]) == 2 and len(r["errores"]) == 1 and "Fila 6" in r["errores"][0]
    w = r["entrenos"][0]
    assert w["sesion"] == "Push" and w["duracion_min"] == 70 and len(w["filas"]) == 4 and len(w["external_id"]) == 16
    b = hv.bloque(w)
    assert "40×10 (cal.)" in b and "60×8 (fallo)" in b and "RPE 8.5" in b and "PC×10" in b
    assert r["entrenos"][1]["sesion"] == "Pull"
    # Lo que escribe se lee igual con gym_stats (calentamiento no efectivo)
    assert hv.leer("a,b\n1,2")["errores"]  # no es un CSV de Hevy


def test_hevy_idempotente(tmp_path):
    p = tmp_path / "Gym.md"
    p.write_text("# Gym\n## Registro\n", encoding="utf-8")
    r = hv.leer(CSV)
    plan = hv.planificar(r["entrenos"], set())
    assert hv.aplicar(plan["nuevos"], p) == 2
    s = gs.cargar(p)
    assert [x.nombre for x in s] == ["Push", "Pull"] and s[0].ejercicios[0].series[0].calentamiento
    plan2 = hv.planificar(r["entrenos"], {x.fecha for x in s})
    assert plan2["nuevos"] == [] and len(plan2["ya_registrados"]) == 2  # segunda vez: nada nuevo


def test_alias_y_musculos_corregidos(tmp_path):
    p = tmp_path / "Gym.md"
    p.write_text("# Gym\n## Registro\n### 2026-10-06 · Push\n- Bench Press: 60×8\n- Máquina rara: 30×10\n", encoding="utf-8")
    s = gs.cargar(p, {"alias_id": {"bench press": "press-de-banca-barra"}, "musculos_id": {"maquina-rara": {"principales": ["espalda"], "secundarios": []}}})
    assert s[0].ejercicios[0].id == "press-de-banca-barra"
    assert s[0].ejercicios[1].principales == ["espalda"]


# ---------- servidor MCP del Coach ----------

def test_mcp_herramientas(tmp_path, monkeypatch):
    gym(tmp_path, bloque_semana(LUNES, "60×8") + bloque_semana(LUNES + timedelta(7), "60×9"))
    (tmp_path / "estado.json").write_text(json.dumps({"hoy": (LUNES + timedelta(15)).isoformat()}))
    monkeypatch.setenv("GYM_MD", str(tmp_path / "Gym.md"))
    sys.path.insert(0, str(ROOT / "control-center/gym"))
    import gym_mcp
    monkeypatch.setattr(gym_mcp, "ESTADO", tmp_path / "estado.json")
    monkeypatch.setattr(gym_mcp, "SALIDA", tmp_path / "salida")
    assert {t["name"] for t in gym_mcp.TOOLS} >= {"historial", "ejercicio", "records", "musculos", "planificacion", "recuperacion", "proponer_cambio"}
    r = gym_mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "ejercicio", "arguments": {"nombre": "press banca"}}})
    out = json.loads(r["result"]["content"][0]["text"])
    assert out["id"] == "press-de-banca-barra" and out["objetivo_siguiente"]["top"]["reps"] == 10
    assert gym_mcp.call("siguiente_sesion", {})["nombre"] == "Push"
    assert gym_mcp.call("musculos", {"musculo": "pecho"})["musculos"][0]["musculo"] == "pecho"
    # Proponer sin datos se rechaza; con datos deja un JSON y no aplica nada
    assert "error" in gym_mcp.call("proponer_cambio", {"tipo": "descarga", "recomendacion": "x", "motivo": "y", "datos": []})
    assert gym_mcp.call("proponer_cambio", {"tipo": "descarga", "ejercicio": "press banca", "recomendacion": "x", "motivo": "y", "datos": ["a"]})["ok"]
    f = next((tmp_path / "salida").glob("*.json"))
    assert json.loads(f.read_text())["ejercicio_id"] == "press-de-banca-barra"
    assert gym_mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "nada"})["error"]["code"] == -32601
