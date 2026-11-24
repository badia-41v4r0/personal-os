"""Aplicación FastAPI del Control Center. Arranque: uvicorn app.main:app --host 127.0.0.1 --port 8770"""
import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .adapters import hostagent
from .config import ROOT
from .security import COOKIE, actor_name

from . import claude_usage, events, extensiones, main_session, model_usage, monitor, rutas_viejas, sessions, vcs
from .api.routes import router
from .core import actions, assistants, gateway, memory, notifications
from .modules import agent_caps  # noqa: F401  (registra capacidades y lecturas)
from .modules import onboarding as onboarding_module  # noqa: F401  (config.*.set, onboarding.hecho, config.get)
from .modules import finance as finance_module
from .modules import checkin as checkin_module
from .modules import home as home_module
from .modules import education as education_module
from .modules import calendar_view as calendar_module
from .modules import applications as applications_module
from .modules import personal as personal_module
from .modules import ocio as ocio_module
from .gym import router as gym_router
from .gym_plan import router as gym_plan_router
from .vault import router as vault_router
from .agenda import router as agenda_router
from .monitor import router as monitor_router
from .sessions import router as sessions_router
from .conversaciones import router as conversaciones_router
from .agents import router as agents_router
from .vcs import router as vcs_router
from .approvals import router as approvals_router
from .projects import router as projects_router
from .claude_usage import router as usage_router
from .model_usage import router as model_usage_router
from .instancia import router as instancia_router
from .core import modules


@asynccontextmanager
async def lifespan(_: FastAPI):
    events.bind_loop(asyncio.get_running_loop())
    events.publish("backend.started")
    main_session.start()
    sessions.recover()
    notify_task = asyncio.create_task(notifications.loop())
    vc_task = None
    if os.environ.get("CC_MONITOR", "1") == "1":
        monitor.start()
        vc_task = asyncio.create_task(vcs.loop())
        usage_task = asyncio.create_task(claude_usage.loop())
        models_task = asyncio.create_task(model_usage.loop())
    yield
    await monitor.stop()
    notify_task.cancel()
    if vc_task:
        vc_task.cancel()
        usage_task.cancel()
        models_task.cancel()
    await main_session.stop()


app = FastAPI(title="Personal OS", version="0.1.0", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(router)
app.include_router(instancia_router)
app.include_router(gym_router)
app.include_router(gym_plan_router)
app.include_router(vault_router)
app.include_router(agenda_router)
app.include_router(monitor_router)
app.include_router(sessions_router)
app.include_router(conversaciones_router)
app.include_router(agents_router)
app.include_router(vcs_router)
app.include_router(approvals_router)
app.include_router(projects_router)
app.include_router(usage_router)
app.include_router(model_usage_router)
app.include_router(notifications.router)
app.include_router(actions.router)
app.include_router(memory.router)
app.include_router(gateway.router)
app.include_router(assistants.router)
app.include_router(home_module.router)
app.include_router(checkin_module.router)
app.include_router(finance_module.router)
app.include_router(personal_module.router)
app.include_router(ocio_module.router)
app.include_router(education_module.router)
app.include_router(calendar_module.router)
app.include_router(applications_module.router)
extensiones.cargar(app)  # módulos propios de esta instalación (app/privado/, no se publica)


@app.middleware("http")
async def rutas_antiguas(request: Request, call_next):
    """Las direcciones antiguas del panel (/gym/, /tasks/?t=approvals…) llevan a las nuevas."""
    if request.method in ("GET", "HEAD") and not request.url.path.startswith(("/api/", "/_next/")):
        destino = rutas_viejas.nueva(request.url.path, request.url.query)
        if destino:
            return RedirectResponse(destino, status_code=308)
    return await call_next(request)


@app.middleware("http")
async def modulos_apagados(request: Request, call_next):
    """La API de un módulo desactivado no existe (404), aunque la web vieja o un script la llamen."""
    mid = modules.modulo_de_ruta(request.url.path) if request.url.path.startswith("/api/v1/") else None
    if mid and not await asyncio.to_thread(modules.activo, mid):
        return JSONResponse({"detail": f"El módulo {modules.MODULES[mid].nombre} está desactivado"}, status_code=404)
    return await call_next(request)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.url.path.startswith("/api/"):
        hostagent.ACTOR.set(await asyncio.to_thread(actor_name, request.cookies.get(COOKIE)))
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(self), geolocation=()")
    if request.url.path.startswith("/_next/static/"):
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    else:
        resp.headers.setdefault("Cache-Control", "no-store")
    # El export estático de Next lleva scripts en línea (sin nonce posible): 'unsafe-inline' solo para eso.
    resp.headers.setdefault("Content-Security-Policy",
                            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                            "img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; frame-src 'self'; "
                            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'; "
                            "worker-src 'self'; manifest-src 'self'")
    return resp


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    # Nunca devolver trazas ni rutas internas al navegador
    return JSONResponse({"detail": "Error interno"}, status_code=500)


# Frontend compilado (apps/web/out). Va al final: /api tiene prioridad. CC_WEB_DIR solo para entornos de prueba.
WEB = Path(os.environ["CC_WEB_DIR"]) if os.environ.get("CC_WEB_DIR") else ROOT / "control-center/apps/web/out"
if WEB.is_dir():
    app.mount("/", StaticFiles(directory=WEB, html=True), name="web")

    @app.exception_handler(404)
    async def not_found(request: Request, exc):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": getattr(exc, "detail", "No encontrado")}, status_code=404)
        return FileResponse(WEB / "404.html", status_code=404)
