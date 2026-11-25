"""Descarga diaria de los movimientos del banco con Enable Banking (open banking PSD2, solo lectura).

Enable Banking da acceso gratis a tus propias cuentas (aplicación «restringida», uso personal). Registras la aplicación en
su panel y subes desde Finanzas su Application ID y su clave privada (la guarda el Host Agent en secrets/<id>.pem, 600);
el banco te pide permiso una vez y dura hasta 180 días. Vale cualquier banco que Enable Banking tenga en tu país.

Cada cuenta en euros va a su cuenta del ledger (asset:<banco>; Revolut, a la de siempre: asset:revolut). Revolut se
clasifica con las reglas de su extracto (revolut.classify); los demás bancos, con las reglas genéricas (las que enseñas,
comercios, Bizum, nómina y transferencias a tu nombre).

La API no trae la hora de inicio ni el saldo tras cada movimiento, así que no comparte identificador con el CSV: lo que
ya entró por extracto se reconoce por importe y fecha (±1 día) y no se duplica. De esas parejas se aprende cómo llama la
API a cada comercio («Mp**carref Hospitalet» → «Carrefour»), para que las categorías que ya enseñaste sigan valiendo.

Lo pendiente no se apunta: se apunta cuando el banco lo confirma. Si el banco da el saldo contable se declara ese; si
solo da el disponible, el disponible más lo pendiente. De momento solo cuentas en euros: las divisas, por CSV.
"""
import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import secrets as tokens
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import events
from ..config import ROOT, TZ_NAME
from ..db import get_db, session_scope
from ..models import JournalEntry, LedgerAccount, Posting
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
RUTA_VUELTA = "/finanzas/banco"
APP_ID_RE = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
PAISES = ("ES", "PT", "FR", "DE", "IT", "NL", "BE", "AT", "IE", "LT", "LV", "EE", "FI", "SE", "DK", "NO", "PL")
TIPOS = {"CARD_PAYMENT": "Card Payment", "TRANSFER": "Transfer", "TOPUP": "Topup", "EXCHANGE": "Exchange", "CHARGE": "Charge",
         "CARD_REFUND": "Card Refund", "REFUND": "Refund", "ATM": "ATM"}
CONTABLE = ("CLBD", "ITBD", "OPBD", "PRCD")       # saldo de lo ya confirmado
DISPONIBLE = ("ITAV", "CLAV", "OPAV", "XPCD", "FWAV")  # ya resta lo pendiente


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


def aspsp(c: dict | None = None) -> dict | None:
    """Banco elegido. Las instalaciones de antes del asistente no lo guardaban: eran Revolut."""
    c = c if c is not None else cfg()
    if c.get("aspsp"):
        return c["aspsp"]
    return {"name": "Revolut", "country": "ES"} if c.get("session_id") else None


def es_revolut(c: dict | None = None) -> bool:
    a = aspsp(c)
    return bool(a) and a["name"].lower().startswith("revolut")


def cuenta_ledger(banco: str, n: int) -> str:
    """asset:revolut para Revolut (la de su extracto); asset:<banco> para los demás; -2, -3… si tiene varias."""
    if banco.lower().startswith("revolut"):
        base = rv.BANK
    else:
        s = unicodedata.normalize("NFKD", banco).encode("ascii", "ignore").decode().lower()
        base = "asset:" + (re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:40] or "banco")
    return base if n == 1 else f"{base}-{n}"


def cuentas(c: dict | None = None) -> list[dict]:
    """Cuentas en euros de la conexión, cada una con su cuenta del ledger."""
    c = c if c is not None else cfg()
    banco = (aspsp(c) or {"name": "banco"})["name"]
    out, n = [], 0
    for a in c.get("cuentas") or []:
        if a.get("moneda") != "EUR":
            continue
        n += 1
        out.append(a | {"ledger": a.get("ledger") or cuenta_ledger(banco, n)})
    return out


# ---------- API de Enable Banking ----------

def _b64(b: bytes) -> bytes:
    return base64.urlsafe_b64encode(b).rstrip(b"=")


def _jwt(app_id: str) -> str:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    try:
        key = serialization.load_pem_private_key(clave(app_id).read_bytes(), None)
    except OSError:
        raise BancoError("Falta la clave privada: súbela en Finanzas → Banco") from None
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
        if r.status_code == 401:
            detalle = f"no acepta la clave ({detalle}). ¿El .pem es el de esta aplicación?"
        raise BancoError(f"Enable Banking respondió {r.status_code}: {str(detalle)[:300]}")
    return r.json() if r.content else {}


def aplicacion() -> dict:
    """Cómo está registrada la aplicación en Enable Banking, con lo que falte para poder conectar."""
    a = _call("GET", "/application")
    problemas = []
    if str(a.get("environment", "")).upper() != "PRODUCTION":
        problemas.append("La aplicación es de Sandbox (pruebas): para tu banco real crea una de Production.")
    if not a.get("active"):
        problemas.append("La aplicación aún no está activa: en su panel pulsa «Activate by linking accounts» y elige tu banco.")
    if not a.get("redirect_urls"):
        problemas.append("La aplicación no tiene ninguna «Allowed redirect URL».")
    return {"nombre": a.get("name"), "entorno": a.get("environment"), "activa": bool(a.get("active")),
            "redirect_urls": a.get("redirect_urls") or [], "problemas": problemas}


def bancos(pais: str) -> list[dict]:
    r = _call("GET", "/aspsps", params={"country": pais, "psu_type": "personal"}).get("aspsps") or []
    return sorted(({"name": b["name"], "country": b.get("country", pais), "logo": b.get("logo"),
                    "dias": int(b.get("maximum_consent_validity") or 0) // 86400 or None} for b in r if b.get("name")),
                  key=lambda b: b["name"].lower())


def elegir_banco(nombre: str, pais: str) -> dict:
    b = next((x for x in bancos(pais) if x["name"] == nombre), None)
    if b is None:
        raise BancoError(f"{nombre} no aparece en Enable Banking para {pais}")
    c = cfg()
    if aspsp(c) != {"name": nombre, "country": pais}:
        # Otro banco: la conexión anterior, sus cuentas y los nombres aprendidos no le sirven
        _guardar(aspsp={"name": nombre, "country": pais}, session_id=None, valid_until=None, cuentas=[], alias={},
                 desde={}, ultima=None, error=None, estado_auth=None)
    return estado()


def conectar(redirect_url: str) -> dict:
    """Pide al banco un permiso nuevo. Devuelve la dirección donde lo apruebas; vuelve a una redirect URL registrada."""
    c = cfg()
    banco = aspsp(c)
    if not banco:
        raise BancoError("Elige primero tu banco")
    registradas = aplicacion()["redirect_urls"]
    # La dirección del panel si está registrada; si no, la primera registrada, y el código se pega a mano
    vuelta = redirect_url if redirect_url in registradas else next((u for u in registradas if u.endswith(RUTA_VUELTA)), None)
    if vuelta is None:
        raise BancoError(f"Añade {redirect_url} a las «Allowed redirect URLs» de tu aplicación en Enable Banking")
    b = next((x for x in bancos(banco["country"]) if x["name"] == banco["name"]), None)
    if b is None:
        raise BancoError(f"{banco['name']} no aparece en Enable Banking para {banco['country']}")
    segundos = min((b["dias"] or 90) * 86400, 180 * 86400) - 3600
    hasta = (datetime.now(timezone.utc) + timedelta(seconds=segundos)).isoformat()
    state = tokens.token_urlsafe(16)
    r = _call("POST", "/auth", {"access": {"valid_until": hasta}, "aspsp": banco, "state": state,
                                "redirect_url": vuelta, "psu_type": "personal"})
    _guardar(estado_auth=state)
    return {"url": r["url"], "redirect_url": vuelta, "pegar": vuelta != redirect_url}


def de_url(url: str) -> tuple[str, str]:
    """Código y estado de la dirección a la que volvió el navegador (para pegarla si esa página no carga)."""
    q = parse_qs(urlsplit(url.strip()).query)
    if q.get("error"):
        raise BancoError(f"El banco no dio el permiso: {(q.get('error_description') or q['error'])[0]}")
    if not q.get("code") or not q.get("state"):
        raise BancoError("Esa dirección no lleva el código del banco (code=…). Copia la dirección completa de la barra del navegador.")
    return q["code"][0], q["state"][0]


def completar(code: str, state: str) -> dict:
    c = cfg()
    if not c.get("estado_auth") or not tokens.compare_digest(state, c["estado_auth"]):
        raise BancoError("Este enlace de vuelta no es de la última conexión que pediste. Vuelve a conectar desde Finanzas.")
    r = _call("POST", "/sessions", {"code": code})
    anterior = c.get("session_id")
    previas = {a["uid"]: a for a in c.get("cuentas") or []}
    nuevas = []
    for a in r.get("accounts", []):
        iban = (a.get("account_id") or {}).get("iban") or ""
        nuevas.append({"uid": a["uid"], "moneda": a.get("currency"), "nombre": a.get("name") or a.get("product") or "",
                       "iban": iban[-4:]} | ({"ledger": previas[a["uid"]]["ledger"]} if previas.get(a["uid"], {}).get("ledger") else {}))
    _guardar(aspsp=aspsp(c), session_id=r["session_id"], valid_until=(r.get("access") or {}).get("valid_until"), cuentas=nuevas,
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
    return {"app_id": app_id, "clave": bool(app_id) and clave(app_id).is_file(), "aspsp": aspsp(c),
            "banco": (aspsp(c) or {}).get("name"), "conectado": bool(c.get("session_id")), "esperando": bool(c.get("estado_auth")),
            "dias": dias_restantes(c), "valido_hasta": c.get("valid_until"),
            "cuentas": [{"nombre": a.get("nombre", ""), "iban": a.get("iban", ""), "ledger": a["ledger"]} for a in cuentas(c)],
            "otras_divisas": sorted({a["moneda"] for a in c.get("cuentas") or [] if a.get("moneda") and a["moneda"] != "EUR"}),
            "ultima": c.get("ultima"), "error": c.get("error"), "alias": len(c.get("alias") or {}), "paises": PAISES}


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
    d = " · ".join(dict.fromkeys(p for p in partes if p)) or "Movimiento sin concepto"
    return d[:-8] if d.lower().endswith(" pending") else d


def fila(t: dict, alias: dict[str, str]) -> dict:
    texto = _texto(t)
    codigo = (t.get("bank_transaction_code") or {}).get("code") or ""
    importe = _signo(t)
    tipo = TIPOS.get(codigo, codigo.title())
    if importe > 0 and codigo in ("TRANSFER", "TOPUP"):
        tipo = "Deposit"  # como en el extracto de Revolut: así se reconocen nómina, Bizum y devoluciones
    return {"fecha": t["booking_date"], "valor": t.get("value_date") or t["booking_date"], "tipo": tipo, "codigo": codigo,
            "bruto": texto, "descripcion": alias.get(texto.lower(), texto), "importe": importe, "comision": Decimal(0)}


def clasificar(f: dict, rules: list[tuple[str, str]]) -> str | None:
    """Bancos que no son Revolut: lo que enseñaste, Bizum, tus transferencias, la nómina y los comercios conocidos."""
    d = f["descripcion"].lower()
    for pattern, cuenta in rules:
        if pattern in d:
            return cuenta
    if "bizum" in d:
        return "income:bizum" if f["importe"] > 0 else "expense:bizum"
    yo = str(ajustes.leer("perfil").get("nombre_completo") or "").strip().lower()
    if yo and yo in d:
        return rv.OWN
    if f["importe"] > 0:
        pagadores = [str(x).strip().lower() for x in ajustes.leer("finanzas").get("pagadores_nomina") or [] if str(x).strip()]
        return "income:nomina" if any(p in d for p in pagadores) or re.search(r"\bn[oó]mina\b", d) else None
    for cuenta, pats in rv.REGLAS.items():
        if re.search(pats.replace("(", r"\(").replace(")", r"\)"), d):
            return cuenta
    return None


def _cuentas_contrapartida(db: Session, revolut: bool) -> None:
    if revolut:
        rv.ensure_accounts(db)
        return
    for name in rv.REGLAS:
        fin.account(db, name, "expense")
    for name, kind in (("expense:bizum", "expense"), ("income:bizum", "income"), ("income:nomina", "income"), (rv.OWN, "asset")):
        fin.account(db, name, kind)


def external_id(t: dict) -> str:
    ref = t.get("entry_reference") or t.get("transaction_id")
    if ref:
        return f"eb:{ref}"[:160]
    return "eb:" + hashlib.sha256(f"{t.get('booking_date')}|{_texto(t)}|{_signo(t)}".encode()).hexdigest()[:32]


def _movimientos(db: Session, cuenta: LedgerAccount, de_api: bool, desde: str) -> list[dict]:
    """Asientos importados en esa cuenta (de la API o de extractos): fecha, importe y descripción."""
    origen = JournalEntry.external_id.like("eb:%") if de_api else ~JournalEntry.external_id.like("eb:%")
    q = (select(JournalEntry.id, JournalEntry.entry_date, JournalEntry.description, Posting.amount)
         .join(Posting, Posting.entry_id == JournalEntry.id)
         .where(Posting.account_id == cuenta.id, JournalEntry.external_id.is_not(None), origen, JournalEntry.entry_date >= desde,
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


def _saldo(saldos: list[dict]) -> tuple[Decimal, bool] | None:
    """(importe, ya_es_contable). Mejor el contable; si no hay, el disponible (al que luego se suma lo pendiente)."""
    for tipos, contable in ((CONTABLE, True), (DISPONIBLE, False)):
        s = next((x for t in tipos for x in saldos if x.get("balance_type") == t), None)
        if s:
            return Decimal(str(s["balance_amount"]["amount"])), contable
    return (Decimal(str(saldos[0]["balance_amount"]["amount"])), False) if saldos else None


def importar(db: Session, txs: list[dict], saldo: tuple[Decimal, bool] | None, desde: str, ledger: str = rv.BANK,
             actor: str = ACTOR, institucion: str = "") -> dict:
    """Apunta en `ledger` lo confirmado que no esté ya (por la API o por un extracto). `desde`: inicio de la ventana pedida."""
    c = cfg()
    revolut = ledger == rv.BANK or es_revolut(c)
    _cuentas_contrapartida(db, revolut)
    banco = fin.account(db, ledger, "asset")
    if institucion and not banco.institution:
        banco.institution = institucion[:80]
    alias: dict[str, str] = dict(c.get("alias") or {})
    cortes = c.get("desde") if isinstance(c.get("desde"), dict) else ({rv.BANK: c["desde"]} if c.get("desde") else {})
    corte = cortes.get(ledger)
    if corte is None:  # primera vez: lo anterior al último extracto ya está apuntado
        corte = max((m["fecha"] for m in _movimientos(db, banco, False, "0000-00-00")), default="0000-00-00")
    existentes = set(db.scalars(select(JournalEntry.external_id).where(JournalEntry.external_id.like("eb:%"))))
    libres = _movimientos(db, banco, False, (date.fromisoformat(desde) - timedelta(days=2)).isoformat())
    rules = rv.learned(db)
    nuevos = dup = casados = revisar = anteriores = 0
    pendiente = Decimal(0)
    for t in sorted(txs, key=lambda t: (t.get("booking_date") or "", t.get("entry_reference") or "")):
        if t.get("status") != "BOOK":
            pendiente += _signo(t)
            continue
        if not t.get("booking_date"):
            continue
        f = fila(t, alias)
        if f["importe"] == 0:
            continue
        ext = external_id(t)
        if ext in existentes:
            dup += 1
            continue
        extracto = _pareja(libres, f["importe"], f["fecha"], f["valor"], f["valor"])
        if extracto is not None:
            casados += 1
            aprende = f["codigo"] not in ("TRANSFER", "TOPUP", "EXCHANGE") and "bizum" not in f["bruto"].lower()
            if aprende and f["bruto"].lower() != extracto["descripcion"].lower():
                alias[f["bruto"].lower()] = extracto["descripcion"]
            continue
        if f["fecha"] < corte:
            anteriores += 1  # anterior al último extracto y sin pareja: el extracto manda
            continue
        f["descripcion"] = alias.get(f["bruto"].lower(), f["descripcion"])
        cuenta = rv.classify(f, rules) if revolut else clasificar(f, rules)
        conocida = cuenta is not None
        contra = fin.account(db, cuenta) if conocida else fin.account(
            db, fin.SIN_CATEGORIZAR if f["importe"] < 0 else fin.INGRESO_SIN_CATEGORIZAR, "expense" if f["importe"] < 0 else "income")
        fin.post_entry(db, f["fecha"], f["descripcion"], [(banco.id, f["importe"], "EUR"), (contra.id, -f["importe"], "EUR")], actor,
                       status="posted" if conocida else "pending", external_id=ext)
        existentes.add(ext)
        nuevos += 1
        revisar += 0 if conocida else 1
    declarado = None
    if saldo is not None:
        importe, contable = saldo
        declarado = importe if contable else importe - pendiente  # el disponible ya resta lo pendiente, aún sin apuntar
        fin.declare_snapshot(db, banco.id, hoy(), declarado)  # foto de ahora: se guarda como cierre de ayer
    _guardar(alias=alias, desde=cortes | {ledger: corte})
    return {"nuevos": nuevos, "por_revisar": revisar, "duplicados": dup, "ya_en_csv": casados, "anteriores_sin_pareja": anteriores,
            "pendientes": fin.money(abs(pendiente)), "saldo": fin.money(declarado) if declarado is not None else None}


def ya_por_api(fecha: str, importe: Decimal, libres: list[dict] | None) -> bool:
    """Para los importadores de extractos: ¿este movimiento ya entró por la API? Consume la pareja para no casar dos veces."""
    if libres is None:
        return False
    return _pareja(libres, importe, fecha, fecha, fecha) is not None


def libres_api(db: Session, desde: str, cuenta: LedgerAccount | None = None) -> list[dict] | None:
    """Movimientos de la API en esa cuenta desde esa fecha, para que un extracto no los duplique. None si no hay ninguno."""
    cuenta = cuenta or db.scalar(select(LedgerAccount).where(LedgerAccount.name == rv.BANK))
    if cuenta is None:
        return None
    libres = _movimientos(db, cuenta, True, (date.fromisoformat(desde) - timedelta(days=2)).isoformat())
    return libres or None


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
    lista = cuentas(c)
    if not lista:
        raise BancoError("La conexión no tiene ninguna cuenta en euros")
    ultima = (c.get("ultima") or {}).get("fecha")
    if ultima and c.get("desde"):
        desde = (date.fromisoformat(ultima) - timedelta(days=SOLAPE)).isoformat()
    else:
        desde = (datetime.now(TZ).date() - timedelta(days=PRIMERA_VEZ)).isoformat()
    banco = (aspsp(c) or {}).get("name", "")
    total: dict = {}
    for a in lista:
        txs = _descargar(a["uid"], desde)
        saldo = _saldo(_call("GET", f"/accounts/{a['uid']}/balances").get("balances") or [])
        r = importar(db, txs, saldo, desde, a["ledger"], actor, institucion=banco)
        for k, v in r.items():
            if isinstance(v, int):
                total[k] = total.get(k, 0) + v
        total.setdefault("saldos", {})[a["ledger"]] = r["saldo"]
        total["saldo"] = r["saldo"] if len(lista) == 1 else None
    _guardar(ultima={"fecha": hoy(), "hora": datetime.now(TZ).strftime("%H:%M")} | total, error=None, intentos=None)
    events.audit(db, actor, "finance.banco.sync", banco, nuevos=total.get("nuevos", 0), por_revisar=total.get("por_revisar", 0))
    return total


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
        _avisar("warning", "Reconecta el banco en Finanzas", f"{motivo} Entra en Finanzas → Importar y ajustes y pulsa «Reconectar».")
    if not toca(c, now):
        return
    hoy_ = dia.isoformat()
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
    app_id: str = Field(pattern=APP_ID_RE)
    pem: str | None = Field(default=None, max_length=20_000)


class BancoIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    pais: str = Field(pattern=r"^[A-Z]{2}$")


class ConectarIn(BaseModel):
    redirect_url: str = Field(max_length=300, pattern=r"^https?://[^\s/]+/finanzas/banco$")


class VueltaIn(BaseModel):
    code: str | None = Field(default=None, min_length=8, max_length=200)
    state: str | None = Field(default=None, min_length=8, max_length=100)
    url: str | None = Field(default=None, max_length=2000)  # la dirección entera, si se pega a mano


def _http(fn, *a):
    try:
        return fn(*a)
    except BancoError as e:
        raise HTTPException(502, str(e)) from None


@router.get("")
def get_estado():
    return estado()


@router.post("/app")
async def set_app(body: AppIn, p: Principal = Depends(require_admin)):
    """Application ID y, si se sube, su clave privada: la guarda el Host Agent (este proceso nunca escribe en secrets/)."""
    if body.pem:
        from ..adapters import hostagent
        await hostagent.call("/v1/banco/clave", method="PUT", json={"app_id": body.app_id, "pem": body.pem})
    if cfg().get("app_id") != body.app_id:
        _guardar(app_id=body.app_id, session_id=None, valid_until=None, cuentas=[], estado_auth=None)  # otra aplicación: otro permiso
    with session_scope() as db:
        events.audit(db, p.name, "finance.banco.app", body.app_id, clave=bool(body.pem))  # nunca la clave
    return estado()


@router.get("/aplicacion", dependencies=[Depends(require_admin)])
def get_aplicacion():
    return _http(aplicacion)


@router.get("/bancos", dependencies=[Depends(require_admin)])
def get_bancos(pais: str = "ES"):
    if not re.fullmatch(r"[A-Z]{2}", pais):
        raise HTTPException(422, "País no válido")
    return _http(bancos, pais)


@router.post("/banco")
def post_banco(body: BancoIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    r = _http(elegir_banco, body.nombre, body.pais)
    events.audit(db, p.name, "finance.banco.elegir", f"{body.nombre} ({body.pais})")
    return r


@router.post("/conectar", dependencies=[Depends(require_admin)])
def post_conectar(body: ConectarIn):
    return _http(conectar, body.redirect_url)


@router.post("/vuelta")
def post_vuelta(body: VueltaIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    if body.url:
        code, state = _http(de_url, body.url)
    elif body.code and body.state:
        code, state = body.code, body.state
    else:
        raise HTTPException(422, "Falta el código del banco")
    r = _http(completar, code, state)
    events.audit(db, p.name, "finance.banco.conectar", r["banco"] or "")
    return r


@router.post("/sincronizar")
def post_sincronizar(p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        return sincronizar(db, p.name) | {"estado": estado()}
    except BancoError as e:
        _guardar(error={"fecha": hoy(), "hora": datetime.now(TZ).strftime("%H:%M"), "mensaje": str(e)[:300]})
        raise HTTPException(502, str(e)) from None
