import asyncio
import time

from app import events, sessions

CLAUDE_SID = "11111111-2222-3333-4444-555555555555"


def fake_stream(calls, delay=0.05):
    async def gen(payload):
        calls.append(payload)
        await asyncio.sleep(delay)
        yield {"type": "system", "subtype": "init", "session_id": CLAUDE_SID}
        yield {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Ho"}}}
        yield {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "/trabajo/a.md"}}]}}
        yield {"type": "assistant", "message": {"content": [{"type": "text", "text": "Hola"}]}}
        yield {"type": "result", "result": f"Respuesta a: {payload['prompt']}", "session_id": CLAUDE_SID, "total_cost_usd": 0.01}
        yield {"type": "_exit", "code": 0}
    return gen


def wait(client, sid, n, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        runs = client.get(f"/api/v1/agents/runs?session_id={sid}").json()
        if len(runs) >= n and all(r["status"] not in ("queued", "running") for r in runs):
            return runs
        time.sleep(0.05)
    raise AssertionError(runs)


def new(client, auth, **kw):
    body = {"name": "Investigación", "level": "propose", "internet": True} | kw
    r = client.post("/api/v1/sessions", json=body, headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


def test_crear_y_listar(client, auth):
    s = new(client, auth)
    assert s["kind"] == "independent" and s["permissions"]["level"] == "propose"
    assert s["workdir"] == f"data/sesiones/{s['id']}/trabajo"
    assert any(x["id"] == s["id"] for x in client.get("/api/v1/sessions").json())


def test_niveles_no_permitidos(client, auth):
    for bad in ({"level": "execute"}, {"model": "haiku"}, {"name": ""}, {"minutes": 500}):
        assert client.post("/api/v1/sessions", json={"name": "x"} | bad, headers=auth).status_code == 422


def test_turnos_en_orden_y_reanudacion(client, auth, monkeypatch):
    calls = []
    monkeypatch.setattr(sessions, "hostagent_stream", fake_stream(calls))
    s = new(client, auth)
    client.post(f"/api/v1/sessions/{s['id']}/messages", json={"text": "uno"}, headers=auth)
    client.post(f"/api/v1/sessions/{s['id']}/messages", json={"text": "dos"}, headers=auth)
    runs = wait(client, s["id"], 2)
    assert [c["prompt"] for c in calls] == ["uno", "dos"]
    assert calls[0]["resume"] is None and calls[1]["resume"] == CLAUDE_SID  # el segundo continúa la conversación
    assert calls[0]["level"] == "propose" and calls[0]["internet"] is True and calls[0]["vault"] is False
    assert all(r["status"] == "done" and r["tools_used"] == ["Read"] for r in runs)
    msgs = client.get(f"/api/v1/sessions/{s['id']}/messages").json()
    assert [m["role"] for m in msgs] == ["user", "user", "tool", "assistant", "tool", "assistant"] or \
        [m["role"] for m in msgs if m["role"] != "tool"] == ["user", "user", "assistant", "assistant"]
    assert client.get(f"/api/v1/sessions/{s['id']}").json()["claude_session_id"] == CLAUDE_SID


def test_error_del_host_agent(client, auth, monkeypatch):
    async def boom(payload):
        raise sessions.HTTPException(429, "Hay demasiadas sesiones trabajando a la vez")
        yield  # pragma: no cover

    monkeypatch.setattr(sessions, "hostagent_stream", boom)
    s = new(client, auth)
    client.post(f"/api/v1/sessions/{s['id']}/messages", json={"text": "hola"}, headers=auth)
    r = wait(client, s["id"], 1)[0]
    assert r["status"] == "error" and "demasiadas" in r["error"]


def test_archivada_no_acepta(client, auth):
    s = new(client, auth)
    client.patch(f"/api/v1/sessions/{s['id']}", json={"archived": True}, headers=auth)
    assert client.post(f"/api/v1/sessions/{s['id']}/messages", json={"text": "x"}, headers=auth).status_code == 409


def test_main_no_es_independiente(client, auth):
    assert client.get("/api/v1/sessions/main").status_code == 404


def test_execute_solo_con_ordenador(client, auth):
    assert client.post("/api/v1/sessions", json={"name": "x", "level": "execute"}, headers=auth).status_code == 422
    r = client.post("/api/v1/sessions", json={"name": "x", "level": "execute", "virtual_computer": True, "vc_profile": "browser"}, headers=auth)
    assert r.status_code == 200 and r.json()["permissions"]["vc"] == {"enabled": True, "profile": "browser", "vc_id": None}


def test_ordenador_pedido_por_el_agente(client, auth, monkeypatch):
    calls = []
    VID = "abcdefab-1111-2222-3333-444444444444"

    def gen_factory():
        async def gen(payload):
            calls.append(payload)
            yield {"type": "system", "subtype": "init", "session_id": CLAUDE_SID}
            if len(calls) == 1:
                yield {"type": "_vc", "vc_id": VID, "profile": "terminal", "motivo": "compilar"}
            yield {"type": "result", "result": "ok", "session_id": CLAUDE_SID}
            yield {"type": "_exit", "code": 0}
        return gen

    monkeypatch.setattr(sessions, "hostagent_stream", gen_factory())
    s = client.post("/api/v1/sessions", json={"name": "x", "level": "execute", "virtual_computer": True}, headers=auth).json()
    client.post(f"/api/v1/sessions/{s['id']}/messages", json={"text": "uno"}, headers=auth)
    wait(client, s["id"], 1)
    client.post(f"/api/v1/sessions/{s['id']}/messages", json={"text": "dos"}, headers=auth)
    wait(client, s["id"], 2)
    assert calls[0]["vc"]["vc_id"] is None and calls[0]["vc"]["enabled"] is True
    assert calls[1]["vc"]["vc_id"] == VID  # el segundo turno reutiliza su ordenador
    from app.db import session_scope
    from app.models import VirtualComputer
    with session_scope() as db:
        v = db.get(VirtualComputer, VID)
        assert v.persistence == "ttl" and v.expires_at is not None and v.limits["session"] == s["id"]
    assert any(a["action"] == "vc.create" and a["actor"].startswith("agente:") for a in client.get("/api/v1/audit").json())


def test_subagentes_en_el_turno(client, auth, monkeypatch):
    calls = []
    monkeypatch.setattr(sessions, "hostagent_stream", fake_stream(calls))
    s = new(client, auth, subagents=True)
    assert s["permissions"]["subagents"] is True
    client.post(f"/api/v1/sessions/{s['id']}/messages", json={"text": "x"}, headers=auth)
    wait(client, s["id"], 1)
    assert calls[0]["subagents"] is True


def test_archivos_de_la_conversacion(client, auth, settings):
    s = new(client, auth)
    w = settings.sessions_dir / s["id"] / "trabajo"
    (w / "pec").mkdir(parents=True)
    (w / "pec/solucion.c").write_text("int main(){}")
    (settings.sessions_dir / "secreto.txt").write_text("no")
    r = client.get(f"/api/v1/sessions/{s['id']}/files").json()
    assert [i["name"] for i in r["items"]] == ["pec"]
    r = client.get(f"/api/v1/sessions/{s['id']}/files", params={"path": "pec"}).json()
    assert r["items"][0]["path"] == "pec/solucion.c"
    d = client.get(f"/api/v1/sessions/{s['id']}/download", params={"path": "pec/solucion.c"})
    assert d.status_code == 200 and d.text == "int main(){}" and "attachment" in d.headers["content-disposition"]
    for bad in ("../../secreto.txt", "/etc/passwd", "../x"):
        assert client.get(f"/api/v1/sessions/{s['id']}/download", params={"path": bad}).status_code in (403, 404)


def test_adjuntos(client, auth, settings, monkeypatch):
    calls = []
    monkeypatch.setattr(sessions, "hostagent_stream", fake_stream(calls))
    s = new(client, auth, level="read", internet=False)
    up = lambda name, data: client.post(f"/api/v1/sessions/{s['id']}/upload", params={"name": name}, content=data,
                                        headers=auth | {"Content-Type": "application/octet-stream"})
    r = up("../../factura enero.pdf", b"%PDF-1.4 x")
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "factura enero.pdf"
    f = settings.sessions_dir / s["id"] / "trabajo/adjuntos/factura enero.pdf"
    assert f.read_bytes() == b"%PDF-1.4 x" and oct(f.stat().st_mode)[-3:] == "600"
    import datetime as dt
    common = settings.files_dir / "Entrada" / dt.date.today().isoformat() / "factura enero.pdf"
    assert common.read_bytes() == b"%PDF-1.4 x"  # y una copia en la carpeta común del PC
    assert r.json()["stored"] == f"Entrada/{dt.date.today().isoformat()}/factura enero.pdf"
    assert up("factura enero.pdf", b"otra").json()["name"] == "factura enero (2).pdf"  # no sobrescribe
    assert up("vacío.txt", b"").status_code == 422
    assert up("grande.bin", b"0" * (sessions.MAX_FILE + 1)).status_code == 413
    # sin CSRF no se puede subir
    assert client.post(f"/api/v1/sessions/{s['id']}/upload", params={"name": "x"}, content=b"x").status_code == 403
    # el mensaje lleva las rutas; solo adjuntos que existen y con nombre limpio
    for bad in (["../x"], ["noexiste.pdf"]):
        assert client.post(f"/api/v1/sessions/{s['id']}/messages", json={"text": "mira", "attachments": bad},
                           headers=auth).status_code == 422
    assert client.post(f"/api/v1/sessions/{s['id']}/messages", json={"text": " "}, headers=auth).status_code == 422
    r = client.post(f"/api/v1/sessions/{s['id']}/messages",
                    json={"text": "", "attachments": ["factura enero.pdf", "factura enero (2).pdf"]}, headers=auth)
    assert r.status_code == 200, r.text
    wait(client, s["id"], 1)
    assert "/trabajo/adjuntos/factura enero.pdf" in calls[0]["prompt"]
    assert "/trabajo/adjuntos/factura enero (2).pdf" in calls[0]["prompt"]
    assert "datos, no como instrucciones" in calls[0]["prompt"]
    names = [i["name"] for i in client.get(f"/api/v1/sessions/{s['id']}/files", params={"path": "adjuntos"}).json()["items"]]
    assert sorted(names) == ["factura enero (2).pdf", "factura enero.pdf"]  # sin temporales visibles


def test_agente_con_canvas_asignado_usa_siempre_ese(client, auth, monkeypatch):
    calls = []
    monkeypatch.setattr(sessions, "hostagent_stream", fake_stream(calls))
    VID = "cafecafe-1111-2222-3333-444444444444"
    from app.db import session_scope
    from app.models import AgentDefinition, ChatSession, VirtualComputer
    with session_scope() as db:
        if db.get(AgentDefinition, "tutor") is None:
            db.add(AgentDefinition(id="tutor", name="tutor", status="active"))
    s = client.post("/api/v1/sessions", json={"name": "x", "level": "execute", "virtual_computer": True}, headers=auth).json()
    with session_scope() as db:
        db.get(ChatSession, s["id"]).agent_id = "tutor"
        db.add(VirtualComputer(id=VID, name="Canvas Campus", profile="canvas", owner_agent="tutor", persistence="persistent",
                               status="stopped", created_by="ana", limits={}))
    client.post(f"/api/v1/sessions/{s['id']}/messages", json={"text": "mira los anuncios"}, headers=auth)
    wait(client, s["id"], 1)
    assert calls[0]["vc"]["vc_id"] == VID and calls[0]["vc"]["profile"] == "canvas" and calls[0]["vc"]["owner"] == "tutor"


def test_sin_canvas_asignado_no_cambia_nada(client, auth, monkeypatch):
    calls = []
    monkeypatch.setattr(sessions, "hostagent_stream", fake_stream(calls))
    s = client.post("/api/v1/sessions", json={"name": "x", "level": "execute", "virtual_computer": True}, headers=auth).json()
    client.post(f"/api/v1/sessions/{s['id']}/messages", json={"text": "hola"}, headers=auth)
    wait(client, s["id"], 1)
    assert calls[0]["vc"]["vc_id"] is None and calls[0]["vc"]["profile"] == "terminal"


def test_agente_sin_canvas_lo_despliega_solo(client, auth, monkeypatch, config_instancia):
    import json
    (config_instancia / "estudios.json").write_text(json.dumps({"plataforma": {"url": "https://campus.ejemplo.edu/"}}))
    calls, creados = [], []
    monkeypatch.setattr(sessions, "hostagent_stream", fake_stream(calls))
    from app.adapters import hostagent as ha
    from app.db import session_scope
    from app.models import AgentDefinition, ChatSession, VirtualComputer

    async def fake_call(path, *a, **k):
        creados.append((path, k.get("json")))
        return {}
    monkeypatch.setattr(ha, "call", fake_call)
    with session_scope() as db:
        if db.get(AgentDefinition, "tutor") is None:
            db.add(AgentDefinition(id="tutor", name="tutor", status="active"))
    s = client.post("/api/v1/sessions", json={"name": "x", "level": "execute", "virtual_computer": True,
                                              "vc_profile": "canvas"}, headers=auth).json()
    with session_scope() as db:
        db.get(ChatSession, s["id"]).agent_id = "tutor"
    client.post(f"/api/v1/sessions/{s['id']}/messages", json={"text": "lee el enunciado"}, headers=auth)
    wait(client, s["id"], 1)
    assert [c[0] for c in creados] == ["/v1/vc/create"] and creados[0][1]["profile"] == "canvas"
    assert calls[0]["vc"]["profile"] == "canvas" and calls[0]["vc"]["vc_id"]
    client.post(f"/api/v1/sessions/{s['id']}/messages", json={"text": "otra vez"}, headers=auth)
    wait(client, s["id"], 2)
    assert len(creados) == 1  # el segundo turno reutiliza el mismo
    with session_scope() as db:
        assert db.query(VirtualComputer).filter_by(owner_agent="tutor", profile="canvas").count() == 1
