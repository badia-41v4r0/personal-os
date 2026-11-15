"""Candidaturas con agente: CV y perfil en la base, solicitudes preparadas por un agente y enviadas solo con aprobación.

Flujo de una solicitud (`ApplicationRun`):
  en_cola → preparando (ordenador `aplicaciones` + agente `solicitud`) → verificando → listo_para_revisar
  → (el usuario aprueba `candidatura.aplicar`) → enviada | fallida, o abortada / rechazada / caducada.

Garantías (plan `compiled-stirring-cocoa`, fase 4):
- El agente no tiene terminal, ratón ni teclado: solo lee la página y rellena campos por referencia (Host Agent).
- El ordenador no tiene red: sale por un proxy con los dominios de esa solicitud, que el agente no puede cambiar.
- Lo que el usuario aprueba son los valores **leídos del navegador** al acabar el agente (no lo que dice el agente),
  la huella del CV, el dominio, el botón y la captura. `candidatura.aplicar` es de nivel 3 fijo.
- El botón lo pulsa el Host Agent tras la aprobación, y solo si el formulario sigue exactamente como se aprobó.
- Lo de la lista «nunca rellenar» no se rellena: si aparece con valor en la revisión, la solicitud no se ofrece.
"""
import asyncio
import base64
import hashlib
import logging
import re
import subprocess
import uuid
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import archivos, events
from ..adapters import hostagent
from ..config import INSTANCE, ROOT, get_settings
from ..core import actions, memory
from ..db import get_db, session_scope, utcnow
from ..models import (Action, AgentRun, ApplicantProfile, ApplicationRun, CareerDocument, ChatSession, JobApplication,
                      Message, VirtualComputer)
from ..security import Principal, current_principal, require_admin
from . import mirror

log = logging.getLogger("cc.applications")
router = APIRouter(prefix="/api/v1/me/career", dependencies=[Depends(current_principal)])

CARPETA = "Carrera"
EXTENSIONES = {".pdf", ".docx", ".doc", ".odt", ".txt", ".md"}
ACTIVOS = ("en_cola", "preparando", "verificando", "listo_para_revisar", "aprobada")
FINALES = ("enviada", "fallida", "abortada", "rechazada", "caducada")
NUNCA = ["DNI", "NIE", "pasaporte", "número de la Seguridad Social", "IBAN o cuenta bancaria", "tarjeta de crédito",
         "salud o discapacidad", "religión o creencias", "orientación sexual", "origen étnico", "antecedentes penales",
         "contraseñas"]
# Recursos estáticos que casi todas las webs de empleo necesitan para dibujarse (no reciben datos del formulario)
CDN = ("gstatic.com", "googleapis.com", "cdnjs.cloudflare.com", "jsdelivr.net", "unpkg.com", "cloudfront.net")
DOS_NIVELES = ("co.uk", "com.es", "com.mx", "com.ar", "com.br", "co.jp", "com.au")
AGENTE = ROOT / "control-center/agents/solicitud.md"
TOOLS: tuple[str, ...] = ()
CAPS = ("candidatura.preparada", "candidatura.abortar")
_tasks: set[asyncio.Task] = set()


# ---------- perfil ----------

class Enlace(BaseModel):
    tipo: str = Field(max_length=40)
    url: str = Field(max_length=500)


class Idioma(BaseModel):
    idioma: str = Field(max_length=40)
    nivel: str = Field(max_length=40)


class Respuesta(BaseModel):
    pregunta: str = Field(max_length=300)
    respuesta: str = Field(max_length=2000)
    verificada: bool = False


class PerfilIn(BaseModel):
    nombre: str = Field("", max_length=120)
    email: str = Field("", max_length=200)
    telefono: str = Field("", max_length=40)
    ciudad: str = Field("", max_length=120)
    enlaces: list[Enlace] = Field(default_factory=list, max_length=10)
    permiso_trabajo: str = Field("", max_length=200)
    disponibilidad: str = Field("", max_length=200)
    pretension: str = Field("", max_length=200)
    idiomas: list[Idioma] = Field(default_factory=list, max_length=10)
    respuestas: list[Respuesta] = Field(default_factory=list, max_length=40)
    nunca_rellenar: list[str] = Field(default_factory=lambda: list(NUNCA), max_length=40)


def perfil(db: Session) -> dict:
    p = db.get(ApplicantProfile, 1)
    return PerfilIn(**(p.data if p else {})).model_dump()


@router.get("/profile")
def get_profile(db: Session = Depends(get_db)):
    return perfil(db)


@router.put("/profile")
def put_profile(body: PerfilIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    data = body.model_dump()
    data["nunca_rellenar"] = sorted({*NUNCA, *(x.strip() for x in body.nunca_rellenar if x.strip())})  # lo básico no se quita
    row = db.get(ApplicantProfile, 1) or ApplicantProfile(id=1)
    row.data, row.updated_at = data, utcnow()
    db.add(row)
    events.audit(db, p.name, "career.profile.update", "perfil")
    return data


# ---------- documentos ----------

def _carpeta() -> Path:
    d = archivos.root() / CARPETA
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    return d


def _texto(f: Path) -> str:
    if f.suffix.lower() in (".txt", ".md"):
        return f.read_text(encoding="utf-8", errors="replace")[:100_000]
    if f.suffix.lower() == ".pdf":
        try:
            r = subprocess.run(["pdftotext", "-layout", "-q", str(f), "-"], capture_output=True, timeout=30)
            return r.stdout.decode("utf-8", "replace")[:100_000]
        except (OSError, subprocess.TimeoutExpired):
            return ""
    return ""


def _doc(d: CareerDocument) -> dict:
    return {"id": d.id, "nombre": d.name, "tipo": d.kind, "sha256": d.sha256, "idioma": d.language, "tamano": d.size,
            "activo": d.active, "texto": bool(d.text), "creado": d.created_at.isoformat() + "Z"}


@router.get("/documents")
def documents(db: Session = Depends(get_db)):
    return [_doc(d) for d in db.scalars(select(CareerDocument).order_by(CareerDocument.created_at.desc()))]


@router.post("/documents")
async def upload(request: Request, nombre: str, tipo: str = "cv", idioma: str = "es", p: Principal = Depends(require_admin)):
    if tipo not in ("cv", "carta", "otro") or not re.fullmatch(r"[a-z]{2}", idioma):
        raise HTTPException(422, "Tipo (cv, carta, otro) o idioma no válidos")
    if Path(nombre).suffix.lower() not in EXTENSIONES:
        raise HTTPException(422, "Sube un PDF, Word, ODT o texto")
    f, size = await archivos.receive(request, _carpeta(), nombre)
    sha = hashlib.sha256(f.read_bytes()).hexdigest()
    with session_scope() as db:
        ya = db.scalar(select(CareerDocument).where(CareerDocument.sha256 == sha))
        if ya is not None:
            f.unlink(missing_ok=True)  # el mismo archivo ya estaba: no se duplica
            ya.active = True
            return _doc(ya) | {"repetido": True}
        d = CareerDocument(name=f.name, kind=tipo, sha256=sha, path=f.relative_to(archivos.root()).as_posix(), language=idioma,
                           size=size, text=_texto(f))
        db.add(d)
        db.flush()
        events.audit(db, p.name, "career.document.upload", d.name, sha=sha[:16])
        return _doc(d)


@router.post("/documents/{did}/archive")
def archive(did: int, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    d = db.get(CareerDocument, did)
    if d is None:
        raise HTTPException(404, "No existe")
    d.active = False  # el archivo se queda: las solicitudes enviadas lo citan por su huella
    events.audit(db, p.name, "career.document.archive", d.name)
    return _doc(d)


@router.get("/documents/{did}/file")
def document_file(did: int, db: Session = Depends(get_db)):
    d = db.get(CareerDocument, did)
    if d is None:
        raise HTTPException(404, "No existe")
    f = archivos.root() / d.path
    if not f.is_file() or f.is_symlink():
        raise HTTPException(410, "El archivo ya no está en archivos/Carrera")
    return FileResponse(f, filename=d.name)


# ---------- solicitudes ----------

def dominios(url: str) -> list[str]:
    """Primero el dominio registrable de la URL (el de la empresa o el del ATS que aloja la oferta); luego los CDN."""
    host = (urlparse(url).hostname or "").lower().strip(".")
    partes = host.split(".")
    n = 3 if ".".join(partes[-2:]) in DOS_NIVELES else 2
    principal = ".".join(partes[-n:])
    return [principal, *(c for c in CDN if c != principal)]


# Palabras que delatan un campo de la lista «nunca rellenar» (en español e inglés), además de lo que añada el usuario
SENSIBLES = ("dni", "nie", "pasaporte", "passport", "seguridad social", "social security", "ssn", "iban", "cuenta bancaria",
             "bank account", "tarjeta", "card number", "cvv", "salud", "health", "discapacidad", "disability", "religi",
             "orientación sexual", "sexual orientation", "étnic", "ethnic", "antecedentes", "criminal", "contraseña", "password")


def sensible(texto: str, nunca: list[str]) -> bool:
    t = f" {texto.lower()} "
    propias = [x.lower() for x in nunca if x not in NUNCA]
    # Las siglas cortas (dni, nie, ssn…) como palabra entera; las raíces largas (religi…, étnic…) como prefijo
    return any(re.search(rf"(?<![a-záéíóúñ]){re.escape(k)}" + (r"(?![a-záéíóúñ])" if len(k) <= 4 else ""), t) for k in SENSIBLES) \
        or any(x and x in t for x in propias)


def _run_out(r: ApplicationRun, db: Session) -> dict:
    a = db.get(Action, r.action_id) if r.action_id else None
    app = db.get(JobApplication, r.application_id)
    return {"id": r.id, "candidatura": r.application_id, "empresa": app.company if app else "", "puesto": app.role if app else "",
            "url": r.url, "dominios": r.domains, "estado": r.status, "documento": r.document_sha, "error": r.error,
            "revision": r.payload.get("revision"), "notas": r.payload.get("notas", ""), "resultado": r.payload.get("resultado"),
            "capturas": len(r.screenshots), "accion": {"id": a.id, "estado": a.status, "hash": a.payload_hash} if a else None,
            "creada": r.created_at.isoformat() + "Z", "actualizada": r.updated_at.isoformat() + "Z"}


def _set(r: ApplicationRun, estado: str, error: str = "") -> None:
    r.status, r.updated_at = estado, utcnow()
    if error:
        r.error = error[:1000]


def _sincronizar(db: Session, r: ApplicationRun) -> None:
    """Si el usuario rechazó o dejó caducar la aprobación, la solicitud se cierra y su ordenador se quita."""
    if r.status != "listo_para_revisar" or not r.action_id:
        return
    a = db.get(Action, r.action_id)
    if a is not None and a.status in ("rejected", "expired"):
        _set(r, "rechazada" if a.status == "rejected" else "caducada")
        _quitar_ordenador(db, r)


class SolicitudIn(BaseModel):
    url: str = Field(min_length=10, max_length=2000)
    documento: int


@router.get("/runs")
def runs(candidatura: int | None = None, db: Session = Depends(get_db)):
    q = select(ApplicationRun).order_by(ApplicationRun.created_at.desc()).limit(50)
    if candidatura is not None:
        q = q.where(ApplicationRun.application_id == candidatura)
    out = []
    for r in db.scalars(q):
        _sincronizar(db, r)
        out.append(_run_out(r, db))
    return out


@router.get("/runs/{rid}")
def run(rid: str, db: Session = Depends(get_db)):
    r = db.get(ApplicationRun, rid)
    if r is None:
        raise HTTPException(404, "No existe")
    _sincronizar(db, r)
    return _run_out(r, db)


@router.get("/runs/{rid}/screenshot/{n}")
def screenshot(rid: str, n: int, db: Session = Depends(get_db)):
    r = db.get(ApplicationRun, rid)
    if r is None or not 0 <= n < len(r.screenshots):
        raise HTTPException(404, "No existe")
    f = get_settings().data_dir / "solicitudes" / rid / f"{n}.png"
    if not f.is_file():
        raise HTTPException(410, "La captura ya no está")
    return Response(f.read_bytes(), media_type="image/png")


@router.post("/applications/{aid}/runs")
def crear(aid: int, body: SolicitudIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    app = db.get(JobApplication, aid)
    if app is None:
        raise HTTPException(404, "Esa candidatura no existe")
    u = urlparse(body.url)
    if u.scheme != "https" or not u.hostname or "@" in u.netloc:
        raise HTTPException(422, "La URL de la oferta tiene que empezar por https://")
    doc = db.get(CareerDocument, body.documento)
    if doc is None or not doc.active:
        raise HTTPException(422, "Elige un CV activo")
    if db.scalar(select(ApplicationRun.id).where(ApplicationRun.status.in_(ACTIVOS))):
        raise HTTPException(409, "Ya hay una solicitud en marcha: termina o descarta esa antes")
    r = ApplicationRun(id=str(uuid.uuid4()), application_id=aid, url=body.url, domains=dominios(body.url), status="en_cola",
                       document_sha=doc.sha256, payload={}, screenshots=[])
    db.add(r)
    if not app.link:
        app.link = body.url[:500]
    events.audit(db, p.name, "career.run.create", r.id, candidatura=aid, dominio=r.domains[0])
    db.flush()
    rid = r.id
    _lanzar(rid)
    return _run_out(r, db)


def _lanzar(rid: str) -> None:
    def start() -> None:
        t = asyncio.create_task(preparar(rid))
        _tasks.add(t)
        t.add_done_callback(_tasks.discard)
    loop = events.loop()
    if loop is not None:
        loop.call_soon_threadsafe(start)


@router.post("/runs/{rid}/abort")
def abortar_desde_panel(rid: str, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    r = db.get(ApplicationRun, rid)
    if r is None:
        raise HTTPException(404, "No existe")
    if r.status not in ACTIVOS:
        raise HTTPException(409, f"Ya está {r.status}")
    if r.action_id:
        a = db.get(Action, r.action_id)
        if a is not None and a.status == "pending":
            a.status, a.finished_at = "rejected", utcnow()
    _set(r, "abortada", "Descartada desde el panel")
    _quitar_ordenador(db, r)
    events.audit(db, p.name, "career.run.abort", rid)
    return _run_out(r, db)


def _quitar_ordenador(db: Session, r: ApplicationRun) -> None:
    if not r.vc_id:
        return
    try:
        hostagent.call_sync(f"/v1/vc/{r.vc_id}/lifecycle/remove", method="POST", timeout=60)
    except Exception as e:  # noqa: BLE001  la política de caducidad lo quitará igualmente
        log.warning("no se pudo quitar el ordenador %s: %s", r.vc_id, e)
    v = db.get(VirtualComputer, r.vc_id)
    if v is not None:
        v.status = "removed"


def _prompt(r: ApplicationRun, app: JobApplication, doc: CareerDocument, perfil_: dict) -> str:
    import json
    return (f"Orden de solicitud `{r.id}`.\n\nPuesto: {app.role} en {app.company}.\nURL: {r.url}\n"
            f"Documento para adjuntar: {doc.name} (huella `{doc.sha256}`).\n\n"
            "Perfil del usuario (datos que puedes usar; lo de `nunca_rellenar` no se rellena nunca):\n"
            f"```json\n{json.dumps(perfil_, ensure_ascii=False, indent=1)}\n```\n\n"
            f"Texto del CV (para responder preguntas sobre experiencia, sin inventar):\n```\n{doc.text[:12000]}\n```")


async def preparar(rid: str) -> None:
    """Crea el ordenador de la solicitud, lanza al agente y, si deja el formulario listo, pide la aprobación."""
    from .. import sessions
    with session_scope() as db:
        r = db.get(ApplicationRun, rid)
        app, doc = db.get(JobApplication, r.application_id), db.scalar(select(CareerDocument).where(CareerDocument.sha256 == r.document_sha))
        _set(r, "preparando")
        vid, sid, turno = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
        texto, dominios_ = _prompt(r, app, doc, perfil(db)), list(r.domains)
        empresa = app.company
    try:
        await hostagent.call("/v1/vc/create", method="POST", timeout=180,
                             json={"id": vid, "profile": "aplicaciones", "cpus": 1, "memory_mb": 1536, "disk_mb": 1024,
                                   "owner": "solicitud", "egress_allow": dominios_})
    except Exception as e:  # noqa: BLE001
        with session_scope() as db:
            _set(db.get(ApplicationRun, rid), "fallida", f"No se pudo crear el ordenador: {getattr(e, 'detail', e)}")
        return
    cuerpo = re.sub(r"\A---\n.*?\n---\n", "", AGENTE.read_text(encoding="utf-8"), flags=re.S).strip()
    with session_scope() as db:
        r = db.get(ApplicationRun, rid)
        r.vc_id, r.session_id = vid, sid
        db.add(VirtualComputer(id=vid, name=f"Solicitud · {empresa}"[:64], profile="aplicaciones", owner_agent="solicitud",
                               persistence="ttl", expires_at=utcnow() + timedelta(hours=26), internet=False, status="running",
                               limits={"cpus": 1, "memory_mb": 1536, "disk_mb": 1024, "dominios": dominios_}, created_by="sistema",
                               container_id=f"{INSTANCE}-vc-{vid[:8]}"))
        db.add(ChatSession(id=sid, kind="solicitud", name=f"Solicitud · {empresa}"[:120], workdir=f"data/sesiones/{sid}/trabajo", model="sonnet",
                           permissions={"level": "read", "internet": False, "vault": False, "minutes": 20, "subagents": False,
                                        "vc": {"enabled": True, "profile": "aplicaciones", "vc_id": vid, "owner": "solicitud", "docs": [r.document_sha]},
                                        "system_prompt": cuerpo, "pos": {"agent": "solicitud", "tools": list(TOOLS), "capabilities": list(CAPS)}}))
        db.flush()  # la conversación antes que su turno
        db.add(AgentRun(id=turno, session_id=sid, agent_id=None, channel="web", status="queued"))
        db.add(Message(session_id=sid, role="user", channel="web", content=texto, run_id=turno))
        events.audit(db, "sistema", "career.run.prepare", rid, vc=vid, session=sid)
    try:
        await sessions._run(sid, turno, texto)
    except Exception as e:  # noqa: BLE001
        log.warning("el turno de la solicitud %s falló: %s", rid, e)
    await asyncio.to_thread(revisar, rid)


def revisar(rid: str) -> None:
    """Tras el turno: lee el formulario del navegador (no lo que dice el agente) y pide la aprobación."""
    with session_scope() as db:
        r = db.get(ApplicationRun, rid)
        if r.status in ("abortada",):
            _quitar_ordenador(db, r)
            return
        if r.status != "verificando":
            turno = db.scalar(select(AgentRun).where(AgentRun.session_id == r.session_id).order_by(AgentRun.created_at.desc()))
            _set(r, "fallida", "El agente no dejó el formulario listo" + (f": {turno.result[-400:]}" if turno and turno.result else ""))
            _quitar_ordenador(db, r)
            return
        vc, boton, rellenados, notas = r.vc_id, r.payload.get("boton"), r.payload.get("rellenados") or [], r.payload.get("notas", "")
        nunca = perfil(db)["nunca_rellenar"]
        doc = db.scalar(select(CareerDocument).where(CareerDocument.sha256 == r.document_sha))
    try:
        estado = hostagent.call_sync(f"/v1/vc/{vc}/form/fields", method="POST", timeout=120)
        shot = hostagent.call_sync(f"/v1/vc/{vc}/screenshot", timeout=30)
    except Exception as e:  # noqa: BLE001
        with session_scope() as db:
            r = db.get(ApplicationRun, rid)
            _set(r, "fallida", f"No pude leer el formulario: {getattr(e, 'detail', e)}")
            _quitar_ordenador(db, r)
        return
    campos, botones = estado.get("campos") or [], {b["ref"]: b for b in estado.get("botones") or []}
    problema = ""
    if estado.get("bloqueos"):
        problema = f"La página pide {', '.join(estado['bloqueos'])}: pasa a manual"
    elif boton not in botones:
        problema = "El botón de envío que indicó el agente no está en la página"
    else:
        host = (urlparse(estado.get("url", "")).hostname or "").lower()
        if not (host == r.domains[0] or host.endswith("." + r.domains[0])):
            problema = "El formulario está en un dominio que no es el de la solicitud"
    sensibles = [c for c in campos if c.get("valor") not in ("", False, [], None)
                 and sensible(f"{c.get('etiqueta', '')} {c.get('nombre', '')}", nunca)]
    if not problema and sensibles:
        problema = "Hay campos de la lista «nunca rellenar» con valor: " + ", ".join(c.get("etiqueta") or c["ref"] for c in sensibles[:5])
    with session_scope() as db:
        r = db.get(ApplicationRun, rid)
        if problema:
            _set(r, "fallida", problema)
            _quitar_ordenador(db, r)
            return
        d = get_settings().data_dir / "solicitudes" / rid
        d.mkdir(mode=0o700, parents=True, exist_ok=True)
        png = base64.b64decode(shot.get("png_base64", ""))
        (d / "0.png").write_bytes(png)
        capturas = [hashlib.sha256(png).hexdigest()]
        r.screenshots = capturas
        esperado = {c["ref"]: c.get("valor") for c in campos}
        revision = {"url": estado.get("url"), "titulo": estado.get("titulo"),
                    "campos": [{"ref": c["ref"], "etiqueta": c.get("etiqueta") or c.get("nombre") or c["ref"], "tipo": c.get("tipo"),
                                "obligatorio": bool(c.get("obligatorio")), "valor": c.get("valor"), "rellenado_por_el_agente": c["ref"] in rellenados}
                               for c in campos],
                    "boton": {"ref": boton, "texto": botones[boton].get("texto", "")}}
        app = db.get(JobApplication, r.application_id)
        payload = {"solicitud": rid, "empresa": app.company, "puesto": app.role, "url": revision["url"], "dominio": r.domains[0],
                   "boton": boton, "esperado": esperado, "documento": {"sha256": r.document_sha, "nombre": doc.name if doc else ""},
                   "capturas": capturas}
        r.payload = dict(r.payload) | {"revision": revision, "notas": notas}
        _set(r, "listo_para_revisar")
    a = actions.request("candidatura.aplicar", payload, actor="solicitud", actor_type="agent",
                        reason=f"Solicitud preparada para {payload['empresa']}: revisa campos, CV y captura")
    with session_scope() as db:
        r = db.get(ApplicationRun, rid)
        r.action_id = a["id"]
        if a["status"] != "pending":  # nunca debería pasar (nivel 3 fijo): si pasa, no se envía nada
            _set(r, "fallida", f"La aprobación no quedó pendiente ({a['status']})")
            _quitar_ordenador(db, r)
        events.publish("career.updated", {"run": rid, "estado": r.status}, db=db)


# ---------- capacidades ----------

def _run_activa(p: dict, db: Session, estado: str = "preparando") -> ApplicationRun:
    r = db.get(ApplicationRun, str(p.get("solicitud", "")))
    if r is None or r.status != estado:
        raise ValueError("Esa solicitud no está en preparación")
    return r


def preparada(p: dict, db: Session) -> dict:
    """El agente dice que lo ha dejado listo. No se fía de sus valores: `revisar` los lee del navegador."""
    r = _run_activa(p, db)
    campos = [str(x) for x in (p.get("campos") or [])][:80]
    boton = str(p.get("boton", ""))
    if not re.fullmatch(r"b\d{1,4}", boton) or not all(re.fullmatch(r"f\d{1,4}", c) for c in campos):
        raise ValueError("campos son referencias f1, f2… y boton una b1, b2…")
    r.payload = dict(r.payload) | {"rellenados": campos, "boton": boton, "notas": str(p.get("notas", ""))[:3000]}
    _set(r, "verificando")
    return {"ok": True, "siguiente": "el usuario lo revisará en el panel; no hagas nada más."}


def abortar(p: dict, db: Session) -> dict:
    r = _run_activa(p, db)
    _set(r, "abortada", str(p.get("motivo", "Sin motivo"))[:1000])
    return {"ok": True}


def aplicar(p: dict, db: Session) -> dict:
    """Tras la aprobación: el Host Agent pulsa el botón solo si el formulario sigue exactamente como se aprobó."""
    r = _run_activa(p, db, "listo_para_revisar")
    rid = r.id

    def fallo(msg: str):
        # La transacción de la acción se deshace al fallar: el estado se guarda aparte
        with session_scope() as s2:
            r2 = s2.get(ApplicationRun, rid)
            _set(r2, "fallida", msg)
            _quitar_ordenador(s2, r2)
        raise RuntimeError(msg)
    try:
        res = hostagent.call_sync(f"/v1/vc/{r.vc_id}/form/submit", method="POST", timeout=150,
                                  json={"boton": p["boton"], "esperado": p["esperado"]})
    except Exception as e:  # noqa: BLE001
        fallo(f"No se pudo enviar: {getattr(e, 'detail', e)}")
    if not res.get("enviado"):
        fallo(f"No se ha enviado nada: {res.get('motivo', 'el formulario cambió')}")
    try:
        shot = hostagent.call_sync(f"/v1/vc/{r.vc_id}/screenshot", timeout=30)
        png = base64.b64decode(shot.get("png_base64", ""))
        f = get_settings().data_dir / "solicitudes" / r.id / f"{len(r.screenshots)}.png"
        f.write_bytes(png)
        r.screenshots = [*r.screenshots, hashlib.sha256(png).hexdigest()]
    except Exception:  # noqa: BLE001  la captura del después es un extra
        pass
    r.payload = dict(r.payload) | {"resultado": {"url": res.get("url"), "titulo": res.get("titulo"), "texto": str(res.get("texto", ""))[:2000]}}
    _set(r, "enviada")
    app = db.get(JobApplication, r.application_id)
    app.status, app.follow_up, app.updated_at = "aplicado", (date.today() + timedelta(days=7)).isoformat(), utcnow()
    app.next_step = "Esperar respuesta (solicitud enviada desde el panel)"
    memory.log_event(db, "career", "application.sent", f"{app.company}: {app.role}")
    mirror.export_jobs(db)
    _quitar_ordenador(db, r)
    return {"enviada": True, "url": res.get("url")}


for cap in (
    actions.Capability("candidatura.preparada", 1, preparada, "Dejar una solicitud lista para revisar",
                       summary=lambda p: f"Solicitud {str(p.get('solicitud'))[:8]} lista"),
    actions.Capability("candidatura.abortar", 1, abortar, "Abortar una solicitud (pasa a manual)",
                       summary=lambda p: f"Solicitud {str(p.get('solicitud'))[:8]}: {str(p.get('motivo'))[:80]}"),
    actions.Capability("candidatura.aplicar", 3, aplicar, "Enviar una candidatura",
                       summary=lambda p: f"Enviar candidatura a {p.get('empresa')} ({p.get('puesto')}) en {p.get('dominio')}"),
):
    actions.register(cap)
actions.FIXED_LEVEL.add("candidatura.aplicar")
