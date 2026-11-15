"""Memoria común, independiente del modelo: cambiar de proveedor no pierde nada.

- Perfil y estado actual: hechos con valid_to vacío. Cambiar uno cierra el anterior, no lo borra.
- Episódica: life_events y decisions.
- Conocimiento: la vault manda; aquí solo hay un índice para buscarla.

Un agente nunca confirma: lo que propone nace como `inferred` y lo valida el usuario.
"""
import hashlib
import json
import logging
import re
import urllib.request
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .. import events
from ..config import get_settings
from ..db import get_db, session_scope, utcnow
from ..models import DecisionRecord, Fact, KnowledgeDoc, LifeEvent, Source, Task
from ..security import Principal, current_principal, require_admin
from . import actions

log = logging.getLogger("cc.memory")
router = APIRouter(prefix="/api/v1/core", dependencies=[Depends(current_principal)])

VERIFICATION = ("inferred", "reported", "imported", "confirmed")
CHUNK_CHARS = 1200
EXCLUDE = (".obsidian", ".trash", "sync-conflict", "panel-archivo", "/Sistema/digest", "Jarvis/Panel.md", "/Contabilidad/")
EMBED_URL = "http://127.0.0.1:11434/api/embed"


def source(db: Session, kind: str, uri: str = "", trust: str = "system", external_id: str = "") -> int:
    s = Source(kind=kind, uri=uri[:500], trust=trust, external_id=external_id[:160])
    db.add(s)
    db.flush()
    return s.id


def log_event(db: Session, domain: str, type_: str, title: str = "", payload: dict | None = None,
              occurred_at: datetime | None = None, source_id: int | None = None, corrects_id: int | None = None) -> int:
    e = LifeEvent(domain=domain, type=type_, title=title[:300], payload=payload or {}, occurred_at=occurred_at or utcnow(),
                  source_id=source_id, corrects_id=corrects_id)
    db.add(e)
    db.flush()
    return e.id


def set_fact(db: Session, subject: str, predicate: str, value: dict, verification: str = "reported",
             confidence: float | None = None, source_id: int | None = None, valid_from: datetime | None = None) -> Fact:
    if verification not in VERIFICATION:
        raise ValueError("verificación no válida")
    now = valid_from or utcnow()
    old = db.scalar(select(Fact).where(Fact.subject == subject, Fact.predicate == predicate, Fact.valid_to.is_(None)))
    if old is not None and old.value == value and old.verification == verification:
        return old  # nada nuevo: no ensucia el historial
    new = Fact(subject=subject, predicate=predicate, value=value, verification=verification, confidence=confidence,
               source_id=source_id, valid_from=now)
    db.add(new)
    db.flush()
    if old is not None:
        old.valid_to, old.superseded_by = now, new.id
        log_event(db, "core", "fact.changed", f"{subject}.{predicate}", {"antes": old.value, "ahora": value}, source_id=source_id)
    return new


def _fact(f: Fact) -> dict:
    return {"id": f.id, "subject": f.subject, "predicate": f.predicate, "value": f.value,
            "valid_from": f.valid_from.isoformat() + "Z", "valid_to": f.valid_to.isoformat() + "Z" if f.valid_to else None,
            "verification": f.verification, "confidence": f.confidence}


def current_facts(db: Session, subject: str | None = None) -> list[dict]:
    q = select(Fact).where(Fact.valid_to.is_(None)).order_by(Fact.subject, Fact.predicate)
    if subject:
        q = q.where(Fact.subject == subject)
    return [_fact(f) for f in db.scalars(q)]


def facts_as_of(db: Session, moment: datetime, subject: str | None = None) -> list[dict]:
    """Lo que se creía en ese momento."""
    q = select(Fact).where(Fact.recorded_at <= moment, Fact.valid_from <= moment,
                           (Fact.valid_to.is_(None)) | (Fact.valid_to > moment))
    if subject:
        q = q.where(Fact.subject == subject)
    return [_fact(f) for f in db.scalars(q)]


# ---------- capacidad de los agentes ----------


def _propose(payload: dict, db: Session) -> dict:
    sid = source(db, "agent", payload.get("origen", ""), "system")
    f = set_fact(db, payload["subject"], payload["predicate"], payload["value"], "inferred",
                 payload.get("confidence"), sid)
    return {"fact_id": f.id}


actions.register(actions.Capability("memory.fact.propose", 1, _propose, "Proponer un hecho para que lo valides",
                                    summary=lambda p: f"Propone {p.get('subject')}.{p.get('predicate')}"))


# ---------- índice de la vault ----------


def chunk_markdown(text_: str) -> list[tuple[str, str]]:
    """Trozos por sección, partidos si pasan de CHUNK_CHARS. Sin frontmatter ni líneas de navegación."""
    body = re.sub(r"\A---\n.*?\n---\n", "", text_, flags=re.S)
    body = "\n".join(line for line in body.splitlines() if not line.startswith("🧭"))
    out: list[tuple[str, str]] = []
    heading, buf = "", []

    def flush() -> None:
        content = "\n".join(buf).strip()
        for i in range(0, len(content), CHUNK_CHARS):
            piece = content[i:i + CHUNK_CHARS].strip()
            if piece:
                out.append((heading[:300], piece))

    for line in body.splitlines():
        if re.match(r"^#{1,4} ", line):
            flush()
            heading, buf = line.lstrip("# ").strip(), []
        else:
            buf.append(line)
    flush()
    return out


def embed(texts: list[str]) -> list[list[float]] | None:
    """Embeddings locales con Ollama. Sin modelo devuelve None y la búsqueda sigue por texto."""
    model = get_settings().embed_model
    if not model:
        return None
    req = urllib.request.Request(EMBED_URL, json.dumps({"model": model, "input": texts}).encode(),
                                 {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:  # noqa: S310  (URL fija, local)
            return json.load(r)["embeddings"]
    except (OSError, ValueError, KeyError) as e:
        log.warning("embeddings no disponibles: %s", e)
        return None


def _indexable(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.md") if not any(x in p.as_posix() for x in EXCLUDE)]


def reindex(limit: int = 2000) -> dict:
    """Incremental por hash. Solo PostgreSQL: con SQLite la búsqueda es la de la vault."""
    with session_scope() as db:
        if db.get_bind().dialect.name != "postgresql":
            return {"indexed": 0, "skipped": 0, "motivo": "requiere PostgreSQL"}
    root = get_settings().vault
    indexed = skipped = removed = 0
    files = _indexable(root)
    seen = {p.relative_to(root).as_posix() for p in files}
    with session_scope() as db:
        known = {d.path: d.content_hash for d in db.scalars(select(KnowledgeDoc))}
        for path in set(known) - seen:
            db.delete(db.get(KnowledgeDoc, path))
            removed += 1
    for f in files[:limit]:
        rel = f.relative_to(root).as_posix()
        try:
            raw = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        h = hashlib.sha256(raw.encode()).hexdigest()
        if known.get(rel) == h:
            skipped += 1
            continue
        chunks = chunk_markdown(raw)
        vectors = embed([f"{a}\n{b}" for a, b in chunks]) if chunks else None
        with session_scope() as db:
            doc = db.get(KnowledgeDoc, rel) or KnowledgeDoc(path=rel, content_hash=h)
            doc.content_hash, doc.chunks, doc.indexed_at = h, len(chunks), utcnow()
            db.add(doc)
            db.flush()
            db.execute(text("DELETE FROM knowledge_chunks WHERE path = :p"), {"p": rel})
            for i, (heading, content) in enumerate(chunks):
                db.execute(text("""INSERT INTO knowledge_chunks (path, position, heading, content, embedding)
                                   VALUES (:p, :i, :h, :c, CAST(:e AS vector))"""),
                           {"p": rel, "i": i, "h": heading, "c": content, "e": str(vectors[i]) if vectors else None})
        indexed += 1
    return {"indexed": indexed, "skipped": skipped, "removed": removed}


def search(db: Session, q: str, limit: int = 10) -> list[dict]:
    """Búsqueda híbrida: fusiona texto en español y significado (RRF). Sin embeddings, solo texto."""
    if db.get_bind().dialect.name != "postgresql":
        return []
    vec = embed([q])
    sql = """
    WITH t AS (SELECT id, row_number() OVER (ORDER BY ts_rank(tsv, q) DESC) r FROM knowledge_chunks, websearch_to_tsquery('spanish', :q) q
               WHERE tsv @@ q ORDER BY r LIMIT 50)
    {vector_cte}
    SELECT c.path, c.heading, left(c.content, 400) AS snippet, {score} AS score
    FROM knowledge_chunks c {joins} WHERE {where} ORDER BY score DESC LIMIT :n"""
    if vec:
        sql = sql.format(vector_cte=""", v AS (SELECT id, row_number() OVER (ORDER BY embedding <=> CAST(:e AS vector)) r
                         FROM knowledge_chunks WHERE embedding IS NOT NULL ORDER BY r LIMIT 50)""",
                         score="COALESCE(1.0/(60+t.r),0)+COALESCE(1.0/(60+v.r),0)",
                         joins="LEFT JOIN t ON t.id=c.id LEFT JOIN v ON v.id=c.id", where="t.id IS NOT NULL OR v.id IS NOT NULL")
        params = {"q": q, "e": str(vec[0]), "n": limit}
    else:
        sql = sql.format(vector_cte="", score="1.0/(60+t.r)", joins="JOIN t ON t.id=c.id", where="TRUE")
        params = {"q": q, "n": limit}
    return [dict(r._mapping) for r in db.execute(text(sql), params)]


def context_pack(db: Session, query: str = "", agent: str = "jarvis", solo_perfil: bool = False) -> dict:
    """Lo mínimo para arrancar un turno: estado actual, decisiones vivas y lo relacionado con la pregunta.
    El chat de un apartado solo recibe lo básico sobre el usuario: sus tareas y decisiones son de otros apartados."""
    hechos = [f for f in current_facts(db) if f["verification"] != "inferred"]
    if solo_perfil:
        return {"agente": agent, "hechos": hechos}
    pendientes = [t.text for t in db.scalars(select(Task).where(Task.done.is_(False), Task.removed_at.is_(None)).order_by(Task.due).limit(10))]
    decisiones = db.scalars(select(DecisionRecord).where(DecisionRecord.status == "active").order_by(DecisionRecord.id.desc()).limit(10))
    return {"agente": agent, "hechos": hechos, "tareas": pendientes, "decisiones": [{"titulo": d.title, "eleccion": d.choice} for d in decisiones],
            "relacionado": search(db, query, 5) if query else []}


# ---------- API ----------


class FactIn(BaseModel):
    subject: str = Field(min_length=1, max_length=80)
    predicate: str = Field(min_length=1, max_length=80)
    value: dict


class DecisionIn(BaseModel):
    decided_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    title: str = Field(min_length=1, max_length=200)
    domain: str = Field(default="general", max_length=32)
    context: str = ""
    choice: str = ""
    reason: str = ""
    status: str = Field(default="active", pattern="^(active|pending|abandoned|replaced)$")
    review_on: str | None = None


@router.get("/facts")
def facts(subject: str | None = None, db: Session = Depends(get_db)):
    return current_facts(db, subject)


@router.get("/facts/history")
def history(subject: str, predicate: str, db: Session = Depends(get_db)):
    q = select(Fact).where(Fact.subject == subject, Fact.predicate == predicate).order_by(Fact.recorded_at.desc())
    return [_fact(f) for f in db.scalars(q)]


@router.post("/facts")
def add_fact(body: FactIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    f = set_fact(db, body.subject, body.predicate, body.value, "confirmed", source_id=source(db, "user", p.name, "user"))
    events.audit(db, p.name, "fact.set", f"{body.subject}.{body.predicate}")
    return _fact(f)


@router.post("/facts/{fid}/verify")
def verify(fid: int, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    f = db.get(Fact, fid)
    if f is None:
        raise HTTPException(404, "Hecho no encontrado")
    f.verification, f.confidence = "confirmed", None
    events.audit(db, p.name, "fact.verify", str(fid))
    return _fact(f)


@router.post("/facts/{fid}/reject")
def reject(fid: int, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    f = db.get(Fact, fid)
    if f is None:
        raise HTTPException(404, "Hecho no encontrado")
    f.valid_to = utcnow()  # no se borra: queda que se descartó
    events.audit(db, p.name, "fact.reject", str(fid))
    return _fact(f)


@router.get("/events")
def life_events(domain: str | None = None, limit: int = 100, db: Session = Depends(get_db)):
    q = select(LifeEvent).order_by(LifeEvent.occurred_at.desc()).limit(min(max(limit, 1), 500))
    if domain:
        q = q.where(LifeEvent.domain == domain)
    return [{"id": e.id, "occurred_at": e.occurred_at.isoformat() + "Z", "domain": e.domain, "type": e.type, "title": e.title,
             "payload": e.payload} for e in db.scalars(q)]


@router.get("/decisions")
def decisions(status: str | None = None, db: Session = Depends(get_db)):
    q = select(DecisionRecord).order_by(DecisionRecord.decided_on.desc())
    if status:
        q = q.where(DecisionRecord.status == status)
    return [{"id": d.id, "fecha": d.decided_on, "area": d.domain, "titulo": d.title, "contexto": d.context, "eleccion": d.choice,
             "motivo": d.reason, "estado": d.status, "revisar": d.review_on, "resultado": d.outcome} for d in db.scalars(q)]


@router.post("/decisions")
def add_decision(body: DecisionIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    d = DecisionRecord(decided_on=body.decided_on, title=body.title, domain=body.domain, context=body.context, choice=body.choice,
                       reason=body.reason, status=body.status, review_on=body.review_on)
    db.add(d)
    db.flush()
    log_event(db, body.domain, "decision", body.title)
    events.audit(db, p.name, "decision.create", str(d.id))
    return {"id": d.id}


@router.get("/search")
def search_api(q: str, limit: int = 10, db: Session = Depends(get_db)):
    if len(q.strip()) < 2:
        raise HTTPException(422, "Escribe al menos 2 caracteres")
    return search(db, q.strip(), min(max(limit, 1), 50))


@router.post("/index", dependencies=[Depends(require_admin)])
def index_now():
    return reindex()


@router.post("/sync", dependencies=[Depends(require_admin)])
def sync_now():
    from ..modules import vault_sync
    return vault_sync.run_all()
