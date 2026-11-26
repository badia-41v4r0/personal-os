"""Máquinas locales (VirtualBox del usuario) desde el panel: estado, asistente para conectarlas, agentes y notas.

El backend no toca VirtualBox, ni SSH, ni secrets/: todo lo hace el Host Agent (host-agent/maquinas_admin.py), que es
también quien aplica qué agente puede usar cada máquina. Aquí se comprueba el rol, se valida que los agentes existan y
tengan la capacidad «ordenador», y se audita cada cambio.
"""
import base64

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import events
from .adapters import hostagent
from .db import get_db
from .models import AgentDefinition, AgentVersion
from .security import Principal, current_principal, require_admin

router = APIRouter(prefix="/api/v1/maquinas")
ID = r"^[a-z][a-z0-9-]{1,31}$"


def agentes_con_ordenador(db: Session) -> list[dict]:
    """Agentes del panel activos con la capacidad «ordenador»: los únicos que reciben las herramientas vm_*."""
    from .agents import seed_panel
    seed_panel(db)  # instalación nueva: el tutor aún no se había creado (como en la lista de agentes)
    out = []
    for a in db.scalars(select(AgentDefinition).where(AgentDefinition.status == "active").order_by(AgentDefinition.id)):
        v = db.scalar(select(AgentVersion).where(AgentVersion.agent_id == a.id, AgentVersion.version == a.current_version))
        spec = (v.spec if v else {}) or {}
        if spec.get("target") == "panel" and spec.get("virtual_computer"):
            out.append({"id": a.id, "nombre": a.name, "descripcion": a.description})
    return out


class PrepararIn(BaseModel):
    vbox: str = Field(min_length=1, max_length=64)
    nombre: str = Field("", max_length=80)
    instantanea: bool = True


class ProbarIn(BaseModel):
    usuario: str = Field("", max_length=32)


class CambiosIn(BaseModel):
    nombre: str | None = Field(None, max_length=80)
    agentes: list[str] | None = Field(None, max_length=20)
    notas: str | None = Field(None, max_length=2000)


class AccionIn(BaseModel):
    que: str = Field(pattern="^(encender|apagar)$")


def _audit(db: Session, p: Principal, action: str, target: str, **detail) -> None:
    events.audit(db, p.user.username, f"maquinas.{action}", target=target, **detail)
    events.publish("maquinas.changed", {"id": target, "action": action}, db=db)


@router.get("")
async def get_estado(p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    try:
        e = await hostagent.call("/v1/maquinas", timeout=60)
    except HTTPException as ex:
        e = {"virtualbox": {"instalado": False, "version": None}, "vms": [], "maquinas": [], "error": ex.detail}
    return e | {"agentes": agentes_con_ordenador(db)}


@router.post("")
async def preparar(body: PrepararIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    r = await hostagent.call("/v1/maquinas", method="POST", json=body.model_dump(), timeout=360)
    _audit(db, p, "preparar", r["id"], vbox=body.vbox, hecho=r.get("hecho"))
    return r


@router.post("/{mid}/probar")
async def probar(mid: str, body: ProbarIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    _id(mid)
    r = await hostagent.call(f"/v1/maquinas/{mid}/probar", method="POST", json=body.model_dump(), timeout=90)
    _audit(db, p, "probar", mid, ok=r.get("ok"))
    return r


@router.patch("/{mid}")
async def cambiar(mid: str, body: CambiosIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    _id(mid)
    if body.agentes is not None:
        validos = {a["id"] for a in agentes_con_ordenador(db)}
        malos = [a for a in body.agentes if a not in validos]
        if malos:
            raise HTTPException(422, f"Estos agentes no existen o no tienen la capacidad «ordenador»: {', '.join(malos)}")
    cambios = body.model_dump(exclude_none=True)
    r = await hostagent.call(f"/v1/maquinas/{mid}", method="PATCH", json=cambios, timeout=30)
    _audit(db, p, "cambiar", mid, campos=sorted(cambios), agentes=body.agentes)
    return r


@router.delete("/{mid}")
async def quitar(mid: str, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    _id(mid)
    r = await hostagent.call(f"/v1/maquinas/{mid}", method="DELETE", timeout=60)
    _audit(db, p, "quitar", mid)
    return r


@router.post("/{mid}/accion")
async def accion(mid: str, body: AccionIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    _id(mid)
    r = await hostagent.call(f"/v1/maquinas/{mid}/accion", method="POST", json=body.model_dump(), timeout=120)
    _audit(db, p, body.que, mid)
    return r


@router.get("/{mid}/captura", dependencies=[Depends(require_admin)])
async def captura(mid: str):
    _id(mid)
    r = await hostagent.call(f"/v1/maquinas/{mid}/captura", timeout=40)
    return Response(base64.b64decode(r["png_base64"]), media_type="image/png", headers={"Cache-Control": "no-store"})


def _id(mid: str) -> None:
    import re
    if not re.fullmatch(ID, mid):
        raise HTTPException(422, "id no válido")
