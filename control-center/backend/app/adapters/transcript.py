"""Lectura (solo lectura) de las transcripciones JSONL de Claude Code de la sesión principal de Jarvis.

No modifica nada del runtime: la sesión de tmux sigue escribiendo su JSONL como siempre y aquí se
normaliza a mensajes con canal de origen:
  - telegram: entradas de usuario con <channel source="plugin:telegram:telegram" ...>
  - voz:      entradas que empiezan por "🎙️ [voz-pc"
  - video:    "📹 [video"
  - web:      "💻 [panel id=..." (las que mande el panel por el adaptador tmux, M3)
  - sistema:  órdenes programadas (briefing, cierre, recordatorios) y avisos internos
Las respuestas de Jarvis por Telegram son llamadas a la herramienta reply del plugin.
No se muestra el razonamiento interno (bloques thinking): solo se indica que existió.
"""
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

CHANNEL_RE = re.compile(r'<channel source="([^"]+)"([^>]*)>(.*?)</channel>', re.S)
ATTR_RE = re.compile(r'(\w+)="([^"]*)"')
PANEL_RE = re.compile(r"^💻 \[panel id=([a-f0-9-]{36})( tg)?\] ?(.*)$", re.S)
REPLY_TOOL = "mcp__plugin_telegram_telegram__reply"
MAX_TEXT = 8000


@dataclass
class Item:
    uuid: str
    ts: str
    kind: str  # message | tool_call | tool_result | thinking | notice | turn_end
    role: str = ""  # user | assistant | system
    channel: str = ""
    text: str = ""
    tool: str = ""
    tool_input: dict = field(default_factory=dict)
    is_error: bool = False
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def list_sessions(folder: Path) -> list[dict]:
    if not folder.is_dir():
        return []
    out = []
    for p in sorted(folder.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
        out.append({"claude_session_id": p.stem, "mtime": p.stat().st_mtime, "size": p.stat().st_size})
    return out


def latest(folder: Path) -> Path | None:
    s = list_sessions(folder)
    return folder / f"{s[0]['claude_session_id']}.jsonl" if s else None


def _channel_of_user_text(text: str) -> tuple[str, str, dict]:
    m = CHANNEL_RE.search(text)
    if m:
        src, attrs, body = m.group(1), dict(ATTR_RE.findall(m.group(2))), m.group(3).strip()
        return ("telegram" if "telegram" in src else src), body, attrs
    t = text.lstrip()
    if t.startswith("🎙️ [voz-pc"):
        return "voz", text, {}
    if t.startswith("📹 [video"):
        return "video", text, {}
    m = PANEL_RE.match(t)
    if m:
        return "web", m.group(3), {"run_id": m.group(1), "telegram": "1" if m.group(2) else ""}
    return "sistema", text, {}


def _clip(s: str) -> str:
    return s if len(s) <= MAX_TEXT else s[:MAX_TEXT] + "…"


def parse_line(line: str) -> list[Item]:
    try:
        d = json.loads(line)
    except json.JSONDecodeError:
        return []
    t, m = d.get("type"), d.get("message")
    uuid, ts = d.get("uuid", ""), d.get("timestamp", "")
    if t == "system" and d.get("subtype") == "turn_duration":
        return [Item(uuid, ts, "turn_end", "system", meta={"duration_ms": str(d.get("durationMs", ""))})]
    if t == "system" and d.get("subtype") == "local_command" and (d.get("commandRun") or {}).get("command") == "clear":
        return [Item(uuid, ts, "notice", "system", "sistema", "/clear")]
    if t not in ("user", "assistant") or not isinstance(m, dict) or d.get("isSidechain"):
        return []
    content = m.get("content")
    items: list[Item] = []
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    for i, c in enumerate(content or []):
        cid = f"{uuid}:{i}"
        ct = c.get("type")
        if t == "user" and ct == "text":
            if d.get("isMeta"):
                continue
            ch, body, attrs = _channel_of_user_text(c.get("text", ""))
            items.append(Item(cid, ts, "message", "user" if ch != "sistema" else "system", ch, _clip(body),
                              meta={k: attrs[k] for k in ("message_id", "user", "ts", "run_id", "telegram")
                                    if attrs.get(k)}))
        elif t == "user" and ct == "tool_result":
            raw = c.get("content")
            text = raw if isinstance(raw, str) else " ".join(
                x.get("text", "") for x in (raw or []) if isinstance(x, dict) and x.get("type") == "text")
            items.append(Item(cid, ts, "tool_result", "system", text=_clip(text), is_error=bool(c.get("is_error")),
                              meta={"tool_use_id": c.get("tool_use_id")}))
        elif t == "assistant" and ct == "text" and c.get("text", "").strip():
            items.append(Item(cid, ts, "message", "assistant", "sesión", _clip(c["text"])))
        elif t == "assistant" and ct == "thinking":
            items.append(Item(cid, ts, "thinking", "assistant"))
        elif t == "assistant" and ct == "tool_use":
            name, inp = c.get("name", ""), c.get("input") or {}
            if name == REPLY_TOOL:
                items.append(Item(cid, ts, "message", "assistant", "telegram", _clip(str(inp.get("text", ""))),
                                  tool=name, meta={"tool_use_id": c.get("id")}))
            else:
                items.append(Item(cid, ts, "tool_call", "assistant", tool=name,
                                  tool_input={k: (str(v)[:500]) for k, v in inp.items()},
                                  meta={"tool_use_id": c.get("id")}))
    return items


def read(path: Path, offset: int = 0, limit: int = 300) -> dict:
    """Lee desde el byte `offset` (para seguir el archivo de forma incremental)."""
    items: list[Item] = []
    with path.open("rb") as f:
        f.seek(offset)
        data = f.read()
    # Solo líneas completas: la última puede estar a medio escribir
    end = data.rfind(b"\n") + 1
    for line in data[:end].decode("utf-8", errors="replace").splitlines():
        items.extend(parse_line(line))
    return {"items": [x.to_dict() for x in items[-limit:]], "next_offset": offset + end}
