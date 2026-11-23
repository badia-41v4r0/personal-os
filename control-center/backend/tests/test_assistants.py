import pytest

from app import db as dbm
from app.core import actions, gateway, orchestrator as orq, runs
from app.models import Budget, ChatSession, Goal, LedgerAccount
from app.modules import agent_caps, finance  # noqa: F401  (registran capacidades y lecturas)


@pytest.fixture()
def turno(client, monkeypatch):
    async def fake(payload):
        yield {"type": "result", "result": "Hola", "session_id": "12345678-1234-1234-1234-1234567890ab"}
    monkeypatch.setattr("app.sessions.hostagent_stream", fake)
    monkeypatch.setattr(runs.model_usage, "latest", lambda: {})
    monkeypatch.setattr(runs.events, "loop", lambda: None)


@pytest.mark.parametrize("key", list(orq.SECTIONS))
def test_cada_apartado_tiene_lo_que_necesita(key):
    s = orq.SECTIONS[key]
    assert set(s.tools) <= set(gateway.TOOLS), key
    assert set(s.capabilities) <= set(actions.REGISTRY), key
    assert s.sensitive  # ninguno pasa al relevo de solo texto
    if not s.panel_agent:
        assert len(runs._body(s.name)) > 50


def test_ningun_apartado_mueve_dinero_ni_mezcla_finanzas():
    for k, s in orq.SECTIONS.items():
        if k != "finanzas":
            assert not [c for c in s.capabilities if c.startswith("finance")], k
            assert not [t for t in s.tools if t.startswith("finance")], k


def test_finanzas_sin_vault():
    assert orq.SECTIONS["finanzas"].vault is False


def test_apartado_usa_su_especialista_aunque_hable_de_otra_cosa(client, auth, turno):
    r = client.post("/api/v1/assistants/salud/messages", json={"text": "cuánto gasto en el gimnasio"}, headers=auth)
    assert r.json()["especialista"] == "salud"
    with dbm.session_scope() as s:
        c = s.get(ChatSession, runs.section_session_id(orq.SECTIONS["salud"], runs._day()))
        assert c.permissions["pos"]["agent"] == "salud" and "health.log" in c.permissions["pos"]["capabilities"]


def test_conversaciones_separadas_por_apartado(client, auth, turno):
    client.post("/api/v1/assistants/salud/messages", json={"text": "uno"}, headers=auth)
    assert [i["text"] for i in client.get("/api/v1/assistants/salud/messages").json()["items"]] == ["uno"]
    assert client.get("/api/v1/assistants/agenda/messages").json()["items"] == []


def test_apartado_desconocido(client, auth):
    assert client.post("/api/v1/assistants/nada/messages", json={"text": "x"}, headers=auth).status_code == 404
    assert client.get("/api/v1/assistants/nada/messages").status_code == 404


def test_estado_del_turno(client, auth, turno):
    client.post("/api/v1/assistants/agenda/messages", json={"text": "x"}, headers=auth)
    assert client.get("/api/v1/assistants/agenda/state").json()["current_run"]
    assert client.get("/api/v1/assistants/salud/state").json()["current_run"] is None


def test_coach_es_el_del_gym(client, auth, monkeypatch):
    enviados = []

    async def fake(payload):
        enviados.append(payload)
        yield {"type": "result", "result": "ok", "session_id": "12345678-1234-1234-1234-1234567890ab"}
    monkeypatch.setattr("app.sessions.hostagent_stream", fake)
    r = client.post("/api/v1/assistants/coach/messages", json={"text": "qué toca"}, headers=auth)
    assert r.status_code == 200 and r.json()["session_id"]
    assert client.get("/api/v1/assistants/coach/messages").json()["items"][0]["text"] == "qué toca"


def test_objetivo_por_el_agente(client):
    r = actions.request("goal.create", {"titulo": "Correr 10 km"}, actor="objetivos")
    assert r["status"] == "done"
    with dbm.session_scope() as s:
        assert s.query(Goal).one().title == "Correr 10 km"


def test_abrir_el_coach_no_crea_nada(client, auth):
    assert client.get("/api/v1/assistants/coach/messages").json()["items"] == []
    assert client.get("/api/v1/assistants/coach/state").json()["current_run"] is None
    with dbm.session_scope() as s:
        assert s.query(ChatSession).filter(ChatSession.name == "Coach del gym").count() == 0


AJENO = {"entrenador": ("finance", "uni", "career", "task", "calendar", "mail", "goal", "lifestyle", "ocio", "fantasy", "note"),
         "finanzas": ("gym", "uni", "career", "task", "calendar", "mail", "goal", "lifestyle", "ocio", "fantasy", "note", "memory.search", "memory.context"),
         "salud": ("gym", "finance", "uni", "career", "task", "calendar", "mail", "goal", "lifestyle", "ocio", "fantasy", "note", "memory.search"),
         "carrera": ("gym", "finance", "uni", "calendar", "mail", "goal", "lifestyle", "ocio", "fantasy", "note", "memory.search"),
         "tutor": ("gym", "finance", "career", "calendar", "mail", "goal", "lifestyle", "ocio", "fantasy", "note", "memory.search", "tasks.list"),
         "objetivos": ("gym", "finance", "uni", "career", "task", "calendar", "mail", "lifestyle", "ocio", "fantasy", "note", "memory.search"),
         "estilo": ("gym", "finance", "uni", "career", "task", "calendar", "mail", "goal", "ocio", "fantasy", "note", "memory.search"),
         "ocio": ("gym", "finance", "uni", "career", "task", "calendar", "mail", "goal", "lifestyle", "fantasy", "note", "memory.search")}


@pytest.mark.parametrize("nombre", list(AJENO))
def test_cada_chat_solo_ve_lo_suyo(nombre):
    s = orq.SPECIALISTS.get(nombre) if nombre == "entrenador" else orq.SECTIONS[nombre]
    for x in (*s.tools, *s.capabilities):
        assert not x.startswith(AJENO[nombre]), (nombre, x)


def test_solo_conocimiento_ve_la_vault_entera():
    enteras = [k for k, s in orq.SECTIONS.items() if s.vault and not s.vault_paths]
    assert enteras == ["conocimiento"]
    assert not [k for k, s in orq.SECTIONS.items() if s.vault_write]


def test_contexto_de_apartado_sin_tareas_de_otros(client, auth, turno):
    client.post("/api/v1/assistants/salud/messages", json={"text": "hola"}, headers=auth)
    with dbm.session_scope() as s:
        c = s.get(ChatSession, runs.section_session_id(orq.SECTIONS["salud"], runs._day()))
        assert '"tareas"' not in c.permissions["system_prompt"] and "Solo tu apartado" in c.permissions["system_prompt"]
        assert c.permissions["vault"] is False


def test_coach_con_acciones_y_vault_limitada(client, auth):
    from app.gym_plan import coach_scope
    e = coach_scope()
    assert e["vault_paths"] == ["Jarvis/Areas/Gym.md", "Jarvis/Sistema/gym.md"]
    assert "gym.workout.replace" in e["pos"]["capabilities"] and e["pos"]["tools"] == ["memory.facts"]
    assert set(e["pos"]["capabilities"]) <= set(actions.REGISTRY)


def test_inicio_no_mezcla_los_chats_de_apartado(client, auth, turno):
    client.post("/api/v1/assistants/salud/messages", json={"text": "de salud"}, headers=auth)
    assert runs.messages()["items"] == []


def test_presupuesto_sigue_vigente_y_cero_lo_quita(client, auth):
    with dbm.session_scope() as db:
        a = LedgerAccount(name="expense:prueba-ocio", kind="expense", currency="EUR")
        db.add(a)
        db.flush()
        db.add(Budget(account_id=a.id, month="2026-01", amount=100))
        db.flush()
        assert finance.budgets_of(db, "2026-03") == {a.id: 100}
        assert finance.budgets_of(db, "2025-12") == {}
        db.add(Budget(account_id=a.id, month="2026-02", amount=0))
        db.flush()
        assert finance.budgets_of(db, "2026-03") == {}
        assert finance._months_before("2026-02", 3) == ["2026-01", "2025-12", "2025-11"]


def test_el_agente_fija_presupuesto(client):
    with dbm.session_scope() as db:
        db.add(LedgerAccount(name="expense:prueba-ropa", kind="expense", currency="EUR"))
    r = actions.request("finance.budget.set", {"cuenta": "expense:prueba-ropa", "importe": 120}, actor="finanzas")
    assert r["status"] == "done"
    assert client.get("/api/v1/health").status_code == 200


def _gym(tmp_path, monkeypatch):
    from app import config
    v = config.get_settings().vault / "Jarvis/Areas"
    v.mkdir(parents=True, exist_ok=True)
    f = v / "Gym.md"
    f.write_text("# Gym\n\n## Registro\n\n### 2026-11-03 · Push\n- Press: 50×8\n\n### 2026-11-05 · Lower\n- Hack: 80×5\n\n## Otra\nnota\n", encoding="utf-8")
    return f


def test_corregir_un_entreno_y_deshacerlo(client, tmp_path, monkeypatch):
    f = _gym(tmp_path, monkeypatch)
    antes = f.read_text(encoding="utf-8")
    r = actions.request("gym.workout.replace", {"fecha": "2026-11-05", "sesion": "Lower", "texto": "Sentadilla Hack: 80x6, 70x6"}, actor="coach")
    assert r["status"] == "done", str(r)[:600]
    t = f.read_text(encoding="utf-8")
    assert "### 2026-11-05 · Lower" in t and "80×6" in t and "80×5" not in t and "- Press: 50×8" in t and "## Otra" in t
    assert actions.undo(r["id"], "ana")["status"] == "undone"
    from app.modules import mirror  # la nota es una copia: vuelve a lo de antes, con el aviso
    assert f.read_text(encoding="utf-8") == antes.replace("## Registro\n\n", "## Registro\n\n" + mirror.AVISO_GYM + "\n\n")


def test_corregir_un_entreno_que_no_existe(client, tmp_path, monkeypatch):
    _gym(tmp_path, monkeypatch)
    r = actions.request("gym.workout.replace", {"fecha": "2026-01-01", "sesion": "Lower", "texto": "Hack: 80x6"}, actor="coach")
    assert r["status"] == "failed"


def test_una_rutina_entra_por_la_cola_y_escribe_solo_ella(client, turno):
    import asyncio
    import json
    from app.config import get_settings
    runs.order_routine("cierre", "haz el cierre")
    d = get_settings().data_dir / "ordenes"
    assert json.loads(next(d.glob("*.json")).read_text())["rutina"] == "cierre"
    assert asyncio.run(runs.ingest_orders()) == 1
    with dbm.session_scope() as s:
        c = s.get(ChatSession, runs.session_id("rutina", runs._day()))
        assert c.permissions["vault_write"] is True and c.permissions["level"] == "propose" and c.permissions["gym"] is True
    assert runs.messages()["items"] == []


def test_la_rutina_avisa_con_su_respuesta_salvo_silencio(monkeypatch):
    import asyncio
    enviado = []

    async def call(path, **kw):
        enviado.append(kw["json"])
    monkeypatch.setattr(runs.hostagent, "call", call)
    asyncio.run(runs._deliver("briefing", "done", "Buenos días"))
    asyncio.run(runs._deliver("cierre", "done", runs.SILENCIO))
    asyncio.run(runs._deliver("semanal", "failed", ""))
    assert enviado[0]["text"] == "Buenos días" and len(enviado) == 2 and "ha fallado" in enviado[1]["text"]


def test_encargo_pide_aprobacion_y_va_a_la_cola(client, monkeypatch):
    from app.config import get_settings
    assert actions.request("encargo.create", {"repo": "x", "tipo": "plan", "titulo": "t", "detalle": "d"}, actor="jarvis")["status"] == "pending"
    r = actions.request("video.analyze", {"url": "https://www.tiktok.com/@a/video/1"}, actor="jarvis")
    assert r["status"] == "done"
    f = next((get_settings().vault / "Jarvis/Videos/cola").glob("*.md"))
    assert "url: https://www.tiktok.com/@a/video/1" in f.read_text(encoding="utf-8")
    assert actions.request("video.analyze", {"url": "https://malo.example/x"}, actor="jarvis")["status"] == "failed"


def test_tras_una_accion_la_base_esta_al_dia(client):
    from sqlalchemy import select

    from app.config import get_settings
    from app.models import Task
    f = get_settings().vault / "Jarvis/Tareas.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("# Tareas\n\n## Pendientes\n", encoding="utf-8")
    assert actions.request("task.create", {"texto": "Llamar al taller", "fecha": "2026-12-01"}, actor="agenda")["status"] == "done"
    with dbm.session_scope() as db:
        assert db.scalar(select(Task).where(Task.text == "Llamar al taller")).due == "2026-12-01"
    assert actions.request("task.reschedule", {"texto": "Llamar al taller", "fecha": "2026-12-05"}, actor="agenda")["status"] == "done"
    assert "📅 2026-12-05" in f.read_text(encoding="utf-8") and f.read_text(encoding="utf-8").count("📅") == 1
    with dbm.session_scope() as db:
        assert db.scalar(select(Task).where(Task.text == "Llamar al taller")).due == "2026-12-05"


def _tareas(lineas: str):
    from app.config import get_settings
    f = get_settings().vault / "Jarvis/Tareas.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(f"# Tareas\n\nCabecera propia\n\n## Pendientes\n{lineas}\n## Hechas\n", encoding="utf-8")
    return f


def test_tareas_perdidas_se_rehacen_desde_la_base(client):
    from tests.conftest import seed_tasks
    from app.modules import vault_sync
    f = _tareas("".join(f"- [ ] Tarea {i} 📅 2026-12-0{i} #uni\n" for i in range(1, 6)) + "- [x] Vieja #personal ✅ 2026-10-01\n")
    seed_tasks(f)
    f.write_text("# Tareas\n\nCabecera propia\n\n## Pendientes\n- [ ] Tarea 1 #uni\n", encoding="utf-8")
    with dbm.session_scope() as db:
        r = vault_sync.sync_tasks(db)
    assert r["descartados"] >= 1
    t = f.read_text(encoding="utf-8")
    assert "Cabecera propia" in t and "- [ ] Tarea 5 📅 2026-12-05 #uni" in t and "- [x] Vieja #personal ✅ 2026-10-01" in t
    f.unlink()
    with dbm.session_scope() as db:
        assert vault_sync.sync_tasks(db)["rehecha"] is True
    assert "Tarea 3" in f.read_text(encoding="utf-8")


def test_de_la_nota_solo_se_acepta_marcar_casillas(client):
    from sqlalchemy import select

    from app.models import Task
    from app.modules import vault_sync
    from tests.conftest import seed_tasks
    f = _tareas("".join(f"- [ ] Tarea {i} #uni\n" for i in range(1, 6)))
    seed_tasks(f)
    # a mano: marca la 1, borra la 2, cambia el texto de la 3 y añade una nueva
    f.write_text(f.read_text(encoding="utf-8").replace("- [ ] Tarea 1 #uni", "- [x] Tarea 1 #uni ✅ 2026-11-05")
                 .replace("- [ ] Tarea 2 #uni\n", "").replace("Tarea 3", "Tarea tres") + "- [ ] Nueva a mano #uni\n", encoding="utf-8")
    with dbm.session_scope() as db:
        r = vault_sync.sync_tasks(db)
    assert r["marcas"] == 1 and r["descartados"] >= 1
    with dbm.session_scope() as db:
        assert db.scalar(select(Task).where(Task.text == "Tarea 1")).done  # la casilla sí se acepta
        assert db.scalar(select(Task).where(Task.text == "Tarea 2")).removed_at is None  # el borrado no
        assert db.scalar(select(Task).where(Task.text == "Tarea tres")) is None and db.scalar(select(Task).where(Task.text == "Nueva a mano")) is None
    t = f.read_text(encoding="utf-8")
    assert "Tarea 2" in t and "Tarea 3" in t and "Tarea tres" not in t and "Nueva a mano" not in t and "- [x] Tarea 1" in t
    assert "Copia generada" in t
    avisos = list((__import__("app.config", fromlist=["x"]).get_settings().data_dir / "avisos").glob("*.json"))
    assert avisos and "copia de la base de datos" in avisos[0].read_text()
    with dbm.session_scope() as db:  # sin nuevos cambios a mano, no vuelve a avisar ni a tocar nada
        assert vault_sync.sync_tasks(db)["descartados"] == 0


def test_la_primera_sincronizacion_siembra_la_base_desde_la_nota(client):
    from sqlalchemy import select

    from app.models import Task
    from app.modules import vault_sync
    _tareas("- [ ] Lo de antes #uni\n")
    with dbm.session_scope() as db:
        assert vault_sync.sync_tasks(db)["sembrada"] is True  # lo escrito justo antes del cambio no se pierde
    with dbm.session_scope() as db:
        assert db.scalar(select(Task).where(Task.text == "Lo de antes")) is not None
        assert "sembrada" not in vault_sync.sync_tasks(db)


def test_el_registro_del_gym_se_rehace_igual_desde_la_base(client):
    from app.config import get_settings
    from app.modules import vault_sync
    f = get_settings().vault / "Jarvis/Areas/Gym.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    bloques = [f"### 2026-10-0{i} · Push\n_Hevy: Pecho_\n- Press de Banca (Barra): 40×10 (cal.), 60×8\n- Dominada: PC×6" for i in range(1, 7)]
    original = "# Gym\n\n## Perfil\n- nota\n\n## Registro\n\n" + "\n\n".join(bloques) + "\n"
    f.write_text(original, encoding="utf-8")
    with dbm.session_scope() as db:
        vault_sync.sync_workouts(db)
    f.write_text("# Gym\n\n## Perfil\n- nota\n\n## Registro\n", encoding="utf-8")
    with dbm.session_scope() as db:
        assert vault_sync.sync_workouts(db)["descartados"] == 1
    from app.modules import mirror
    assert f.read_text(encoding="utf-8").replace(mirror.AVISO_GYM + "\n\n", "") == original


def test_el_pipeline_de_trabajo_sale_de_la_base(client, auth):
    from app.config import get_settings
    f = get_settings().vault / "Jarvis/Areas/Trabajo.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("# Trabajo\n\n## Pipeline de candidaturas\n| Empresa | Puesto | Estado | Fecha | Próximo paso | Follow-up |\n|---|---|---|---|---|---|\n\nEstados: x\n\n## Bloqueos\n-\n", encoding="utf-8")
    r = client.post("/api/v1/me/career/applications", json={"empresa": "Acme", "puesto": "FDE | IA", "estado": "aplicado"}, headers=auth)
    assert r.status_code < 300, r.text
    t = f.read_text(encoding="utf-8")
    assert "| Acme | FDE / IA | aplicado |" in t and "Estados: x" in t and "## Bloqueos" in t
    client.patch(f"/api/v1/me/career/applications/{r.json()['id']}", json={"estado": "entrevista"}, headers=auth)
    t = f.read_text(encoding="utf-8")
    assert "| entrevista |" in t and t.count("Acme") == 1
