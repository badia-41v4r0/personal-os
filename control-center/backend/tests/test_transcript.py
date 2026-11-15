import json

from app.adapters import transcript

TG = ('<channel source="plugin:telegram:telegram" chat_id="1" message_id="307" user="ana" user_id="1" '
      'ts="2026-10-24T17:42:34.000Z">\nhola jarvis\n</channel>')


def line(**kw):
    return json.dumps(kw)


LINES = [
    line(type="user", uuid="u1", timestamp="t1", message={"role": "user", "content": TG}),
    line(type="assistant", uuid="a1", timestamp="t2", message={"role": "assistant", "content": [
        {"type": "thinking", "thinking": "SECRETO INTERNO"},
        {"type": "tool_use", "id": "x1", "name": "Read", "input": {"file_path": "/vault/Jarvis/Tareas.md"}},
    ]}),
    line(type="user", uuid="u2", timestamp="t3", message={"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "x1", "content": "contenido"}]}),
    line(type="assistant", uuid="a2", timestamp="t4", message={"role": "assistant", "content": [
        {"type": "tool_use", "id": "x2", "name": "mcp__plugin_telegram_telegram__reply",
         "input": {"chat_id": "1", "text": "¡Hola!"}}]}),
    line(type="user", uuid="u3", timestamp="t5", message={"role": "user", "content": "🎙️ [voz-pc id=9] qué tengo hoy"}),
    line(type="user", uuid="u4", timestamp="t6", message={"role": "user", "content": "Haz el briefing"}),
    line(type="user", uuid="u5", timestamp="t7", isMeta=True, message={"role": "user", "content": "meta"}),
    line(type="assistant", uuid="s1", timestamp="t8", isSidechain=True,
         message={"role": "assistant", "content": [{"type": "text", "text": "subagente"}]}),
    line(type="system", uuid="y1"),
    "esto no es json",
]


def test_parse(tmp_path):
    p = tmp_path / "abc.jsonl"
    p.write_text("\n".join(LINES) + "\n")
    items = transcript.read(p)["items"]
    msgs = [(i["kind"], i["channel"], i["text"]) for i in items if i["kind"] == "message"]
    assert msgs == [("message", "telegram", "hola jarvis"), ("message", "telegram", "¡Hola!"),
                    ("message", "voz", "🎙️ [voz-pc id=9] qué tengo hoy"), ("message", "sistema", "Haz el briefing")]
    # El razonamiento no se expone, solo se marca
    assert not any("SECRETO" in json.dumps(i) for i in items)
    assert any(i["kind"] == "thinking" for i in items)
    assert any(i["kind"] == "tool_call" and i["tool"] == "Read" for i in items)
    assert items[0]["meta"]["message_id"] == "307"


def test_lectura_incremental_ignora_linea_a_medias(tmp_path):
    p = tmp_path / "abc.jsonl"
    p.write_text(LINES[0] + "\n" + LINES[4][:20])
    r = transcript.read(p)
    assert len(r["items"]) == 1
    with p.open("a") as f:
        f.write(LINES[4][20:] + "\n")
    r2 = transcript.read(p, r["next_offset"])
    assert [i["channel"] for i in r2["items"]] == ["voz"]


def test_api_rechaza_ids_arbitrarios(client, auth, settings):
    (settings.data_dir / "runtime").write_text("tmux")  # la transcripción es la de la sesión de tmux
    (settings.jarvis_projects / "abc.jsonl").write_text(LINES[0] + "\n")
    assert client.get("/api/v1/sessions/main/messages").json()["claude_session_id"] == "abc"
    for bad in ("../../etc/passwd", "abc/../x", "nohay"):
        assert client.get("/api/v1/sessions/main/messages", params={"claude_session_id": bad}).status_code == 404
