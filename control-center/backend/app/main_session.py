"""Session Manager de la sesión principal (la de Telegram, en tmux).

- Seguidor: lee el JSONL más reciente cada segundo y publica `chat.updated` (solo offset e id de sesión;
  el contenido se pide a /sessions/main/messages, así SQLite no copia la conversación).
- Cola: los mensajes del panel se envían de uno en uno. El siguiente no sale hasta que el JSONL muestra el
  fin del turno del anterior (`turn_duration`). Entre procesos (voz, timers, panel) manda además el cerrojo
  común de teclado que aplica el Host Agent.
- Cada mensaje es una ejecución (AgentRun) con id, estado, herramientas usadas y resultado.
"""
import asyncio
import uuid as uuidlib
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from . import events
from .adapters import hostagent, transcript
from .config import get_settings
from .db import session_scope, utcnow
from .models import AgentRun, ChatSession, Message

MAIN_ID = "main"
TURN_TIMEOUT = timedelta(minutes=20)
POLL = 1.0

_queue: asyncio.Queue[str]  # se crea en start(), dentro del bucle de eventos de la app
_tasks: list[asyncio.Task] = []
_current: dict[str, str | None] = {"run": None}


def ensure_main_session() -> None:
    with session_scope() as db:
        if db.get(ChatSession, MAIN_ID) is None:
            db.add(ChatSession(id=MAIN_ID, kind="main", name="Jarvis (compartida con Telegram)",
                               description="Sesión principal en tmux; la misma que usa Telegram, la voz y los timers.",
                               agent_id=None, workdir="/workspace", model="sonnet"))
        # Recuperación: lo que quedó a medias al pararse el backend no se reenvía (podría duplicarse)
        for r in db.scalars(select(AgentRun).where(AgentRun.session_id == MAIN_ID,
                                                   AgentRun.status.in_(("queued", "running")))):
            r.status, r.ended_at = "error", utcnow()
            r.error = "El backend se reinició con la ejecución pendiente; no se reenvía para no duplicarla."


def submit(text: str, telegram: bool, actor: str) -> dict:
    run_id = str(uuidlib.uuid4())
    with session_scope() as db:
        db.add(AgentRun(id=run_id, session_id=MAIN_ID, agent_id="jarvis", channel="web", status="queued",
                        usage={"telegram": telegram}))
        db.add(Message(session_id=MAIN_ID, role="user", channel="web", content=text, run_id=run_id))
        events.audit(db, actor, "chat.main.send", target=run_id, chars=len(text), telegram=telegram)
        events.publish("run.queued", {"run_id": run_id, "session_id": MAIN_ID, "position": _queue.qsize() + 1}, db=db)
    _queue.put_nowait(run_id)
    return {"run_id": run_id, "status": "queued", "position": _queue.qsize()}


def _set(run_id: str, **fields) -> None:
    with session_scope() as db:
        r = db.get(AgentRun, run_id)
        for k, v in fields.items():
            setattr(r, k, v)


async def interrupt(actor: str) -> dict:
    run_id = _current["run"]
    with session_scope() as db:
        # Las que aún esperan en la cola se cancelan sin llegar a enviarse
        queued = list(db.scalars(select(AgentRun).where(AgentRun.session_id == MAIN_ID, AgentRun.status == "queued")))
        for r in queued:
            r.status, r.ended_at, r.error = "interrupted", utcnow(), "Cancelada antes de enviarse"
        events.audit(db, actor, "chat.main.interrupt", target=run_id or "")
    await hostagent.call("/v1/jarvis/interrupt", method="POST")
    if run_id:
        _set(run_id, status="interrupted", ended_at=utcnow(), error="Interrumpida desde el panel")
        events.publish("run.interrupted", {"run_id": run_id, "session_id": MAIN_ID})
    return {"interrupted": run_id, "cancelled": [r.id for r in queued]}


async def _wait_turn(run_id: str, path: Path, offset: int) -> None:
    """Sigue el JSONL desde `offset` hasta ver nuestro mensaje y después el fin de su turno."""
    folder = get_settings().jarvis_projects
    seen_prompt, tools, replies = False, [], []
    deadline = utcnow() + TURN_TIMEOUT
    while utcnow() < deadline:
        with session_scope() as db:
            if db.get(AgentRun, run_id).status == "interrupted":
                return
        latest = transcript.latest(folder)
        if latest is not None and latest != path:  # /clear u otra sesión: seguir en el archivo nuevo
            path, offset = latest, 0
        data = transcript.read(path, offset, limit=10_000)
        offset = data["next_offset"]
        for it in data["items"]:
            if not seen_prompt:
                seen_prompt = it["kind"] == "message" and it["meta"].get("run_id") == run_id
                continue
            if it["kind"] == "tool_call":
                tools.append(it["tool"])
            elif it["kind"] == "message" and it["role"] == "assistant":
                replies.append(it["text"])
            elif it["kind"] == "turn_end":
                _set(run_id, status="done", ended_at=utcnow(), tools_used=tools, result="\n\n".join(replies)[-8000:])
                events.publish("run.finished", {"run_id": run_id, "session_id": MAIN_ID, "status": "done",
                                                "tools": len(tools)})
                return
        await asyncio.sleep(POLL)
    _set(run_id, status="error", ended_at=utcnow(), tools_used=tools, error="Sin fin de turno en 20 min")
    events.publish("run.finished", {"run_id": run_id, "session_id": MAIN_ID, "status": "error"})


async def _worker() -> None:
    folder = get_settings().jarvis_projects
    while True:
        run_id = await _queue.get()
        with session_scope() as db:
            run = db.get(AgentRun, run_id)
            if run is None or run.status != "queued":
                continue
            text = db.scalar(select(Message.content).where(Message.run_id == run_id))
            telegram = bool((run.usage or {}).get("telegram"))
        _current["run"] = run_id
        try:
            path = transcript.latest(folder)
            offset = path.stat().st_size if path else 0
            _set(run_id, status="running", started_at=utcnow())
            events.publish("run.started", {"run_id": run_id, "session_id": MAIN_ID})
            await hostagent.call("/v1/jarvis/prompt", method="POST", timeout=180,
                                 json={"run_id": run_id, "text": text, "telegram": telegram})
            if path is None:
                path = transcript.latest(folder)
            await _wait_turn(run_id, path, offset)
        except Exception as e:  # noqa: BLE001 — se registra y se sigue con la cola
            detail = getattr(e, "detail", None) or str(e) or e.__class__.__name__
            _set(run_id, status="error", ended_at=utcnow(), error=str(detail)[:500])
            events.publish("run.finished", {"run_id": run_id, "session_id": MAIN_ID, "status": "error",
                                            "error": str(detail)[:200]})
        finally:
            _current["run"] = None


async def _follower() -> None:
    folder = get_settings().jarvis_projects
    state: tuple[str, int] | None = None
    while True:
        try:
            p = transcript.latest(folder)
            if p is not None:
                cur = (p.stem, p.stat().st_size)
                if cur != state:
                    if state is not None:
                        events.publish("chat.updated", {"session_id": MAIN_ID, "claude_session_id": cur[0],
                                                        "size": cur[1]}, source="transcript")
                    state = cur
        except OSError:
            pass
        await asyncio.sleep(POLL)


def start() -> None:
    global _queue
    _queue = asyncio.Queue()
    ensure_main_session()
    _tasks.extend([asyncio.create_task(_worker()), asyncio.create_task(_follower())])


async def stop() -> None:
    for t in _tasks:
        t.cancel()
    _tasks.clear()


def queue_state() -> dict:
    return {"current_run": _current["run"], "queued": _queue.qsize()}
