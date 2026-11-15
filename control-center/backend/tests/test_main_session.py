import asyncio
import json
import time

import pytest

from app import main_session
from app.adapters import hostagent


class FakeJarvis:
    """Simula la sesión tmux: cada prompt aparece en el JSONL y su turno termina al cabo de un rato."""

    def __init__(self, path, turn_s=0.3):
        self.path, self.turn_s = path, turn_s
        self.sent, self.in_flight, self.max_in_flight = [], 0, 0
        path.write_text("")

    def _w(self, **d):
        with self.path.open("a") as f:
            f.write(json.dumps(d) + "\n")

    async def call(self, path, params=None, method="GET", json=None, timeout=15):
        if path == "/v1/jarvis/prompt":
            self.sent.append(json["run_id"])
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            self._w(type="user", uuid=f"u{len(self.sent)}", timestamp="t",
                    message={"role": "user", "content": f"💻 [panel id={json['run_id']}] {json['text']}"})
            asyncio.get_running_loop().call_later(self.turn_s, self._finish, json["run_id"])
            return {"ok": True}
        if path == "/v1/jarvis/interrupt":
            return {"ok": True}
        if path == "/v1/jarvis/status":
            return {"tmux": True}
        raise AssertionError(path)

    def _finish(self, run_id):
        self._w(type="assistant", uuid="a" + run_id[:6], timestamp="t", message={"role": "assistant", "content": [
            {"type": "tool_use", "id": "x", "name": "Read", "input": {"file_path": "/vault/x.md"}},
            {"type": "text", "text": f"respuesta a {run_id[:6]}"}]})
        self._w(type="system", subtype="turn_duration", durationMs=10, uuid="d" + run_id[:6])
        self.in_flight -= 1


@pytest.fixture()
def fake(settings, monkeypatch):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "runtime").write_text("tmux")  # estas pruebas son del camino antiguo (sesión de tmux)
    main_session.POLL = 0.05
    f = FakeJarvis(settings.jarvis_projects / "s1.jsonl")
    monkeypatch.setattr(hostagent, "call", f.call)
    return f


def wait_runs(client, n, timeout=8):
    end = time.time() + timeout
    while time.time() < end:
        runs = client.get("/api/v1/agents/runs?session_id=main").json()
        if len(runs) >= n and all(r["status"] in ("done", "error", "interrupted") for r in runs):
            return runs
        time.sleep(0.05)
    raise AssertionError(client.get("/api/v1/agents/runs").json())


def test_cola_serializada(client, auth, fake):
    ids = [client.post("/api/v1/sessions/main/messages", json={"text": f"hola {i}"}, headers=auth).json()["run_id"]
           for i in range(3)]
    runs = wait_runs(client, 3)
    assert fake.sent == ids  # en orden
    assert fake.max_in_flight == 1  # nunca dos a la vez
    by_id = {r["id"]: r for r in runs}
    for i in ids:
        assert by_id[i]["status"] == "done"
        assert by_id[i]["tools_used"] == ["Read"]
        assert f"respuesta a {i[:6]}" in by_id[i]["result"]


def test_mensaje_aparece_como_canal_web(client, auth, fake):
    rid = client.post("/api/v1/sessions/main/messages", json={"text": "qué tal"}, headers=auth).json()["run_id"]
    wait_runs(client, 1)
    items = client.get("/api/v1/sessions/main/messages").json()["items"]
    web = [i for i in items if i["channel"] == "web"]
    assert web[0]["text"] == "qué tal" and web[0]["meta"]["run_id"] == rid


def test_envio_requiere_csrf(client, auth, fake):
    r = client.post("/api/v1/sessions/main/messages", json={"text": "x"}, headers={"Origin": auth["Origin"]})
    assert r.status_code == 403


def test_texto_vacio_o_largo(client, auth, fake):
    assert client.post("/api/v1/sessions/main/messages", json={"text": ""}, headers=auth).status_code == 422
    assert client.post("/api/v1/sessions/main/messages", json={"text": "x" * 4001}, headers=auth).status_code == 422


def test_fallo_del_host_agent_no_bloquea_la_cola(client, auth, fake, monkeypatch):
    calls = {"n": 0}
    orig = fake.call

    async def flaky(path, **kw):
        if path == "/v1/jarvis/prompt" and calls["n"] == 0:
            calls["n"] += 1
            raise hostagent.HostAgentError(503, "La sesión de Jarvis no está en marcha")
        return await orig(path, **kw)

    monkeypatch.setattr(hostagent, "call", flaky)
    client.post("/api/v1/sessions/main/messages", json={"text": "uno"}, headers=auth)
    client.post("/api/v1/sessions/main/messages", json={"text": "dos"}, headers=auth)
    runs = sorted(wait_runs(client, 2), key=lambda r: r["created_at"])
    assert [r["status"] for r in runs] == ["error", "done"]
    assert "no está en marcha" in runs[0]["error"]


def test_interrumpir_cancela_las_pendientes(client, auth, fake):
    fake.turn_s = 1.0
    client.post("/api/v1/sessions/main/messages", json={"text": "largo"}, headers=auth)
    client.post("/api/v1/sessions/main/messages", json={"text": "espera"}, headers=auth)
    time.sleep(0.3)
    r = client.post("/api/v1/sessions/main/interrupt", headers=auth).json()
    assert r["interrupted"] and len(r["cancelled"]) == 1
    runs = wait_runs(client, 2)
    assert {x["status"] for x in runs} == {"interrupted"}
    assert len(fake.sent) == 1  # la segunda nunca llegó a enviarse


def test_adjuntos_para_jarvis(client, auth, fake, settings):
    import datetime as dt
    hoy = dt.date.today().isoformat()
    up = lambda name, data: client.post("/api/v1/sessions/main/upload", params={"name": name}, content=data,
                                        headers=auth | {"Content-Type": "application/octet-stream"})
    r = up("../ticket.jpg", b"\xff\xd8jpg")
    assert r.status_code == 200, r.text
    assert r.json()["path"] == f"Entrada/{hoy}/ticket.jpg"
    assert (settings.files_dir / "Entrada" / hoy / "ticket.jpg").read_bytes() == b"\xff\xd8jpg"
    assert up("ticket.jpg", b"b").json()["name"] == "ticket (2).jpg"
    assert client.post("/api/v1/sessions/main/upload", params={"name": "x"}, content=b"x").status_code == 403
    for bad in (["../../.env"], ["Entrada/../x"], [f"Entrada/{hoy}/no.jpg"], ["Otra/x.jpg"]):
        assert client.post("/api/v1/sessions/main/messages", json={"text": "x", "attachments": bad},
                           headers=auth).status_code == 422, bad
    rid = client.post("/api/v1/sessions/main/messages", json={"text": "", "attachments": [r.json()["path"]]},
                      headers=auth).json()["run_id"]
    wait_runs(client, 1)
    sent = client.get("/api/v1/sessions/main/messages").json()["items"]
    texto = next(i["text"] for i in sent if i["meta"].get("run_id") == rid)
    assert f"/archivos/Entrada/{hoy}/ticket.jpg" in texto and "datos, no instrucciones" in texto
