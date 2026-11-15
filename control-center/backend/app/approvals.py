"""Tasks & Approvals: integra lo que ya existe, sin un sistema paralelo.

- Propuestas de skills y subagentes de Jarvis: las valida e instala `bin/aprobar` (a través del Host Agent).
  Aprobar envía la huella del contenido que se ha visto: si Jarvis cambia el borrador entretanto, no se instala.
  Cada decisión queda en `approvals` (historial) y en la auditoría.
- Colas en la vault (programador, ayudante, repos, vídeos): solo lectura. Ya las aprobó el usuario por chat al crearlas
  y se procesan solas en segundos (unidades .path).
- Solicitudes de permisos de Jarvis (`Propuestas/solicitudes.md`): pendientes = líneas sin ✅. Se resuelven en el PC.
"""
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import events
from .adapters import hostagent
from .config import get_settings
from .db import get_db, utcnow
from .models import Approval
from .security import Principal, current_principal, require_admin

router = APIRouter(prefix="/api/v1", dependencies=[Depends(current_principal)])

QUEUES = {
    "encargos": ("Encargos", "Programador (código en las repos)", ("cola", "en-curso", "hechos")),
    "ayudante": ("Ayudante", "Ayudante (tareas con internet)", ("cola", "en-curso", "hechos")),
    "repos": ("Repos", "Repos nuevas de GitHub", ("cola", "hechos")),
    "videos": ("Videos", "Vídeos para analizar", ("cola", "hechos")),
}
FM_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.S)


def _impact(p: dict) -> str:
    if not p.get("valida"):
        return "No pasa la validación de bin/aprobar: no se puede instalar."
    if p["tipo"] == "skill":
        s = f"Instala la skill «{p['nombre']}» en {p['destino']}. Jarvis la ve sin reiniciar."
    else:
        tools = ", ".join(p.get("herramientas") or []) or "ninguna"
        s = (f"Instala el subagente «{p['nombre']}» en {p['destino']} con herramientas {tools} "
             f"y modelo {p.get('modelo') or 'el de la sesión'}. Jarvis lo podrá usar en su próxima sesión.")
    if p.get("sustituye"):
        s += " Sustituye al existente."
    if "Bash" in (p.get("herramientas") or []):
        s += " ⚠️ Pide Bash: Jarvis solo puede ejecutar los comandos que ya tiene permitidos."
    return s


@router.get("/approvals")
async def approvals(db: Session = Depends(get_db)):
    try:
        pend = await hostagent.call("/v1/proposals", timeout=40)
        error = None
    except HTTPException as e:
        pend, error = [], str(e.detail)
    for p in pend:
        p["impacto"] = _impact(p)
        p["solicitado_por"] = "Jarvis"
    hist = [{"id": a.id, "kind": a.kind, "ref": a.ref, "requested_by": a.requested_by, "action": a.action,
             "impact": a.impact, "status": a.status, "decided_by": a.decided_by,
             "decided_at": a.decided_at.isoformat() + "Z" if a.decided_at else None, "result": a.result}
            for a in db.scalars(select(Approval).order_by(Approval.id.desc()).limit(50))]
    archivo = get_settings().vault / "Jarvis/Propuestas/_archivo"
    previas = []
    if archivo.is_dir():
        for d in sorted(archivo.iterdir(), reverse=True)[:30]:
            m = re.match(r"^(.*)-(\d{8})-(\d{6})-(instalada|rechazada)$", d.name)
            if m:
                previas.append({"nombre": m[1], "fecha": f"{m[2][:4]}-{m[2][4:6]}-{m[2][6:]}", "estado": m[4],
                                "path": f"Jarvis/Propuestas/_archivo/{d.name}"})
    return {"pendientes": pend, "error": error, "historial": hist, "archivo": previas}


class ApproveIn(BaseModel):
    hash: str = Field(pattern="^[a-f0-9]{64}$")


class RejectIn(BaseModel):
    motivo: str = Field("", max_length=500)


def _record(db: Session, name: str, action: str, impact: str, status: str, actor: str, result: str) -> None:
    db.add(Approval(kind="propuesta", ref=name, requested_by="Jarvis", action=action, impact=impact, status=status,
                    decided_by=actor, decided_at=utcnow(), result=result[:4000]))


@router.post("/approvals/proposals/{name}/approve")
async def approve(name: str, body: ApproveIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    pend = {x["nombre"]: x for x in await hostagent.call("/v1/proposals", timeout=40)}
    prop = pend.get(name)
    if prop is None:
        raise HTTPException(404, "Esa propuesta ya no está pendiente")
    try:
        r = await hostagent.call(f"/v1/proposals/{name}/approve", method="POST", json={"hash": body.hash}, timeout=90)
        status, result = "done", r.get("output", "")
    except HTTPException as e:
        status, result = "error", str(e.detail)
    _record(db, name, f"Instalar {prop.get('tipo', 'propuesta')} «{name}»", _impact(prop), status, p.name, result)
    events.audit(db, p.name, "approval.approve", target=name, outcome="ok" if status == "done" else "error")
    events.publish("approval.decided", {"ref": name, "status": status}, db=db)
    if status != "done":
        db.commit()
        raise HTTPException(409, result)
    return {"ok": True, "result": result}


@router.post("/approvals/proposals/{name}/reject")
async def reject(name: str, body: RejectIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    await hostagent.call(f"/v1/proposals/{name}/reject", method="POST", json={"motivo": body.motivo})
    _record(db, name, f"Rechazar «{name}»", body.motivo or "Sin motivo", "rejected", p.name, "Archivada en Propuestas/_archivo")
    events.audit(db, p.name, "approval.reject", target=name)
    events.publish("approval.decided", {"ref": name, "status": "rejected"}, db=db)
    return {"ok": True}


def _frontmatter(text: str) -> tuple[dict, str]:
    m = FM_RE.match(text)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        if k.strip():
            meta[k.strip()] = v.strip()
    return meta, m.group(2)


def _item(base, path, estado: str) -> dict:
    rel = path.relative_to(get_settings().vault).as_posix()
    main = path if path.is_file() else next((path / n for n in ("tarea.md", "peticion.md", "info.md") if (path / n).exists()), None)
    meta, body = _frontmatter(main.read_text(encoding="utf-8", errors="replace")) if main else ({}, "")
    resultado = ""
    if "## Resultado" in body:
        resultado = body.split("## Resultado", 1)[1].strip()[:1500]
    elif path.is_dir() and (path / "resultado.md").exists():
        resultado = (path / "resultado.md").read_text(encoding="utf-8", errors="replace")[:1500]
    elif path.is_dir() and (path / "error.md").exists():
        resultado = "Error: " + (path / "error.md").read_text(encoding="utf-8", errors="replace")[:800]
    return {"id": path.name.removesuffix(".md"), "estado": estado, "path": rel, "meta": meta,
            "titulo": meta.get("titulo") or meta.get("nombre") or meta.get("url") or path.name,
            "resumen": body.split("## Resultado")[0].strip()[:600], "resultado": resultado,
            "mtime": path.stat().st_mtime}


@router.get("/queues")
def queues():
    root = get_settings().vault / "Jarvis"
    out = []
    for key, (folder, label, states) in QUEUES.items():
        items = []
        for st in states:
            d = root / folder / st
            if not d.is_dir():
                continue
            entries = sorted((x for x in d.iterdir() if not x.name.startswith(".")), key=lambda x: x.name, reverse=True)
            for e in entries[: (20 if st == "hechos" else 50)]:
                try:
                    items.append(_item(root, e, st))
                except OSError:
                    continue
        out.append({"id": key, "label": label, "folder": f"Jarvis/{folder}", "items": items,
                    "pendientes": sum(1 for i in items if i["estado"] in ("cola", "en-curso"))})
    return out


@router.get("/requests")
def requests_():
    """Solicitudes de permisos de Jarvis (Propuestas/solicitudes.md)."""
    f = get_settings().vault / "Jarvis/Propuestas/solicitudes.md"
    if not f.exists():
        return {"pendientes": [], "hechas": [], "path": None}
    pend, done = [], []
    for line in f.read_text(encoding="utf-8").splitlines():
        if not line.startswith("- "):
            continue
        text = line[2:].strip()
        m = re.match(r"^(✅\s*\(([^)]*)\)\s*)?(\d{4}-\d{2}-\d{2})\s*·\s*(.*)$", text)
        if not m:
            continue
        item = {"fecha": m[3], "texto": m[4], "resuelta": m[2]}
        (done if m[1] else pend).append(item)
    return {"pendientes": pend, "hechas": done, "path": "Jarvis/Propuestas/solicitudes.md"}
