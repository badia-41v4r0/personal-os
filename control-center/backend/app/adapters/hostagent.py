"""Cliente del Host Agent (socket Unix + token). El backend no ejecuta nada en el host por su cuenta."""
from contextvars import ContextVar

import httpx
from fastapi import HTTPException

from ..config import get_settings


# Quién pide esto: así la auditoría del Host Agent se puede cruzar con la del panel
ACTOR: ContextVar[str] = ContextVar("hostagent_actor", default="sistema")
RUN_ID: ContextVar[str] = ContextVar("hostagent_run", default="")


class HostAgentError(HTTPException):
    pass


async def call(path: str, params: dict | None = None, method: str = "GET", json: dict | None = None,
               timeout: float = 15) -> dict | list:
    s = get_settings()
    if not s.hostagent_socket.exists():
        raise HostAgentError(503, "Host Agent no disponible")
    transport = httpx.AsyncHTTPTransport(uds=str(s.hostagent_socket))
    async with httpx.AsyncClient(transport=transport, base_url="http://hostagent", timeout=timeout) as c:
        try:
            r = await c.request(method, path, params=params, json=json,
                                headers={"Authorization": f"Bearer {s.hostagent_token}", "X-Actor": ACTOR.get(), "X-Run-Id": RUN_ID.get()})
        except httpx.HTTPError:
            raise HostAgentError(503, "Host Agent no responde")
    if r.status_code >= 400:
        raise HostAgentError(r.status_code if r.status_code < 500 else 502, r.json().get("detail", "error"))
    return r.json()


def call_sync(path: str, method: str = "GET", json: dict | None = None, timeout: float = 15) -> dict | list:
    """Para los manejadores de acciones, que son síncronos."""
    s = get_settings()
    if not s.hostagent_socket.exists():
        raise HostAgentError(503, "Host Agent no disponible")
    with httpx.Client(transport=httpx.HTTPTransport(uds=str(s.hostagent_socket)), base_url="http://hostagent", timeout=timeout) as c:
        try:
            r = c.request(method, path, json=json, headers={"Authorization": f"Bearer {s.hostagent_token}", "X-Actor": ACTOR.get(), "X-Run-Id": RUN_ID.get()})
        except httpx.HTTPError:
            raise HostAgentError(503, "Host Agent no responde")
    if r.status_code >= 400:
        raise HostAgentError(r.status_code if r.status_code < 500 else 502, r.json().get("detail", "error"))
    return r.json()


async def available() -> bool:
    try:
        await call("/v1/health")
        return True
    except HTTPException:
        return False
