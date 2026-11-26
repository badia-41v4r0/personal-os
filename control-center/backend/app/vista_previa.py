"""/vista-previa/: el panel real hace de puerta a la vista previa del Constructor (control-center/cambios/vista_previa.py).

Así la vista previa funciona en la misma dirección que el panel (también desde el móvil con Tailscale), sin abrir otro
puerto ni tocar los orígenes permitidos. El panel comprueba la sesión del usuario y le pasa a la vista previa su
usuario, su token de sesión y su CSRF junto con el token de la vista previa (que solo conocen los dos): la vista previa
adopta esa sesión (security.adoptar_sesion_vista_previa). Las cookies que pudiera poner la vista previa no llegan al
navegador, para no pisar la sesión del panel real.

Si la vista previa está dormida (nadie la usó en una hora), se despierta al abrirla.
"""
import asyncio
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, Request, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from starlette.background import BackgroundTask

from .adapters import hostagent
from .config import get_settings
from .core import modules
from .db import session_scope
from .models import User
from .security import COOKIE, SAFE_METHODS, VP_CSRF, VP_HEADER, VP_USER, lookup_session, origin_ok

router = APIRouter()
PREFIJO = "/vista-previa"
SALTAR = {"host", "content-length", "connection", "keep-alive", "transfer-encoding", "upgrade", "proxy-connection", "te",
          "trailer", "accept-encoding", "cookie"}
SALTAR_RESP = {"set-cookie", "transfer-encoding", "connection", "keep-alive", "content-encoding"}
_cliente: httpx.AsyncClient | None = None
_uso = 0.0
_despertando = 0.0


def _personalizacion() -> dict | None:
    from .constructor import personalizacion
    return personalizacion()


def _usuario(token: str | None) -> tuple[str, str] | None:
    """(usuario, csrf) de la sesión del panel real, o None."""
    with session_scope() as db:
        sess = lookup_session(db, token)
        if sess is None:
            return None
        u = db.get(User, sess.user_id)
        if u is None or u.must_change_password or u.role != "admin":
            return None
        return u.username, sess.csrf_token


def _tocar_uso() -> None:
    global _uso
    if time.time() - _uso > 30:
        _uso = time.time()
        f: Path = get_settings().constructor_dir / "uso"
        try:
            f.touch()
        except OSError:
            pass


def _pagina(titulo: str, texto: str, recargar: bool = False, status: int = 200) -> HTMLResponse:
    meta = '<meta http-equiv="refresh" content="3">' if recargar else ""
    return HTMLResponse(f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
{meta}<title>{titulo}</title><style>body{{font-family:system-ui,sans-serif;display:grid;place-items:center;min-height:100vh;margin:0;
background:#0b0b0c;color:#e8e8ea}}main{{max-width:28rem;padding:2rem;text-align:center}}p{{color:#a1a1aa;line-height:1.5}}
a{{color:#8ab4ff}}.c{{width:28px;height:28px;border:3px solid #333;border-top-color:#8ab4ff;border-radius:50%;margin:0 auto 1rem;
animation:g 1s linear infinite}}@keyframes g{{to{{transform:rotate(360deg)}}}}</style></head><body><main>
{'<div class="c"></div>' if recargar else ''}<h1 style="font-size:1.2rem">{titulo}</h1><p>{texto}</p><p><a href="/">Volver al panel</a></p>
</main></body></html>""", status_code=status, headers={"Cache-Control": "no-store"})


async def _despertar() -> None:
    global _despertando
    if time.time() - _despertando < 20:
        return
    _despertando = time.time()
    try:
        await hostagent.call("/v1/constructor/arrancar", method="POST", timeout=30)
    except Exception:  # noqa: BLE001
        pass


def _cliente_http() -> httpx.AsyncClient:
    global _cliente
    if _cliente is None:
        _cliente = httpx.AsyncClient(timeout=httpx.Timeout(300, connect=3), follow_redirects=False)
    return _cliente


def _no_disponible(es_api: bool, p: dict | None):
    if es_api:
        return JSONResponse({"detail": "La vista previa no está en marcha"}, status_code=503)
    if p is None:
        return _pagina("No hay ninguna vista previa abierta",
                       "Pídele un cambio al Constructor desde el chat y aquí verás cómo queda antes de aplicarlo.", status=404)
    if p.get("estado") == "error":
        return _pagina("La vista previa no se ha podido preparar", p.get("error") or "Error desconocido. Descártala desde el chat y vuelve a intentarlo.")
    if p.get("estado") == "preparando":
        return _pagina("Preparando la vista previa…", (p.get("paso") or "Copiando el panel") + ". La primera vez tarda unos minutos.", recargar=True)
    return _pagina("Arrancando la vista previa…", "Un momento: estaba dormida porque nadie la usaba.", recargar=True)


@router.get(PREFIJO, include_in_schema=False)
async def raiz():
    return RedirectResponse(PREFIJO + "/", status_code=308)


@router.api_route(PREFIJO + "/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"], include_in_schema=False)
async def proxy(path: str, request: Request):
    es_api = path.startswith("api/")
    if not await asyncio.to_thread(modules.activo, "constructor"):
        return _pagina("El Constructor está desactivado", "Actívalo en Ajustes → Módulos.", status=404)
    token = request.cookies.get(COOKIE)
    quien = _usuario(token)
    if quien is None:
        if es_api:
            return JSONResponse({"detail": "No autenticado"}, status_code=401)
        return RedirectResponse("/login/", status_code=303)
    if request.method not in SAFE_METHODS and not origin_ok(request.headers.get("origin")):
        return JSONResponse({"detail": "Origen no permitido"}, status_code=403)
    p = _personalizacion()
    if p is None or p.get("estado") not in ("lista", "dormida") or not p.get("puerto") or not p.get("token"):
        return _no_disponible(es_api, p)
    _tocar_uso()
    headers = {k: v for k, v in request.headers.items() if k.lower() not in SALTAR}
    headers |= {VP_HEADER: p["token"], VP_USER: quien[0], VP_CSRF: quien[1], "cookie": f"{COOKIE}={token}"}
    url = f"http://127.0.0.1:{p['puerto']}/{path}" + (f"?{request.url.query}" if request.url.query else "")
    c = _cliente_http()
    try:
        r = await c.send(c.build_request(request.method, url, headers=headers, content=request.stream()), stream=True)
    except httpx.HTTPError:  # dormida o arrancando: se despierta
        asyncio.get_running_loop().create_task(_despertar())
        return _no_disponible(es_api, {**p, "estado": "dormida"})
    out = {}
    for k, v in r.headers.multi_items():
        lk = k.lower()
        if lk in SALTAR_RESP:
            continue
        if lk == "location" and v.startswith("/") and not v.startswith(PREFIJO + "/") and not v.startswith("/api/"):
            v = PREFIJO + v
        out[k] = v
    return StreamingResponse(r.aiter_raw(), status_code=r.status_code, headers=out, background=BackgroundTask(r.aclose))


@router.websocket(PREFIJO + "/api/v1/ws")
async def ws(websocket: WebSocket):
    """Los eventos en directo de la vista previa (mismo protocolo que /api/v1/ws)."""
    import websockets
    token = websocket.cookies.get(COOKIE)
    quien = _usuario(token) if origin_ok(websocket.headers.get("origin")) else None
    p = _personalizacion()
    if quien is None or not p or p.get("estado") != "lista":
        await websocket.close(code=4401 if quien is None else 1013)
        return
    _tocar_uso()
    await websocket.accept()
    q = websocket.url.query
    try:
        up = await websockets.connect(f"ws://127.0.0.1:{p['puerto']}/api/v1/ws" + (f"?{q}" if q else ""), max_size=None,
                                      additional_headers={"Origin": websocket.headers.get("origin", ""), "Cookie": f"{COOKIE}={token}",
                                                          VP_HEADER: p["token"], VP_USER: quien[0], VP_CSRF: quien[1]})
    except Exception:  # noqa: BLE001
        await websocket.close(code=1011)
        return

    async def bajada():
        try:
            async for m in up:
                await (websocket.send_bytes(m) if isinstance(m, bytes) else websocket.send_text(m))
        finally:
            try:
                await websocket.close()
            except Exception:  # noqa: BLE001
                pass

    t = asyncio.create_task(bajada())
    try:
        while True:
            m = await websocket.receive()
            if m["type"] == "websocket.disconnect":
                break
            if m.get("text") is not None:
                await up.send(m["text"])
            elif m.get("bytes") is not None:
                await up.send(m["bytes"])
            _tocar_uso()
    except Exception:  # noqa: BLE001
        pass
    finally:
        t.cancel()
        await up.close()
