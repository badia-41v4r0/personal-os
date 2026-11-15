"""API de Gym 2.0 contra un Gym.md de prueba: persistencia, versiones, confirmaciones, importación, informes y Coach."""
import json
from datetime import date, timedelta

import pytest

from app import gym as gym_api

HOY = date(2026, 10, 20)  # martes
L = date(2026, 10, 5)


def bloque(ini: date, banca: str) -> str:
    return "\n".join([
        f"### {ini} · Leg day\n- Sentadilla Hack (Máquina): 70×8, 60×10",
        f"### {ini + timedelta(1)} · Push\n- Press de Banca (Barra): {banca}\n- Aperturas (Máquina): 40×12",
        f"### {ini + timedelta(2)} · Pull\n- Jalón al Pecho (Cable): 50×10",
        f"### {ini + timedelta(3)} · Lower\n- Extensión de Pierna: 60×12",
        f"### {ini + timedelta(4)} · Upper\n- Press de Hombros Sentado (Barra): 40×8"])


@pytest.fixture()
def g(settings, monkeypatch, tmp_path):
    p = settings.vault / "Jarvis/Areas"
    p.mkdir(parents=True)
    (p / "Gym.md").write_text("# Gym\n## Perfil\n- **Objetivo:** hipertrofia\n\n## Registro\n\n" + bloque(L, "60×8, 55×8") + "\n\n"
                              + bloque(L + timedelta(7), "60×9, 55×9") + "\n", encoding="utf-8")
    monkeypatch.setattr(gym_api, "hoy", lambda: HOY)
    import app.gym_plan as gp
    monkeypatch.setattr(gp, "hoy", lambda: HOY)
    monkeypatch.setenv("CC_TELEGRAM_INBOX", str(tmp_path / "inbox"))
    gym_api._cache["key"] = None
    return p / "Gym.md"


def test_overview_y_lecturas(client, auth, g):
    o = client.get("/api/v1/gym/overview").json()
    assert o["ultima"]["fecha"] == "2026-10-16" and o["semana"]["previstas"] == 5
    sig = o["siguiente"]
    assert sig["nombre"] == "Push" and sig["fecha"] == "2026-10-20" and sig["estado"] == "recomendacion"
    assert sig["ejercicios"][0]["objetivo"]["top"]["peso"] == 60 and sig["ejercicios"][0]["objetivo"]["top"]["reps"] == 10
    assert "niveles" in o and isinstance(o["analisis"], list)
    for path in ("/workouts", "/exercises", "/statistics", "/muscles", "/records", "/stagnation", "/analysis", "/recovery",
                 "/calendar", "/recommendations", "/plans", "/routines", "/coach/decisions", "/imports",
                 "/exercises/press-de-banca-barra", "/exercises/press-de-banca-barra/progress?periodo=28d",
                 "/workouts/2026-10-13-push", "/workouts/2026-10-06-push/compare/2026-10-13-push"):
        r = client.get("/api/v1/gym" + path)
        assert r.status_code == 200, (path, r.text)
    assert client.get("/api/v1/gym/exercises/no-existe").status_code == 404
    assert client.get("/api/v1/gym/exercises/press-de-banca-barra/progress?periodo=malo").status_code == 422


def test_aceptar_plan_registra_decisiones_y_compara(client, auth, g):
    rec = client.get("/api/v1/gym/recommendations").json()
    assert client.post("/api/v1/gym/recommendations/siguiente/accept", json={"huella": "otra"}, headers=auth).status_code == 409
    r = client.post("/api/v1/gym/recommendations/siguiente/accept", json={"huella": rec["siguiente"]["huella"]}, headers=auth)
    assert r.status_code == 200
    plan = r.json()
    assert plan["estado"] == "aceptada" and plan["fecha"] == "2026-10-20"
    # Ya planificada: la recomendación lo indica
    assert client.get("/api/v1/gym/recommendations").json()["planificada"]["id"] == plan["id"]
    # Hago la sesión (Hevy → Gym.md) y se asocia sola por fecha + nombre
    g.write_text(g.read_text() + "\n### 2026-10-20 · Push\n- Press de Banca (Barra): 60×10, 55×10\n- Fondos: PC×10\n")
    d = client.get(f"/api/v1/gym/plans/{plan['id']}").json()
    assert d["workout_id"] == "2026-10-20-push" and d["link_mode"] == "auto" and d["estado"] == "hecha"
    c = d["comparacion"]
    est = {e["id"]: e["estado"] for e in c["ejercicios"]}
    assert est["press-de-banca-barra"] == "cumplido" and est["aperturas-maquina"] == "omitido"
    assert [a["id"] for a in c["anadidos"]] == ["fondos"]
    # No se modifica lo previsto una vez hecho
    assert client.patch(f"/api/v1/gym/plans/{plan['id']}", json={"ejercicios": []}, headers=auth).status_code == 409
    w = client.get("/api/v1/gym/workouts/2026-10-20-push").json()
    assert w["plan"]["id"] == plan["id"] and w["comparacion"]["cumplimiento"] is not None


def test_plan_manual_versiones_y_asociacion(client, auth, g):
    r = client.post("/api/v1/gym/plans", json={"fecha": "2026-10-22", "nombre": "Pull", "motivo": "a mano",
                                               "ejercicios": [{"nombre": "Jalón al Pecho (Cable)", "series": 3, "rep_min": 8, "rep_max": 12, "peso": 52.5, "reps": 8}]}, headers=auth)
    assert r.status_code == 200
    pid = r.json()["id"]
    assert client.post("/api/v1/gym/plans", json={"fecha": "2026-10-01", "nombre": "Pull"}, headers=auth).status_code == 422
    body = {"ejercicios": [{"nombre": "Remo con Barra", "series": 4, "rep_min": 6, "rep_max": 10, "peso": 50},
                           {"nombre": "Jalón al Pecho (Cable)", "series": 3, "rep_min": 8, "rep_max": 12, "peso": 55}],
            "motivo": "cambio el orden", "version_base": 1}
    d = client.patch(f"/api/v1/gym/plans/{pid}", json=body, headers=auth).json()
    assert d["version"] == 2 and len(d["versiones"]) == 2 and d["versiones"][0]["ejercicios"][0]["nombre"] == "Jalón al Pecho (Cable)"
    assert d["ejercicios"][0]["nombre"] == "Remo con Barra"
    assert client.patch(f"/api/v1/gym/plans/{pid}", json=body, headers=auth).status_code == 409  # versión vieja
    # Asociación manual con un entreno que no coincide en fecha
    assert client.post(f"/api/v1/gym/plans/{pid}/link", json={"workout_id": "nada"}, headers=auth).status_code == 404
    assert client.post(f"/api/v1/gym/plans/{pid}/link", json={"workout_id": "2026-10-14-pull"}, headers=auth).status_code == 200
    d = client.get(f"/api/v1/gym/plans/{pid}").json()
    assert d["link_mode"] == "manual" and d["comparacion"]["estado"] == "asociada"
    # Una nueva planificación el mismo día sustituye (no borra) a la anterior
    client.post("/api/v1/gym/plans", json={"fecha": "2026-10-22", "nombre": "Upper"}, headers=auth)
    todas = client.get("/api/v1/gym/plans?todas=true").json()
    assert {p["nombre"]: p["estado"] for p in todas if p["fecha"] == "2026-10-22"}["Upper"] == "aceptada"


def test_recuperacion(client, auth, g):
    assert client.post("/api/v1/gym/recovery", json={"fecha": "2030-01-01", "energia": 3}, headers=auth).status_code == 422
    assert client.post("/api/v1/gym/recovery", json={"fecha": "2026-10-19", "energia": 9}, headers=auth).status_code == 422
    r = client.post("/api/v1/gym/recovery", json={"fecha": "2026-10-19", "energia": 2, "molestia_zona": "hombro", "molestia_intensidad": 3}, headers=auth)
    assert r.status_code == 200
    client.post("/api/v1/gym/recovery", json={"fecha": "2026-10-19", "energia": 3, "molestia_zona": "hombro"}, headers=auth)  # actualiza
    rc = client.get("/api/v1/gym/recovery").json()
    assert len(rc["registros"]) == 1 and rc["registros"][0]["energia"] == 3 and rc["molestias"][0]["zona"] == "hombro"
    # La molestia hace que el press de banca vaya con precaución
    sig = client.get("/api/v1/gym/recommendations").json()["siguiente"]
    banca = next(e for e in sig["ejercicios"] if e["id"] == "press-de-banca-barra")
    assert banca["objetivo"]["accion"] == "precaucion" and banca["objetivo"]["top"]["reps"] == 9
    assert client.delete("/api/v1/gym/recovery/2026-10-19", headers=auth).status_code == 200


def test_rutinas_versiones_y_confirmacion(client, auth, g):
    r = client.post("/api/v1/gym/routines", json={"nombre": "Mía", "desde_historial": True}, headers=auth).json()
    rid = r["id"]
    assert r["estado"] == "draft" and r["spec"]["dias"]["1"]["nombre"] == "Push"
    assert client.patch(f"/api/v1/gym/routines/{rid}", json={"estado": "active"}, headers=auth).status_code == 428
    assert client.patch(f"/api/v1/gym/routines/{rid}", json={"estado": "active", "confirmar": True}, headers=auth).json()["estado"] == "active"
    spec = r["spec"]
    spec["dias"]["1"]["ejercicios"].append({"nombre": "Fondos", "series": 3, "rep_min": 6, "rep_max": 10, "descanso_s": 120, "metodo": "top_set"})
    assert client.patch(f"/api/v1/gym/routines/{rid}", json={"spec": spec}, headers=auth).status_code == 428  # activa: confirmar
    assert client.patch(f"/api/v1/gym/routines/{rid}", json={"spec": spec, "confirmar": True}, headers=auth).status_code == 422  # sin motivo
    d = client.patch(f"/api/v1/gym/routines/{rid}", json={"spec": spec, "confirmar": True, "motivo": "más tríceps", "version_base": 1}, headers=auth).json()
    assert d["version"] == 2 and any("Fondos" in c for c in d["versiones"][0]["cambios"])
    # La rutina activa manda en la recomendación
    sig = client.get("/api/v1/gym/recommendations").json()["siguiente"]
    assert "Fondos" in [e["nombre"] for e in sig["ejercicios"]] and sig["origen"].startswith("Rutina")
    assert client.post(f"/api/v1/gym/routines/{rid}/restore/1", json={}, headers=auth).status_code == 428
    d = client.post(f"/api/v1/gym/routines/{rid}/restore/1", json={"confirmar": True}, headers=auth).json()
    assert d["version"] == 3 and len(d["versiones"]) == 3
    dup = client.post(f"/api/v1/gym/routines/{rid}/duplicate", headers=auth).json()
    assert dup["estado"] == "draft" and dup["version"] == 1
    bad = {"spec": {"dias": {"9": {"nombre": "x", "ejercicios": []}}, "notas": ""}}
    assert client.patch(f"/api/v1/gym/routines/{dup['id']}", json=bad, headers=auth).status_code == 422


def test_ajustes_y_alias(client, auth, g):
    r = client.put("/api/v1/gym/exercises/press-de-banca-barra/settings", json={"rep_min": 8, "rep_max": 12}, headers=auth)
    assert r.status_code == 200
    e = client.get("/api/v1/gym/exercises/press-de-banca-barra").json()
    assert e["config"]["rep_min"] == 8 and e["config"]["origen"] == "ajuste"
    assert client.put("/api/v1/gym/exercises/x/settings", json={"principales": ["alas"]}, headers=auth).status_code == 422
    g.write_text(g.read_text() + "\n### 2026-10-19 · Leg day\n- Hack Squat: 72.5×8\n")
    assert client.post("/api/v1/gym/exercises/aliases", json={"nombre": "Hack Squat", "exercise_id": "sentadilla-hack-maquina"}, headers=auth).status_code == 200
    h = client.get("/api/v1/gym/exercises/sentadilla-hack-maquina").json()
    assert h["ejercicio"]["sesiones"] == 3 and "hack squat" in h["alias"]


def test_decisiones_del_coach(client, auth, g, settings):
    from app import gym_plan
    sid = "s1"
    out = settings.sessions_dir / sid / "gym" / "salida"
    out.mkdir(parents=True)
    (out / "a.json").write_text(json.dumps({"tipo": "descarga", "alcance": "ejercicio", "objetivo_de": "Press", "ejercicio_id": "press-de-banca-barra",
                                            "recomendacion": "Descarga una semana", "motivo": "estancado", "datos": ["3 sesiones iguales"]}))
    (out / "b.json").write_text(json.dumps({"tipo": "inventado", "recomendacion": "x"}))  # no valida → se descarta
    rut = {"dias": {"0": {"nombre": "Leg day", "ejercicios": [{"nombre": "Prensa", "series": 3, "rep_min": 8, "rep_max": 12}]}}}
    (out / "c.json").write_text(json.dumps({"tipo": "reorganizar", "alcance": "rutina", "recomendacion": "Rutina", "motivo": "m",
                                            "datos": ["d"], "rutina": rut, "nombre_rutina": "Propuesta"}))
    assert gym_plan.ingerir(sid, "run-1") == 2 and not list(out.glob("*.json"))
    pend = client.get("/api/v1/gym/coach/decisions?estado=propuesta").json()
    assert len(pend) == 2 and all(d["fuente"] == "coach" for d in pend)
    desc = next(d for d in pend if d["tipo"] == "descarga")
    assert client.post(f"/api/v1/gym/coach/decisions/{desc['id']}/reject", headers=auth).json()["estado"] == "rechazada"
    assert client.post(f"/api/v1/gym/coach/decisions/{desc['id']}/accept", headers=auth).status_code == 409
    ro = next(d for d in pend if d["tipo"] == "reorganizar")
    a = client.post(f"/api/v1/gym/coach/decisions/{ro['id']}/accept", headers=auth).json()
    assert a["estado"] == "aplicada" and a["payload"]["aplicado"]["borrador"]  # sin rutina activa: nueva en borrador
    assert any(r["nombre"] == "Propuesta" and r["estado"] == "draft" for r in client.get("/api/v1/gym/routines").json())
    # preparar() deja el estado del entrenador para el MCP
    gym_plan.preparar(sid)
    est = json.loads((settings.sessions_dir / sid / "gym/estado.json").read_text())
    assert est["hoy"] == HOY.isoformat() and len(est["decisiones"]) == 2


def test_informes_sin_duplicados(client, auth, g):
    a = client.get("/api/v1/gym/reports?tipo=semanal").json()
    b = client.get("/api/v1/gym/reports?tipo=semanal").json()
    assert len(a) == len(b) == 2 and {r["desde"] for r in a} == {"2026-10-05", "2026-10-12"}
    d = client.get(f"/api/v1/gym/reports/{a[0]['id']}").json()["datos"]
    assert d["sesiones_hechas"] == 5 and d["cumplimiento"] == 100 and d["texto"]
    m = client.get("/api/v1/gym/reports?tipo=mensual").json()
    assert all(r["tipo"] == "mensual" for r in m)
    r = client.post("/api/v1/gym/reports/generate", json={"tipo": "semanal", "desde": "2026-10-14"}, headers=auth).json()
    assert r["desde"] == "2026-10-12" and len(client.get("/api/v1/gym/reports?tipo=semanal").json()) == 2


CSV = """title,start_time,end_time,exercise_title,set_type,weight_kg,reps,rpe,exercise_notes,duration_seconds,distance_km
PechoTriceps,"20 oct 2026, 18:00","20 oct 2026, 19:05",Press de Banca (Barra),warmup,40,10,,,,
PechoTriceps,"20 oct 2026, 18:00","20 oct 2026, 19:05",Press de Banca (Barra),failure,60,10,,,,
Leg Day,"12 oct 2026, 18:00","12 oct 2026, 19:00",Sentadilla Hack (Máquina),normal,70,8,,,,
"""


def test_importacion_hevy_idempotente(client, auth, g):
    antes = g.read_text()
    p = client.post("/api/v1/gym/import/hevy", json={"texto": CSV, "archivo": "w.csv"}, headers=auth).json()
    assert [n["fecha"] for n in p["resumen"]["nuevos"]] == ["2026-10-20"] and len(p["resumen"]["ya_registrados"]) == 1
    assert g.read_text() == antes  # la vista previa no escribe
    a = client.post(f"/api/v1/gym/import/{p['id']}/apply", headers=auth).json()
    assert a["estado"] == "applied" and a["resumen"]["aplicadas"] == 1
    assert "### 2026-10-20 · Push" in g.read_text() and "40×10 (cal.)" in g.read_text()
    assert client.post(f"/api/v1/gym/import/{p['id']}/apply", headers=auth).status_code == 409
    w = client.get("/api/v1/gym/workouts/2026-10-20-push").json()
    assert w["hevy_traza"]["duracion_min"] == 65 and w["duracion_min"] == 65
    p2 = client.post("/api/v1/gym/import/hevy", json={"texto": CSV}, headers=auth).json()
    assert p2["resumen"]["nuevos"] == []  # idempotente
    bad = client.post("/api/v1/gym/import/hevy", json={"texto": "a,b\n1,2"}, headers=auth).json()
    assert bad["estado"] == "error" and bad["errores"]
    assert client.get("/api/v1/gym/imports").json()["trazas"] == 2


def test_requiere_sesion_y_csrf(client, auth, g):
    client.post("/api/v1/auth/logout", headers=auth)
    assert client.get("/api/v1/gym/overview").status_code == 401
    assert client.post("/api/v1/gym/recovery", json={"fecha": "2026-10-19"}).status_code in (401, 403)


def test_editar_conserva_lo_no_cambiado(client, auth, g):
    rec = client.get("/api/v1/gym/recommendations").json()
    plan = client.post("/api/v1/gym/recommendations/siguiente/accept", json={"huella": rec["siguiente"]["huella"]}, headers=auth).json()
    filas = [{"id": e["id"], "nombre": e["nombre"], "series": e["series"], "rep_min": e["rango"][0], "rep_max": e["rango"][1],
              "peso": e["objetivo"]["top"]["peso"], "reps": e["objetivo"]["top"]["reps"], "descanso_s": e["descanso_s"]} for e in plan["ejercicios"]]
    filas[1]["peso"] = 45
    d = client.patch(f"/api/v1/gym/plans/{plan['id']}", json={"ejercicios": filas, "version_base": 1}, headers=auth).json()
    assert d["version"] == 2
    assert not d["ejercicios"][0].get("editado") and d["ejercicios"][0]["objetivo"]["motivo"] == plan["ejercicios"][0]["objetivo"]["motivo"]
    assert d["ejercicios"][1]["editado"] and d["ejercicios"][1]["objetivo"]["top"]["peso"] == 45


def test_rutina_del_coach_no_salta_la_confirmacion(client, auth, g):
    from app import db as dbm
    from app.models import GymCoachDecision, GymRoutine
    rutina = {"dias": {"lunes": {"nombre": "Push", "ejercicios": [{"nombre": "Press banca", "series": 3, "rep_min": 6, "rep_max": 10}]}}}
    with dbm.session_scope() as s:
        s.add(GymRoutine(id="r1", name="Actual", status="active", created_by="prueba"))
        d = GymCoachDecision(scope="rutina", kind="reorganizar", status="propuesta", source="coach", payload={"rutina": rutina})
        s.add(d)
        s.flush()
        did = d.id
    r = client.post(f"/api/v1/gym/coach/decisions/{did}/accept", json={}, headers=auth)
    assert r.status_code == 428
    assert client.get("/api/v1/gym/coach/decisions?estado=propuesta").json()[0]["id"] == did
