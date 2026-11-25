"""Descarga diaria de los movimientos del banco con Enable Banking (open banking PSD2, solo lectura).

Enable Banking da acceso gratis a tus propias cuentas (aplicación «restringida», uso personal). Tú registras la aplicación
en su panel y dejas su clave privada en secrets/<application id>.pem; el banco te pide permiso una vez y dura hasta 180 días.

Los movimientos se clasifican con las mismas reglas que el extracto CSV de Revolut (revolut.classify). La API no trae la
hora de inicio ni el saldo tras cada movimiento, así que no comparte identificador con el CSV: lo que ya entró por CSV se
reconoce por importe y fecha (±1 día) y no se duplica. De esas parejas se aprende cómo llama la API a cada comercio
(«Mp**carref Hospitalet» → «Carrefour»), para que las categorías que ya enseñaste sigan valiendo.

Lo pendiente no se apunta: se apunta cuando el banco lo confirma. El saldo declarado es el disponible más lo pendiente,
que es lo que suma lo confirmado. De momento solo la cuenta en euros: las divisas siguen entrando por CSV.
"""
import asyncio
import base64
import hashlib
import json
import logging
import os
import secrets as tokens
import sys
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import events
from ..config import ROOT, TZ_NAME
from ..db import get_db, session_scope
from ..models import BalanceAssertion, JournalEntry, Posting
from ..security import Principal, current_principal, require_admin
from . import finance as fin
from . import revolut as rv

sys.path.insert(0, str(ROOT / "collectors"))
import ajustes  # noqa: E402

log = logging.getLogger("cc.banco")
router = APIRouter(prefix="/api/v1/finance/banco", dependencies=[Depends(current_principal)])
API = "https://api.enablebanking.com"
CFG = "banco"
TZ = ZoneInfo(TZ_NAME)
HORA = 3                      # sincronización diaria a partir de las 3:00
INTENTOS = 3                  # al día, con una hora entre ellos (PSD2 limita las consultas sin ti delante)
PRIMERA_VEZ = 120             # días hacia atrás la primera vez: para casar con el CSV y aprender los nombres
SOLAPE = 10                   # días que se repasan en cada sincronización (lo que el banco confirma tarde)
AVISO_DIAS = 7                # avisar de que el permiso caduca
ACTOR = "banco"
TIPOS = {"CARD_PAYMENT": "Card Payment", "TRANSFER": "Transfer", "TOPUP": "Topup", "EXCHANGE": "Exchange", "CHARGE": "Charge",
         "CARD_REFUND": "Card Refund", "REFUND": "Refund", "ATM": "ATM"}


class BancoError(Exception):
    pass


# ---------- configuración (data/config/banco.json, permisos 600) ----------

def cfg() -> dict:
    return ajustes.propia(CFG)


def _guardar(**cambios) -> dict:
    d = cfg() | cambios
    ajustes.guardar(CFG, d)
    return d


def clave(app_id: str) -> Path:
    return Path(os.environ.get("POS_SECRETS_DIR", str(ROOT / "secrets"))) / f"{app_id}.pem"


def hoy() -> str:
    return datetime.now(TZ).date().isoformat()


# ---------- API de Enable Banking ----------

def _b64(b: bytes) -> bytes:
    return base64.urlsafe_b64encode(b).rstrip(b"=")


def _jwt(app_id: str) -> str:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    try:
        key = serialization.load_pem_private_key(clave(app_id).read_bytes(), None)
    except OSError:
        raise BancoError(f"Falta la clave privada: secrets/{app_id}.pem") from None
    now = int(time.time())
    parte = lambda d: _b64(json.dumps(d, separators=(",", ":")).encode())  # noqa: E731
    firmado = parte({"typ": "JWT", "alg": "RS256", "kid": app_id}) + b"." + parte(
        {"iss": "enablebanking.com", "aud": "api.enablebanking.com", "iat": now, "exp": now + 600})
    return (firmado + b"." + _b64(key.sign(firmado, padding.PKCS1v15(), hashes.SHA256()))).decode()


def _call(method: str, path: str, body: dict | None = None, params: dict | None = None) -> dict:
    app_id = cfg().get("app_id")
    if not app_id:
        raise BancoError("Falta el Application ID de Enable Banking")
    try:
        r = httpx.request(method, API + path, json=body, params=params, timeout=60,
                          headers={"Authorization": f"Bearer {_jwt(app_id)}"})
    except httpx.HTTPError as e:
        raise BancoError(f"Sin conexión con Enable Banking: {e}") from None
    if r.status_code >= 400:
        try:
            detalle = r.json().get("message") or r.json().get("detail") or r.text
        except ValueError:
            detalle = r.text
        raise BancoError(f"Enable Banking respondió {r.status_code}: {str(detalle)[:300]}")
    return r.json() if r.content else {}


def conectar(redirect_url: str) -> str:
    """Pide al banco un permiso nuevo. Devuelve la dirección donde lo apruebas; vuelve a redirect_url con un código."""
    c = cfg()
    aspsp = c.get("aspsp") or {"name": "Revolut", "country": "ES"}
    bancos = _call("GET", "/aspsps", params={"country": aspsp["country"]}).get("aspsps", [])
    b = next((x for x in bancos if x.get("name") == aspsp["name"]), None)
    if b is None:
        raise BancoError(f"{aspsp['name']} no aparece en Enable Banking para {aspsp['country']}")
    segundos = min(int(b.get("maximum_consent_validity") or 0) or 90 * 86400, 180 * 86400) - 3600
    hasta = (datetime.now(timezone.utc) + timedelta(seconds=segundos)).isoformat()
    state = tokens.token_urlsafe(16)
    r = _call("POST", "/auth", {"access": {"valid_until": hasta}, "aspsp": aspsp, "state": state,
                                "redirect_url": redirect_url, "psu_type": "personal"})
    _guardar(estado_auth=state)
    return r["url"]


def completar(code: str, state: str) -> dict:
    c = cfg()
    if not c.get("estado_auth") or not tokens.compare_digest(state, c["estado_auth"]):
        raise BancoError("Este enlace de vuelta no es de la última conexión que pediste. Vuelve a conectar desde Finanzas.")
    r = _call("POST", "/sessions", {"code": code})
    anterior = c.get("session_id")
    cuentas = [{"uid": a["uid"], "moneda": a.get("currency")} for a in r.get("accounts", [])]
    _guardar(session_id=r["session_id"], valid_until=(r.get("access") or {}).get("valid_until"), cuentas=cuentas,
             estado_auth=None, avisado=None, error=None)
    if anterior and anterior != r["session_id"]:
        try:
            _call("DELETE", f"/sessions/{anterior}")
        except BancoError:
            pass  # ya caducada: no pasa nada
    return estado()


def dias_restantes(c: dict | None = None) -> int | None:
    c = c if c is not None else cfg()
    if not c.get("valid_until"):
        return None
    fin_ = datetime.fromisoformat(c["valid_until"].replace("Z", "+00:00"))
    return (fin_ - datetime.now(timezone.utc)).days


def estado() -> dict:
    c = cfg()
    app_id = c.get("app_id") or ""
    return {"app_id": app_id, "clave": bool(app_id) and clave(app_id).is_file(), "banco": (c.get("aspsp") or {"name": "Revolut"})["name"],
            "conectado": bool(c.get("session_id")), "dias": dias_restantes(c), "valido_hasta": c.get("valid_until"),
            "ultima": c.get("ultima"), "error": c.get("error"), "desde": c.get("desde"), "alias": len(c.get("alias") or {})}


# ---------- importación ----------

def _signo(t: dict) -> Decimal:
    v = Decimal(str((t.get("transaction_amount") or {}).get("amount") or "0"))
    return -v if t.get("credit_debit_indicator") == "DBIT" else v


def _texto(t: dict) -> str:
    """Descripción como la del extracto: la línea de Bizum primero, el concepto después."""
    partes = [" ".join(str(x).split()) for x in t.get("remittance_information") or [] if str(x).strip()]
    if not partes:
        partes = [((t.get("creditor") if t.get("credit_debit_indicator") == "DBIT" else t.get("debtor")) or {}).get("name") or ""]
    partes.sort(key=lambda p: not p.lower().startswith("bizum"))
    d = " · ".join(dict.fromkeys(p for p in partes if p))
    return d[:-8] if d.lower().endswith(" pending") else d


def fila(t: dict, alias: dict[str, str]) -> dict:
    texto = _texto(t)
    codigo = (t.get("bank_transaction_code") or {}).get("code") or ""
    importe = _signo(t)
    tipo = TIPOS.get(codigo, codigo.title())
    if importe > 0 and codigo in ("TRANSFER", "TOPUP"):
        tipo = "Deposit"  # como en el extracto: así se reconocen nómina, Bizum y devoluciones
    return {"fecha": t["booking_date"], "valor": t.get("value_date") or t["booking_date"], "tipo": tipo, "codigo": codigo,
            "bruto": texto, "descripcion": alias.get(texto.lower(), texto), "importe": importe, "comision": Decimal(0)}


def external_id(t: dict) -> str:
    ref = t.get("entry_reference") or t.get("transaction_id")
    if ref:
        return f"eb:{ref}"[:160]
    return "eb:" + hashlib.sha256(f"{t.get('booking_date')}|{_texto(t)}|{_signo(t)}".encode()).hexdigest()[:32]


def _movimientos_banco(db: Session, prefijo: str, desde: str) -> list[dict]:
    """Asientos de la cuenta del banco con ese origen (revolut: = CSV, eb: = API): fecha, importe y descripción."""
    banco = fin.account(db, rv.BANK)
    q = (select(JournalEntry.id, JournalEntry.entry_date, JournalEntry.description, Posting.amount)
         .join(Posting, Posting.entry_id == JournalEntry.id)
         .where(Posting.account_id == banco.id, JournalEntry.external_id.like(f"{prefijo}%"), JournalEntry.entry_date >= desde,
                JournalEntry.reverses_id.is_(None)))
    return [{"id": i, "fecha": d, "descripcion": s, "importe": Decimal(str(a))} for i, d, s, a in db.execute(q)]


def _pareja(libres: list[dict], importe: Decimal, ini: str, fin_: str, centro: str) -> dict | None:
    a, b = date.fromisoformat(ini) - timedelta(days=1), date.fromisoformat(fin_) + timedelta(days=1)
    cands = [x for x in libres if x["importe"] == importe and a <= date.fromisoformat(x["fecha"]) <= b]
    if not cands:
        return None
    x = min(cands, key=lambda x: abs((date.fromisoformat(x["fecha"]) - date.fromisoformat(centro)).days))
    libres.remove(x)
    return x


def importar(db: Session, txs: list[dict], saldo_disponible: Decimal | None, desde: str, actor: str = ACTOR) -> dict:
    """Apunta lo confirmado que no esté ya (por la API o por un extracto CSV). `desde`: primer día de la ventana pedida."""
    rv.ensure_accounts(db)
    banco = fin.account(db, rv.BANK)
    c = cfg()
    alias: dict[str, str] = dict(c.get("alias") or {})
    corte = c.get("desde")
    if corte is None:  # primera vez: lo anterior al último extracto ya está apuntado
        corte = db.scalar(select(JournalEntry.entry_date).where(JournalEntry.external_id.like("revolut:%"))
                          .order_by(JournalEntry.entry_date.desc()).limit(1)) or "0000-00-00"
    existentes = set(db.scalars(select(JournalEntry.external_id).where(JournalEntry.external_id.like("eb:%"))))
    inicio = (date.fromisoformat(desde) - timedelta(days=2)).isoformat()
    libres = _movimientos_banco(db, "revolut:", inicio)
    rules = rv.learned(db)
    nuevos = dup = casados = revisar = anteriores = 0
    pendiente = Decimal(0)
    for t in sorted(txs, key=lambda t: (t.get("booking_date") or "", t.get("entry_reference") or "")):
        if t.get("status") != "BOOK":
            pendiente += _signo(t)
            continue
        f = fila(t, alias)
        if f["importe"] == 0:
            continue
        ext = external_id(t)
        if ext in existentes:
            dup += 1
            continue
        csv = _pareja(libres, f["importe"], f["fecha"], f["valor"], f["valor"])
        if csv is not None:
            casados += 1
            if f["codigo"] == "CARD_PAYMENT" and f["bruto"].lower() != csv["descripcion"].lower():
                alias[f["bruto"].lower()] = csv["descripcion"]
            continue
        if f["fecha"] < corte:
            anteriores += 1  # anterior al último extracto y sin pareja: el CSV manda
            continue
        f["descripcion"] = alias.get(f["bruto"].lower(), f["descripcion"])
        cuenta = rv.classify(f, rules)
        conocida = cuenta is not None
        contra = fin.account(db, cuenta) if conocida else fin.account(
            db, fin.SIN_CATEGORIZAR if f["importe"] < 0 else fin.INGRESO_SIN_CATEGORIZAR, "expense" if f["importe"] < 0 else "income")
        fin.post_entry(db, f["fecha"], f["descripcion"], [(banco.id, f["importe"], "EUR"), (contra.id, -f["importe"], "EUR")], actor,
                       status="posted" if conocida else "pending", external_id=ext)
        existentes.add(ext)
        nuevos += 1
        revisar += 0 if conocida else 1
    saldo = None
    if saldo_disponible is not None:
        saldo = saldo_disponible - pendiente  # el disponible ya resta lo pendiente, que aún no está apuntado
        dia = hoy()
        b = db.scalar(select(BalanceAssertion).where(BalanceAssertion.account_id == banco.id, BalanceAssertion.as_of == dia))
        if b is None:
            db.add(BalanceAssertion(account_id=banco.id, as_of=dia, amount=saldo, currency="EUR"))
        else:
            b.amount = saldo
        db.flush()
    _guardar(alias=alias, desde=corte)
    return {"nuevos": nuevos, "por_revisar": revisar, "duplicados": dup, "ya_en_csv": casados, "anteriores_sin_pareja": anteriores,
            "pendientes": fin.money(-pendiente) if pendiente < 0 else fin.money(pendiente), "saldo": fin.money(saldo) if saldo is not None else None}


def ya_por_api(fecha: str, importe: Decimal, libres: list[dict] | None) -> bool:
    """Para el importador CSV: ¿este movimiento ya entró por la API? Consume la pareja para no casar dos veces."""
    if libres is None:
        return False
    return _pareja(libres, importe, fecha, fecha, fecha) is not None


def libres_api(db: Session, desde: str) -> list[dict] | None:
    """Movimientos de la API desde esa fecha, para que el importador CSV no los duplique. None si nunca se ha usado."""
    if not db.scalar(select(JournalEntry.id).where(JournalEntry.external_id.like("eb:%")).limit(1)):
        return None
    return _movimientos_banco(db, "eb:", (date.fromisoformat(desde) - timedelta(days=2)).isoformat())


def _descargar(uid: str, desde: str) -> list[dict]:
    txs, key = [], None
    for _ in range(100):
        params = {"date_from": desde} | ({"continuation_key": key} if key else {})
        r = _call("GET", f"/accounts/{uid}/transactions", params=params)
        txs += r.get("transactions") or []
        key = r.get("continuation_key")
        if not key:
            break
    return txs


def sincronizar(db: Session, actor: str = ACTOR) -> dict:
    c = cfg()
    if not c.get("session_id"):
        raise BancoError("El banco no está conectado")
    d = dias_restantes(c)
    if d is not None and d < 0:
        raise BancoError("El permiso del banco ha caducado: vuelve a conectar desde Finanzas")
    eur = next((a for a in c.get("cuentas") or [] if a.get("moneda") == "EUR"), None)
    if eur is None:
        raise BancoError("La conexión no tiene ninguna cuenta en euros")
    ultima = (c.get("ultima") or {}).get("fecha")
    if ultima and c.get("desde"):
        desde = (date.fromisoformat(ultima) - timedelta(days=SOLAPE)).isoformat()
    else:
        desde = (datetime.now(TZ).date() - timedelta(days=PRIMERA_VEZ)).isoformat()
    txs = _descargar(eur["uid"], desde)
    saldos = _call("GET", f"/accounts/{eur['uid']}/balances").get("balances") or []
    preferido = next((s for s in saldos if s.get("balance_type") in ("ITAV", "CLAV", "ITBD", "CLBD")), saldos[0] if saldos else None)
    disponible = Decimal(str(preferido["balance_amount"]["amount"])) if preferido else None
    r = importar(db, txs, disponible, desde, actor)
    _guardar(ultima={"fecha": hoy(), "hora": datetime.now(TZ).strftime("%H:%M")} | r, error=None, intentos=None)
    events.audit(db, actor, "finance.banco.sync", c.get("aspsp", {}).get("name", "Revolut"), nuevos=r["nuevos"], por_revisar=r["por_revisar"])
    return r


# ---------- todos los días a las 3:00 ----------

_ultimo_repaso = 0.0


def _avisar(nivel: str, titulo: str, cuerpo: str) -> None:
    from ..core import notifications
    notifications.crear(nivel, titulo, cuerpo, url="/finanzas/", source="banco")  # sin push: suele ser de madrugada


def toca(c: dict, now: datetime) -> bool:
    local = now.astimezone(TZ)
    if not c.get("session_id") or local.hour < HORA:
        return False
    if (c.get("ultima") or {}).get("fecha") == local.date().isoformat():
        return False
    i = c.get("intentos") or {}
    if i.get("fecha") == local.date().isoformat():
        return i.get("n", 0) < INTENTOS and time.time() - i.get("ts", 0) >= 3600
    return True


def _diario_sync(now: datetime) -> None:
    from ..core import modules
    if not modules.activo("finanzas"):
        return
    c = cfg()
    d = dias_restantes(c)
    dia = now.astimezone(TZ).date()
    avisado = c.get("avisado")
    if c.get("session_id") and d is not None and d <= AVISO_DIAS and (not avisado or (dia - date.fromisoformat(avisado)).days >= 3):
        _guardar(avisado=dia.isoformat())
        motivo = "El permiso para leer tu banco ha caducado." if d < 0 else f"El permiso para leer tu banco caduca en {d} días."
        _avisar("warning", "Reconecta el banco en Finanzas", f"{motivo} Entra en Finanzas → Herramientas y pulsa «Reconectar».")
    if not toca(c, now):
        return
    hoy_ = now.astimezone(TZ).date().isoformat()
    previo = c.get("intentos") or {}
    n = (previo.get("n", 0) if previo.get("fecha") == hoy_ else 0) + 1
    _guardar(intentos={"fecha": hoy_, "n": n, "ts": time.time()})
    try:
        with session_scope() as db:
            r = sincronizar(db)
        log.info("banco: %s", r)
    except Exception as e:  # noqa: BLE001
        log.warning("banco: %s", e)
        _guardar(error={"fecha": hoy_, "hora": now.astimezone(TZ).strftime("%H:%M"), "mensaje": str(e)[:300]})
        if n >= INTENTOS:
            _avisar("warning", "No se pudieron descargar los movimientos del banco", str(e)[:300])


async def diario(now: datetime | None = None) -> None:
    """Lo llama el bucle de avisos cada pocos segundos; mira como mucho una vez por minuto."""
    global _ultimo_repaso
    if time.monotonic() - _ultimo_repaso < 60:
        return
    _ultimo_repaso = time.monotonic()
    await asyncio.to_thread(_diario_sync, now or datetime.now(timezone.utc))


# ---------- API ----------

class AppIn(BaseModel):
    app_id: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class ConectarIn(BaseModel):
    redirect_url: str = Field(max_length=300, pattern=r"^https?://[^\s]+/finanzas/banco$")


class VueltaIn(BaseModel):
    code: str = Field(min_length=8, max_length=200)
    state: str = Field(min_length=8, max_length=100)


def _http(fn, *a):
    try:
        return fn(*a)
    except BancoError as e:
        raise HTTPException(502, str(e)) from None


@router.get("")
def get_estado():
    return estado()


@router.post("/app")
def set_app(body: AppIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    _guardar(app_id=body.app_id)
    events.audit(db, p.name, "finance.banco.app", body.app_id)
    return estado()


@router.post("/conectar", dependencies=[Depends(require_admin)])
def post_conectar(body: ConectarIn):
    return {"url": _http(conectar, body.redirect_url)}


@router.post("/vuelta")
def post_vuelta(body: VueltaIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    r = _http(completar, body.code, body.state)
    events.audit(db, p.name, "finance.banco.conectar", r["banco"])
    return r


@router.post("/sincronizar")
def post_sincronizar(p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        return sincronizar(db, p.name) | {"estado": estado()}
    except BancoError as e:
        _guardar(error={"fecha": hoy(), "hora": datetime.now(TZ).strftime("%H:%M"), "mensaje": str(e)[:300]})
        raise HTTPException(502, str(e)) from None
