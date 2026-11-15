import json
import subprocess
import sys

import pytest

from app.config import ROOT
from app.core import model_gateway as mg
from app.core import orchestrator as orq


def row(pct, name="seven_day", available=True):
    return {"available": available, "windows": [{"name": name, "utilization": pct}]}


def uso(claude=0.1, terra=0.1):
    return {"claude": row(claude), "antigravity-flash": row(0.9), "antigravity-opus": row(0.9), "codex-terra": row(terra)}


def test_perfil_elige_modelo():
    assert mg.route("deep", uso()).model == "opus" and mg.route("fast", uso()).model == "sonnet"


def test_perfil_desconocido():
    with pytest.raises(ValueError):
        mg.route("barato", uso())


def test_relevo_real_cuando_claude_se_agota():
    r = mg.route("standard", uso(claude=0.95))
    assert r.provider == "codex-terra" and r.model == "gpt-5.6-terra"


def test_solo_claude_admite_datos_sensibles():
    assert [p.key for p in mg.PROVIDERS.values() if p.sensitive_ok] == ["claude"]


def test_datos_sensibles_no_salen_a_otros_proveedores():
    r = mg.route("standard", uso(claude=0.95), sensitive=True)
    assert r.provider == "claude" and "sensibles" in r.reason


@pytest.mark.parametrize("texto,esperado", [
    ("cuánto gasto al mes en comida y cuánto ahorro", "finanzas"), ("analiza mi rutina de gym", "entrenador"),
    ("cuánto llevo ahorrado este mes", "finanzas"), ("revisa mi entrenamiento de pecho", "entrenador"), ("esta unidad no funciona", "jarvis"),
    ("cuándo es el examen de la uoc", "tutor"), ("revisa esta oferta de empleo", "carrera"),
    ("hola qué tal", "jarvis"), ("el gym me cuesta dinero", "jarvis"),
])
def test_orquestador_enruta(texto, esperado):
    assert orq.pick(texto).name == esperado


def test_finanzas_es_sensible_y_no_ve_la_vault():
    f = orq.SPECIALISTS["finanzas"]
    assert f.sensitive and "memory.search" not in f.tools
    assert all(c.startswith("finance.") for c in f.capabilities) and not f.vault


def test_mcp_pos_habla_el_protocolo():
    mcp = ROOT / "control-center/pos/pos_mcp.py"
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "pos_tools", "arguments": {}}}]
    out = subprocess.run([sys.executable, str(mcp)], input="\n".join(json.dumps(m) for m in msgs), capture_output=True, text=True,
                         env={"POS_SOCK": "/nonexistent/pos.sock"}, timeout=10).stdout.splitlines()
    r = [json.loads(x) for x in out]
    assert r[0]["result"]["serverInfo"]["name"] == "pos"
    assert {t["name"] for t in r[1]["result"]["tools"]} == {"pos_read", "pos_action", "pos_tools"}
    assert r[2]["result"]["isError"] is True  # sin socket lo dice, no se inventa una respuesta


def test_definicion_de_finanzas_sin_vias_de_escape():
    t = (ROOT / "control-center/agents/finanzas.md").read_text()
    cab = t.split("---")[1]
    assert "tools: mcp__pos__pos_read, mcp__pos__pos_action, mcp__pos__pos_tools" in cab
    for prohibida in ("Bash", "WebFetch", "WebSearch", "Edit", "Write"):
        assert prohibida not in cab


from app import db as dbm  # noqa: E402
from app.core import gateway, runs  # noqa: E402
from app.models import AgentRun, ChatSession, Message, RunToken  # noqa: E402


@pytest.fixture()
def turno(client, monkeypatch):
    """Sustituye solo al Host Agent: todo lo demás es el camino real."""
    enviados = []

    async def fake(payload):
        enviados.append(payload)
        with dbm.session_scope() as s:
            assert s.query(RunToken).count() == 1  # la credencial vive durante el turno
        yield {"type": "result", "result": "Respuesta de prueba", "session_id": "12345678-1234-1234-1234-1234567890ab"}
    monkeypatch.setattr("app.sessions.hostagent_stream", fake)
    monkeypatch.setattr(runs.model_usage, "latest", lambda: uso())
    monkeypatch.setattr(runs.events, "loop", lambda: None)  # cada prueba ejecuta el turno a mano, en su propio bucle
    return enviados


def test_por_defecto_bajo_demanda(client):
    """Sin el archivo de modo, bajo demanda: la sesión de tmux ya no existe desde el 05/11."""
    assert runs.mode() == "runs"


def test_cambiar_modo_sin_reiniciar(client, auth):
    assert client.post("/api/v1/runtime", json={"modo": "runs"}, headers=auth).json()["modo"] == "runs"
    assert client.get("/api/v1/runtime").json()["modo"] == "runs"
    assert client.post("/api/v1/runtime", json={"modo": "otro"}, headers=auth).status_code == 422
    client.post("/api/v1/runtime", json={"modo": "tmux"}, headers=auth)
    assert runs.mode() == "tmux"


async def test_turno_completo(client, turno):
    r = runs.submit("cuánto ahorro este mes", "ana")
    assert r["especialista"] == "finanzas"
    with dbm.session_scope() as s:
        sid = s.query(ChatSession).filter(ChatSession.kind == "runtime").one().id
        run_id = s.query(AgentRun).one().id
    await runs._execute(sid, run_id, "cuánto ahorro este mes", False)
    p = turno[0]
    assert p["vault"] is False and p["internet"] is False and p["pos_token"] and "Contexto" in p["system_prompt"]
    with dbm.session_scope() as s:
        assert s.query(RunToken).count() == 0  # al terminar el turno la credencial desaparece
        assert s.query(Message).filter(Message.role == "assistant").one().content == "Respuesta de prueba"
    assert runs.messages()["items"][-1]["text"] == "Respuesta de prueba"


def test_una_conversacion_por_dia_y_especialista():
    assert runs.session_id("jarvis", "2026-11-04") == runs.session_id("jarvis", "2026-11-04")
    assert runs.session_id("jarvis", "2026-11-04") != runs.session_id("jarvis", "2026-11-05")
    assert runs.session_id("jarvis", "2026-11-04") != runs.session_id("finanzas", "2026-11-04")


def test_ordenes_de_timers(client, settings, turno):
    import asyncio
    d = settings.data_dir / "ordenes"
    d.mkdir(parents=True, exist_ok=True)
    (d / "1.json").write_text(json.dumps({"text": "Prepara el briefing"}))
    (d / "2.json").write_text("roto")
    (d / ".tmp.a").write_text("a medias")
    assert asyncio.run(runs.ingest_orders()) == 1
    assert [p.name for p in d.iterdir()] == [".tmp.a"]


def test_consolidar_sin_conversacion_no_gasta(client):
    assert runs.consolidate("2026-11-04") is None


def test_consolidar_solo_puede_proponer(client, turno):
    day = runs._day()
    runs.submit("x" * 300, "ana")
    r = runs.consolidate(day)
    assert r["especialista"] == "memoria"
    with dbm.session_scope() as s:
        c = s.get(ChatSession, runs.session_id("memoria", day))
        assert c.permissions["pos"]["capabilities"] == ["memory.fact.propose"]
        assert c.permissions["vault"] is True and c.permissions["internet"] is False


def test_consolidacion_apagada_por_defecto(client, monkeypatch):
    import asyncio
    from datetime import datetime
    llamadas = []
    monkeypatch.setattr(runs, "consolidate", lambda d: llamadas.append(d))
    asyncio.run(runs.maintenance(datetime(2026, 11, 4, 23, 40, tzinfo=runs.TZ), {}))
    assert llamadas == []


def test_prompts_de_todos_los_agentes():
    for n in runs.AGENT_FILES:
        assert len(runs._body(n)) > 50


def test_dos_mensajes_a_la_vez_el_primero_del_dia(client, turno):
    """Sin reintento, uno de los dos falla por clave duplicada en PostgreSQL."""
    from concurrent.futures import ThreadPoolExecutor
    for _ in range(3):
        with dbm.session_scope() as s:
            s.query(Message).delete()
            s.query(AgentRun).delete()
            s.query(ChatSession).filter(ChatSession.kind == "runtime").delete()
        with ThreadPoolExecutor(4) as ex:
            r = list(ex.map(lambda i: runs.submit(f"hola {i}", "ana"), range(4)))
        assert len({x["run_id"] for x in r}) == 4
        with dbm.session_scope() as s:
            assert s.query(ChatSession).filter(ChatSession.kind == "runtime").count() == 1


def test_una_orden_no_se_procesa_dos_veces(client, settings, turno):
    import asyncio
    d = settings.data_dir / "ordenes"
    d.mkdir(parents=True, exist_ok=True)
    (d / "1.json").write_text(json.dumps({"text": "Una sola vez"}))

    async def dos():
        return await asyncio.gather(runs.ingest_orders(), runs.ingest_orders())
    assert sum(asyncio.run(dos())) == 1
    with dbm.session_scope() as s:
        assert s.query(Message).filter(Message.role == "user").count() == 1


def test_relevo_responde_sin_herramientas(client, turno, monkeypatch):
    import asyncio
    monkeypatch.setattr(runs.model_usage, "latest", lambda: uso(claude=0.95))
    pedido = {}

    async def fake(path, **k):
        pedido.update(path=path, **k["json"])
        return {"text": "Respuesta de Codex"}
    monkeypatch.setattr(runs.hostagent, "call", fake)
    runs.submit("hola qué tal", "ana")
    with dbm.session_scope() as s:
        c = s.query(ChatSession).filter(ChatSession.kind == "runtime").one()
        sid, run_id = c.id, s.query(AgentRun).one().id
    route = mg.route("standard", runs.model_usage.latest())
    asyncio.run(runs._execute(sid, run_id, "hola qué tal", False, route))
    assert pedido["path"] == "/v1/models/codex-terra/ask" and "Contexto" not in pedido["prompt"]
    assert turno == []  # no se abrió ningún turno de Claude
    with dbm.session_scope() as s:
        assert s.query(Message).filter(Message.role == "assistant").one().content == "Respuesta de Codex"


def test_finanzas_nunca_usa_el_relevo(client, turno, monkeypatch):
    monkeypatch.setattr(runs.model_usage, "latest", lambda: uso(claude=0.95))
    assert mg.route("standard", runs.model_usage.latest(), sensitive=True).provider == "claude"


def test_voz_escribe_la_respuesta(client, turno, tmp_path, monkeypatch):
    import asyncio
    monkeypatch.setattr(runs, "ROOT", tmp_path)
    (tmp_path / "control-center/agents").mkdir(parents=True)
    monkeypatch.setattr(runs, "_body", lambda n: "x")
    runs.submit("hola", "voz", voz="20261104-120000")
    with dbm.session_scope() as s:
        sid, run_id = s.query(ChatSession).filter(ChatSession.kind == "runtime").one().id, s.query(AgentRun).one().id
    asyncio.run(runs._execute(sid, run_id, "hola", False, None, "20261104-120000"))
    assert (tmp_path / "data/voz/salida/20261104-120000.md").read_text() == "Respuesta de prueba"


def test_id_de_voz_raro_se_descarta(client, settings, turno):
    import asyncio
    d = settings.data_dir / "ordenes"
    d.mkdir(parents=True, exist_ok=True)
    (d / "1.json").write_text(json.dumps({"text": "x", "voz": "../../evil"}))
    assert asyncio.run(runs.ingest_orders()) == 0


def test_solo_jarvis_puede_pasar_al_relevo():
    assert all(e.sensitive for e in orq.SPECIALISTS.values()) and not orq.DEFAULT.sensitive


def test_tutor_hereda_su_definicion_con_canvas(client, turno):
    from app.models import AgentDefinition, AgentVersion
    spec = {"name": "tutor", "target": "panel", "description": "Tutor de la UOC", "instructions": "Eres el tutor de la UOC", "model": "opus", "level": "execute",
            "internet": True, "vault": True, "subagents": True, "virtual_computer": True, "tools": []}
    with dbm.session_scope() as s:
        s.add(AgentDefinition(id="tutor", name="tutor", origin="panel", status="active", current_version=1))
        s.flush()
        s.add(AgentVersion(agent_id="tutor", version=1, spec=spec, rendered="x", author="prueba"))
    runs.submit("cuándo es la pec", "ana")
    with dbm.session_scope() as s:
        c = s.query(ChatSession).filter(ChatSession.kind == "runtime").one()
        p = c.permissions
        assert c.agent_id == "tutor" and c.model == "opus" and p["level"] == "execute" and p["vault"] and p["internet"]
        assert p["vc"]["enabled"] and p["vc"]["profile"] == "canvas" and p["subagents"]
        assert "Eres el tutor" in p["system_prompt"]


def test_cambiar_permisos_vale_para_la_conversacion_abierta(client, turno, monkeypatch):
    runs.submit("hola", "ana")
    monkeypatch.setattr(orq, "DEFAULT", orq.Specialist("jarvis", "standard", ("memory.facts",), ("task.create",), ()))
    runs.submit("otra", "ana")
    with dbm.session_scope() as s:
        assert s.query(ChatSession).filter(ChatSession.kind == "runtime").one().permissions["pos"]["capabilities"] == ["task.create"]
