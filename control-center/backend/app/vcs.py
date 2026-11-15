"""Ordenadores virtuales: registro, ciclo de vida, políticas y acceso desde el panel.

El backend no toca Docker: todo pasa por el Host Agent. Aquí se guardan los metadatos (dueño, perfil, persistencia,
caducidad, límites), se auditan las acciones y se aplican las políticas cada minuto:
- caducidad (`ttl`): al vencer se elimina; `ephemeral`: se elimina al pararse o al terminar la ejecución que lo pidió;
- disco: si el home supera su límite, se para y se avisa (el driver local de Docker no permite limitarlo);
- contenedores con la etiqueta jarvis.vc que no estén en la base (creados para un agente) se registran.
Terminal y escritorio: WebSocket del navegador (cookie + Origin) ↔ WebSocket del Host Agent (socket Unix + token).
"""
import asyncio
import base64
import logging
import uuid as uuidlib
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, WebSocket
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import events
from .adapters import hostagent
from .config import INSTANCE, get_settings
from .db import get_db, session_scope, utcnow
from .models import VirtualComputer, VirtualComputerEvent
from .security import (COOKIE, WS_RECHECK_SECONDS, Principal, current_principal, require_admin, session_alive,
                       websocket_principal)

log = logging.getLogger("cc.vcs")
router = APIRouter(prefix="/api/v1/virtual-computers")
auth = [Depends(current_principal)]
MAX_ACTIVE = 3  # ordenadores en marcha a la vez (RAM justa)


class CreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    profile: str = Field("terminal", pattern="^(terminal|browser|desktop|canvas)$")
    internet: bool = False
    persistence: str = Field("ephemeral", pattern="^(ephemeral|persistent|ttl)$")
    ttl_hours: float = Field(4, gt=0, le=168)
    cpus: float = Field(1, ge=0.25, le=2)
    memory_mb: int = Field(1536, ge=256, le=4096)
    disk_mb: int = Field(2048, ge=128, le=10240)
    owner_agent: str | None = Field(None, max_length=64)


def _iso(d):
    return d.isoformat() + "Z" if d else None


def _out(v: VirtualComputer, live: dict | None = None) -> dict:
    return {"id": v.id, "name": v.name, "profile": v.profile, "owner_agent": v.owner_agent, "persistence": v.persistence,
            "expires_at": _iso(v.expires_at), "internet": v.internet, "status": v.status, "limits": v.limits,
            "created_by": v.created_by, "created_at": _iso(v.created_at), "last_activity": _iso(v.last_activity),
            "container": v.container_id, "live": live}


def _event(db: Session, vid: str, type_: str, actor: str, **detail) -> None:
    db.add(VirtualComputerEvent(vc_id=vid, type=type_, actor=actor, detail=detail))
    events.publish(f"vc.{type_}", {"id": vid, **detail}, db=db)


async def create_vc(body: CreateIn, actor: str, session: str = "") -> dict:
    extra = {}
    if body.profile == "canvas":
        # Campus: guarda la sesión de la universidad, así que es persistente; sale solo por su proxy (dominios del campus)
        from .modules import campus
        body.persistence, body.internet = "persistent", False
        extra = {"egress_allow": campus.dominios(), "start_url": campus.url()}
        if not campus.url():
            raise HTTPException(409, "Configura antes tu campus (Educación → Configurar): falta su dirección")
        if body.owner_agent:
            with session_scope() as db:
                if db.scalars(select(VirtualComputer).where(VirtualComputer.owner_agent == body.owner_agent,
                                                            VirtualComputer.profile == "canvas",
                                                            VirtualComputer.status != "deleted")).first():
                    raise HTTPException(409, f"{body.owner_agent} ya tiene un ordenador del campus")
    with session_scope() as db:
        n = len(list(db.scalars(select(VirtualComputer).where(VirtualComputer.status.in_(("running", "creating"))))))
        if n >= MAX_ACTIVE:
            raise HTTPException(429, f"Ya hay {n} ordenadores en marcha (máximo {MAX_ACTIVE})")
        vid = str(uuidlib.uuid4())
        v = VirtualComputer(id=vid, name=body.name, profile=body.profile, owner_agent=body.owner_agent,
                            persistence=body.persistence, internet=body.internet, status="creating",
                            expires_at=utcnow() + timedelta(hours=body.ttl_hours) if body.persistence == "ttl" else None,
                            limits={"cpus": body.cpus, "memory_mb": body.memory_mb, "disk_mb": body.disk_mb,
                                    "session": session or None},
                            created_by=actor, container_id=f"{INSTANCE}-vc-{vid[:8]}")
        db.add(v)
        events.audit(db, actor, "vc.create", target=vid, profile=body.profile, internet=body.internet,
                     persistence=body.persistence, owner=body.owner_agent or "")
    try:
        await hostagent.call("/v1/vc/create", method="POST", timeout=90, json={
            "id": vid, "profile": body.profile, "internet": body.internet, "cpus": body.cpus,
            "memory_mb": body.memory_mb, "disk_mb": body.disk_mb, "owner": body.owner_agent or actor, "session": session, **extra})
    except HTTPException as e:
        with session_scope() as db:
            v = db.get(VirtualComputer, vid)
            v.status = "error"
            _event(db, vid, "error", actor, error=str(e.detail))
        raise
    with session_scope() as db:
        v = db.get(VirtualComputer, vid)
        v.status = "running"
        _event(db, vid, "created", actor, profile=body.profile)
        return _out(v)


async def remove_vc(vid: str, actor: str, reason: str) -> None:
    await hostagent.call(f"/v1/vc/{vid}/lifecycle/remove", method="POST", timeout=60)
    with session_scope() as db:
        v = db.get(VirtualComputer, vid)
        if v:
            v.status = "deleted"
            events.audit(db, actor, "vc.delete", target=vid, reason=reason)
            _event(db, vid, "deleted", actor, reason=reason)


@router.get("", dependencies=auth)
async def list_vcs(include_deleted: bool = False):
    try:
        live = {x["id"]: x for x in await hostagent.call("/v1/vc")}
    except HTTPException:
        live = {}
    with session_scope() as db:
        q = select(VirtualComputer).order_by(VirtualComputer.created_at.desc())
        if not include_deleted:
            q = q.where(VirtualComputer.status != "deleted")
        return [_out(v, live.get(v.id)) for v in db.scalars(q)]


@router.post("")
async def create(body: CreateIn, p: Principal = Depends(require_admin)):
    return await create_vc(body, p.name)


def _get(db: Session, vid: str) -> VirtualComputer:
    v = db.get(VirtualComputer, vid)
    if v is None or v.status == "deleted":
        raise HTTPException(404, "Ordenador no encontrado")
    return v


@router.get("/{vid}", dependencies=auth)
async def get(vid: str):
    with session_scope() as db:
        v = _get(db, vid)
        evs = [{"ts": _iso(e.ts), "type": e.type, "actor": e.actor, "detail": e.detail}
               for e in db.scalars(select(VirtualComputerEvent).where(VirtualComputerEvent.vc_id == vid)
                                   .order_by(VirtualComputerEvent.id.desc()).limit(50))]
        out = _out(v)
    try:
        out["live"] = next((x for x in await hostagent.call("/v1/vc") if x["id"] == vid), None)
    except HTTPException:
        out["live"] = None
    if out["live"] and out["live"]["state"] == "running":
        try:
            out["disk_bytes"] = (await hostagent.call(f"/v1/vc/{vid}/disk"))["bytes"]
        except HTTPException:
            out["disk_bytes"] = None
    out["events"] = evs
    return out


# ---------- Canvas: registro del proxy (antes de la ruta genérica /{vid}/{action}) ----------

@router.get("/{vid}/egress", dependencies=auth)
async def egress_log(vid: str, lines: int = 200):
    with session_scope() as db:
        _get(db, vid)
    return await hostagent.call(f"/v1/vc/{vid}/egress", {"lines": max(1, min(lines, 2000))})


@router.post("/{vid}/{action}")
async def lifecycle(vid: str, action: str, p: Principal = Depends(require_admin)):
    if action not in ("start", "stop", "restart"):
        raise HTTPException(404, "Acción desconocida")
    with session_scope() as db:
        v = _get(db, vid)
        if action == "start":
            n = len(list(db.scalars(select(VirtualComputer).where(VirtualComputer.status == "running"))))
            if n >= MAX_ACTIVE:
                raise HTTPException(429, f"Ya hay {n} ordenadores en marcha (máximo {MAX_ACTIVE})")
        ephemeral = v.persistence == "ephemeral"
    if action == "stop" and ephemeral:
        await remove_vc(vid, p.name, "efímero parado")
        return {"status": "deleted"}
    await hostagent.call(f"/v1/vc/{vid}/lifecycle/{action}", method="POST", timeout=60)
    with session_scope() as db:
        v = db.get(VirtualComputer, vid)
        v.status, v.last_activity = ("stopped" if action == "stop" else "running"), utcnow()
        events.audit(db, p.name, f"vc.{action}", target=vid)
        _event(db, vid, action, p.name)
        return {"status": v.status}


@router.delete("/{vid}")
async def delete(vid: str, p: Principal = Depends(require_admin)):
    with session_scope() as db:
        _get(db, vid)
    await remove_vc(vid, p.name, "eliminado desde el panel")
    return {"ok": True}


@router.get("/{vid}/logs", dependencies=auth)
async def logs(vid: str, lines: int = 200):
    return await hostagent.call(f"/v1/logs/container/{INSTANCE}-vc-{vid[:8]}", {"lines": lines})


@router.get("/{vid}/files", dependencies=auth)
async def files(vid: str, path: str = "/home/vc/trabajo"):
    return await hostagent.call(f"/v1/vc/{vid}/files", {"path": path})


@router.get("/{vid}/download")
async def download(vid: str, path: str, p: Principal = Depends(current_principal)):
    r = await hostagent.call(f"/v1/vc/{vid}/file", {"path": path}, timeout=90)
    with session_scope() as db:
        events.audit(db, p.name, "vc.download", target=vid, path=path, bytes=r["size"])
    name = path.rsplit("/", 1)[-1].replace('"', "")
    # Siempre como descarga y sin interpretar (no se sirve HTML del ordenador en el origen del panel)
    return Response(base64.b64decode(r["base64"]), media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "X-Content-Type-Options": "nosniff"})


@router.get("/{vid}/screenshot", dependencies=auth)
async def screenshot(vid: str):
    r = await hostagent.call(f"/v1/vc/{vid}/screenshot", timeout=30)
    return Response(base64.b64decode(r["png_base64"]), media_type="image/png")


# ---------- WebSockets: terminal y escritorio ----------

async def _proxy(ws: WebSocket, vid: str, kind: str) -> None:
    import websockets
    with session_scope() as db:
        p = websocket_principal(ws, db)
        v = db.get(VirtualComputer, vid) if p else None
        ok = p is not None and p.user.role == "admin" and v is not None and v.status == "running"
        if ok:
            events.audit(db, p.name, f"vc.{kind}", target=vid)
    if not ok:
        await ws.close(code=4401)
        return
    await ws.accept(subprotocol="binary" if kind == "vnc" and "binary" in ws.headers.get("sec-websocket-protocol", "") else None)
    s = get_settings()
    try:
        upstream = await websockets.unix_connect(str(s.hostagent_socket), f"ws://hostagent/v1/vc/{vid}/{kind}",
                                                 additional_headers={"Authorization": f"Bearer {s.hostagent_token}"},
                                                 max_size=None)
    except Exception:  # noqa: BLE001
        await ws.close(code=1011)
        return

    async def down():
        async for m in upstream:
            if isinstance(m, bytes):
                await ws.send_bytes(m)
            else:
                await ws.send_text(m)

    async def guard():
        """La terminal y el escritorio no sobreviven al cierre de sesión."""
        token = ws.cookies.get(COOKIE)
        while True:
            await asyncio.sleep(WS_RECHECK_SECONDS)
            if not session_alive(token):
                await ws.close(code=4401)
                await upstream.close()
                return

    t = asyncio.create_task(down())
    g = asyncio.create_task(guard())
    try:
        while True:
            m = await ws.receive()
            if m["type"] == "websocket.disconnect":
                break
            if m.get("bytes") is not None:
                await upstream.send(m["bytes"])
            elif m.get("text") is not None:
                await upstream.send(m["text"])
    except Exception:  # noqa: BLE001
        pass
    finally:
        t.cancel()
        g.cancel()
        await upstream.close()
    with session_scope() as db:
        v = db.get(VirtualComputer, vid)
        if v:
            v.last_activity = utcnow()


@router.websocket("/{vid}/tty")
async def tty(ws: WebSocket, vid: str):
    await _proxy(ws, vid, "tty")


@router.websocket("/{vid}/vnc")
async def vnc(ws: WebSocket, vid: str):
    await _proxy(ws, vid, "vnc")


# ---------- políticas (cada minuto) ----------

async def reconcile() -> None:
    try:
        live = {x["id"]: x for x in await hostagent.call("/v1/vc")}
    except HTTPException:
        return
    now = utcnow()
    to_remove: list[tuple[str, str]] = []
    with session_scope() as db:
        known = {v.id: v for v in db.scalars(select(VirtualComputer).where(VirtualComputer.status != "deleted"))}
        for vid, x in live.items():
            if vid not in known and vid:
                # Creado para un agente por la pasarela de su sesión: se registra
                v = VirtualComputer(id=vid, name=f"{x.get('profile')} · {x.get('owner') or 'agente'}", profile=x.get("profile") or "terminal",
                                    owner_agent=(x.get("owner") or "").removeprefix("agent:") or None, persistence="ttl",
                                    expires_at=now + timedelta(hours=2),
                                    status="running" if x["state"] == "running" else "stopped", internet=False,
                                    limits={"disk_mb": int(x.get("disk_mb") or 2048), "session": x.get("session") or None},
                                    created_by=x.get("owner") or "agente", container_id=x["container"])
                db.add(v)
                db.flush()
                _event(db, vid, "registered", "sistema", owner=x.get("owner"))
        for vid, v in known.items():
            x = live.get(vid)
            if x is None:
                if v.status in ("running", "stopped"):
                    v.status = "deleted"
                    _event(db, vid, "vanished", "sistema")
                continue
            state = "running" if x["state"] == "running" else "stopped"
            if v.status != state and v.status not in ("creating",):
                v.status = state
                _event(db, vid, state, "sistema")
            if v.persistence == "ttl" and v.expires_at and v.expires_at <= now:
                to_remove.append((vid, "caducado"))
            elif v.persistence == "ephemeral" and state == "stopped":
                to_remove.append((vid, "efímero parado"))
    for vid, why in to_remove:
        try:
            await remove_vc(vid, "sistema", why)
        except HTTPException as e:
            log.warning("no se pudo eliminar %s: %s", vid, e.detail)
    # Límite de disco del home
    with session_scope() as db:
        running = [(v.id, (v.limits or {}).get("disk_mb", 2048)) for v in
                   db.scalars(select(VirtualComputer).where(VirtualComputer.status == "running"))]
    for vid, limit in running:
        try:
            used = (await hostagent.call(f"/v1/vc/{vid}/disk"))["bytes"]
        except HTTPException:
            continue
        if used > limit * 1024 * 1024:
            await hostagent.call(f"/v1/vc/{vid}/lifecycle/stop", method="POST", timeout=60)
            with session_scope() as db:
                v = db.get(VirtualComputer, vid)
                v.status = "stopped"
                events.audit(db, "sistema", "vc.stop", target=vid, reason="disco", used=used)
                _event(db, vid, "disk_limit", "sistema", used_mb=used // 1048576, limit_mb=limit)


async def loop() -> None:
    await asyncio.sleep(10)
    while True:
        try:
            await reconcile()
        except Exception as e:  # noqa: BLE001
            log.exception("vcs: %s", e)
        await asyncio.sleep(60)
