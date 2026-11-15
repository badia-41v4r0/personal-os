"""Puerta del MCP `pos`: lo único que un agente puede tocar del Core.

Cada ejecución recibe una credencial que dura lo que su turno y solo abre sus herramientas. Las lecturas pasan por
TOOLS; las escrituras, siempre por core/actions. El contenedor no ve la base de datos ni los secretos.
"""
import hashlib
import secrets
from datetime import timedelta
from typing import Callable

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..db import session_scope, utcnow
from ..models import RunToken
from . import modules
from . import actions, memory

router = APIRouter(prefix="/api/v1/internal/pos")
TURN_TTL = timedelta(hours=3)
ToolFn = Callable[[dict, Session], dict | list]
TOOLS: dict[str, ToolFn] = {}
# Leer esto trae contenido de terceros: desde ese momento la ejecución queda marcada y sus acciones de nivel 2 piden aprobación
EXTERNAL_TOOLS: set[str] = set()


def tool(name: str):
    def deco(fn: ToolFn) -> ToolFn:
        TOOLS[name] = fn
        return fn
    return deco


@tool("memory.search")
def _search(args: dict, db: Session):
    return memory.search(db, str(args.get("q", "")), 10)


@tool("memory.facts")
def _facts(args: dict, db: Session):
    return memory.current_facts(db, args.get("subject"))


@tool("memory.context")
def _context(args: dict, db: Session):
    return memory.context_pack(db, str(args.get("q", "")))


@tool("finance.summary")
def _finance_summary(args: dict, db: Session):
    from datetime import date

    from ..modules import finance
    return {"mes": finance.month_summary(db, str(args.get("mes") or date.today().strftime("%Y-%m"))), "patrimonio": finance.net_worth(db)}


@tool("finance.entries")
def _finance_entries(args: dict, db: Session):
    from sqlalchemy import select

    from ..models import JournalEntry
    from ..modules import finance
    q = select(JournalEntry).order_by(JournalEntry.entry_date.desc()).limit(min(int(args.get("limit") or 50), 200))
    if args.get("estado"):
        q = q.where(JournalEntry.status == str(args["estado"]))
    return [finance._entry(db, e) for e in db.scalars(q)]


@tool("finance.overview")
def _finance_overview(args: dict, db: Session):
    from datetime import date

    from ..modules import finance
    return finance.year_overview(db, str(args.get("año") or date.today().year))


@tool("finance.budgets")
def _finance_budgets(args: dict, db: Session):
    from datetime import date

    from ..modules import finance
    return finance.budget_plan(db, date.today().strftime("%Y-%m"))


@tool("finance.accounts")
def _finance_accounts(args: dict, db: Session):
    from ..modules import finance
    return finance._accounts_view(db)


@tool("finance.rules")
def _finance_rules(args: dict, db: Session):
    from ..modules import finance
    return finance.rules_list(db)


@tool("finance.savings")
def _finance_savings(args: dict, db: Session):
    from ..modules import finance
    return finance.savings_view(db)


def issue_token(run_id: str, agent: str, tools: list[str], capabilities: list[str], tainted: bool = False) -> str:
    raw = secrets.token_urlsafe(32)
    with session_scope() as db:
        db.execute(delete(RunToken).where(RunToken.expires_at < utcnow()))
        db.add(RunToken(token_hash=hashlib.sha256(raw.encode()).hexdigest(), run_id=run_id, agent=agent, tools=tools,
                        capabilities=capabilities, tainted=tainted, expires_at=utcnow() + TURN_TTL))
    return raw


def revoke_run(run_id: str) -> None:
    with session_scope() as db:
        db.execute(delete(RunToken).where(RunToken.run_id == run_id))


class CallIn(BaseModel):
    kind: str = Field(pattern="^(read|action)$")
    name: str = Field(max_length=80)
    args: dict = Field(default_factory=dict)
    reason: str = Field(default="", max_length=1000)
    idempotency_key: str | None = Field(default=None, max_length=120)


def _run_of(x_run_token: str = Header(default="")) -> dict:
    with session_scope() as db:
        r = db.get(RunToken, hashlib.sha256(x_run_token.encode()).hexdigest())
        if r is None or r.expires_at < utcnow():
            raise HTTPException(401, "Ejecución no válida")
        return {"hash": r.token_hash, "run_id": r.run_id, "agent": r.agent, "tools": list(r.tools), "capabilities": list(r.capabilities), "tainted": r.tainted}


@router.get("/tools")
def list_tools(run: dict = Depends(_run_of)):
    act = modules.activos()
    return {"result": {"lecturas": modules.filtrar(run["tools"], act), "capacidades": modules.filtrar(run["capabilities"], act)}}


@router.post("/call")
def call(body: CallIn, run: dict = Depends(_run_of)):
    if not modules.permitido(body.name):
        if body.kind == "read":
            raise HTTPException(403, "Ese módulo está desactivado")
        return {"result": {"status": "denied", "reason": "Ese módulo está desactivado"}}
    if body.kind == "read":
        if body.name not in run["tools"] or body.name not in TOOLS:
            raise HTTPException(403, "Herramienta no permitida para este agente")
        with session_scope() as db:
            if body.name in EXTERNAL_TOOLS:
                db.get(RunToken, run["hash"]).tainted = True
            try:
                return {"result": TOOLS[body.name](body.args, db)}
            except (ValueError, KeyError, RuntimeError, OSError) as e:
                return {"error": str(e)[:300]}
    if body.name not in run["capabilities"]:
        return {"result": {"status": "denied", "reason": "Capacidad no permitida para este agente"}}
    return {"result": actions.request(body.name, body.args, actor=run["agent"], actor_type="agent", run_id=run["run_id"],
                                      reason=body.reason, idempotency_key=body.idempotency_key, tainted=run["tainted"])}
