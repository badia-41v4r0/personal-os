"""Versiones del panel (Ajustes → Versiones): actualizar, deshacer personalizaciones y copias de seguridad.

Quien hace el trabajo es el supervisor de cambios (control-center/cambios/supervisor.py), que el Host Agent lanza como
unidad aparte: así sobrevive al reinicio del panel. `GET /progreso` lee directamente el archivo de estado que deja el
supervisor, para que la pantalla «Aplicando cambios…» funcione aunque el Host Agent se esté reiniciando.
"""
import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import events
from .adapters import hostagent
from .config import get_settings
from .db import session_scope
from .security import Principal, current_principal, require_admin

router = APIRouter(prefix="/api/v1/cambios", dependencies=[Depends(current_principal)])


def progreso_actual() -> dict | None:
    try:
        return json.loads((get_settings().cambios_dir / "estado.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


@router.get("/progreso")
def progreso():
    """La operación en curso o la última (lo que escribe el supervisor). No depende del Host Agent."""
    p = progreso_actual()
    if p:
        p = {k: v for k, v in p.items() if k not in ("commit_antes", "commit_despues")}
    return {"operacion": p}


@router.get("")
async def estado():
    try:
        return await hostagent.call("/v1/cambios", timeout=60)
    except HTTPException as e:
        if e.status_code in (502, 503):
            raise HTTPException(503, "El Host Agent no responde (¿se está reiniciando?)")
        raise


@router.post("/buscar")
async def buscar(p: Principal = Depends(require_admin)):
    return await hostagent.call("/v1/cambios/buscar", method="POST", timeout=130)


class OpIn(BaseModel):
    commit: str | None = Field(None, max_length=40)
    version: str | None = Field(None, max_length=20)
    copia: str | None = Field(None, max_length=40)
    vault: bool = False


async def _lanzar(op: str, cuerpo: dict, p: Principal) -> dict:
    r = await hostagent.call(f"/v1/cambios/{op}", method="POST", json=cuerpo, timeout=60)
    with session_scope() as db:
        events.audit(db, p.name, f"cambios.{op}", **{k: v for k, v in cuerpo.items() if v not in (None, "")})
    events.publish("cambios.iniciado", {"op": op})
    await asyncio.sleep(0.5)  # el supervisor escribe su estado al empezar
    return {**r, "operacion": progreso_actual()}


@router.post("/actualizar")
async def actualizar(body: OpIn, p: Principal = Depends(require_admin)):
    return await _lanzar("actualizar", {"version": body.version} if body.version else {}, p)


@router.post("/deshacer")
async def deshacer(body: OpIn, p: Principal = Depends(require_admin)):
    if not body.commit:
        raise HTTPException(422, "Falta la personalización")
    return await _lanzar("deshacer", {"commit": body.commit}, p)


@router.post("/restaurar")
async def restaurar(body: OpIn, p: Principal = Depends(require_admin)):
    if not body.copia:
        raise HTTPException(422, "Falta la copia")
    return await _lanzar("restaurar", {"copia": body.copia, "vault": body.vault}, p)
