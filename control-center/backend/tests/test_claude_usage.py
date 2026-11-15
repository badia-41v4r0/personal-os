import time

from app import claude_usage, sessions
from app.adapters import hostagent

EV = {"type": "rate_limit_event", "rate_limit_info": {"status": "allowed", "unifiedWindows": {
    "five_hour": {"utilization": 0.63, "resetsAt": 1793486400}, "seven_day": {"utilization": 0.68, "resetsAt": 1793772000}}}}


def test_parse():
    d = claude_usage.parse_event(EV)
    assert d["five_hour"]["utilization"] == 0.63 and d["seven_day"]["resets_at"] == 1793772000
    assert claude_usage.parse_event({"type": "rate_limit_event", "rate_limit_info": {}}) is None


def test_sin_datos_y_actualizar(client, auth, monkeypatch):
    assert client.get("/api/v1/claude/usage").json() == {"available": False}

    async def call(path, params=None, method="GET", json=None, timeout=15):
        assert path == "/v1/claude/usage" and method == "POST"
        return {"five_hour": {"utilization": 0.4, "resets_at": 1793486400}, "seven_day": {"utilization": 0.2, "resets_at": 1793772000}, "cached": False}

    monkeypatch.setattr(hostagent, "call", call)
    r = client.post("/api/v1/claude/usage/refresh", headers=auth).json()
    assert r["available"] and r["five_hour"]["utilization"] == 0.4 and r["source"] == "probe"
    assert r["seven_day"]["resets_at"].startswith("2026-")
    assert client.get("/api/v1/claude/usage").json()["seven_day"]["utilization"] == 0.2
    assert client.post("/api/v1/claude/usage/refresh", headers={"Origin": auth["Origin"]}).status_code == 403


def test_gratis_desde_las_conversaciones(client, auth, monkeypatch):
    async def gen(payload):
        yield {"type": "system", "subtype": "init", "session_id": "11111111-2222-3333-4444-555555555555"}
        yield EV
        yield {"type": "result", "result": "ok"}
        yield {"type": "_exit", "code": 0}

    monkeypatch.setattr(sessions, "hostagent_stream", gen)
    s = client.post("/api/v1/sessions", json={"name": "x"}, headers=auth).json()
    client.post(f"/api/v1/sessions/{s['id']}/messages", json={"text": "hola"}, headers=auth)
    end = time.time() + 5
    while time.time() < end and not client.get("/api/v1/claude/usage").json().get("available"):
        time.sleep(0.05)
    u = client.get("/api/v1/claude/usage").json()
    assert u["source"] == "session" and u["five_hour"]["utilization"] == 0.63
