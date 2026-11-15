"""Importa el extracto CSV de Revolut al ledger.

Un extracto no distingue gasto de movimiento propio: aquí se clasifica cada línea por su naturaleza. Lo que solo cambia el
dinero de sitio (fondo, inversión, cripto, divisas, tus otras cuentas) va a una cuenta de activo y no cuenta como gasto ni
ingreso. Los comercios se categorizan con reglas, sin modelo; lo dudoso queda por revisar y no cuenta en los totales.

Sin datos del extracto no hay ninguna cifra: el fondo y las inversiones valen lo que entró y salió, no su valor de mercado.
"""
import csv
import hashlib
import io
import re
from collections import defaultdict
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

import sys

from ..config import ROOT

sys.path.insert(0, str(ROOT / "collectors"))
import ajustes  # noqa: E402
from ..models import BalanceAssertion, ImportBatch, JournalEntry, Posting
from . import finance as fin

HEADER = ["Type", "Product", "Started Date", "Completed Date", "Description", "Amount", "Fee", "Currency", "State", "Balance"]
BANK = "asset:revolut"
FEES = "expense:comisiones"
OWN = "asset:otras-cuentas-propias"
FX = "asset:revolut-divisas"
SOLD = "asset:revolut-cripto"  # dinero que aparece en una divisa sin salir de euros: venta de cripto o inversión
ACCOUNTS = {
    "asset:revolut-flexible": "asset", "asset:revolut-inversion": "asset", "asset:revolut-cripto": "asset", "asset:revolut-divisas": "asset",
    BANK: "asset", OWN: "asset", FEES: "expense", "expense:bizum": "expense", "expense:restaurantes": "expense", "expense:tabaco": "expense",
    "expense:educacion": "expense", "expense:deporte": "expense", "expense:compras": "expense", "expense:cuidado-personal": "expense",
    "income:bizum": "income", "income:impuestos": "income",
}
# Orden: de lo más específico a lo más general. El primer patrón que encaja decide.
MOVIMIENTOS = (
    (r"(to|from) (eur )?flexible cash funds", "asset:revolut-flexible"),
    (r"to investment account|to robo portfolio|revolut x|exchanged to xau", "asset:revolut-inversion"),
    (r"revolut digital assets", "asset:revolut-cripto"),
    (r"exchanged to ", "asset:revolut-divisas"),
)


def _movimientos() -> tuple:
    """Más las transferencias a tu propio nombre (perfil → nombre_completo). Los depósitos sin nombre no: se quedan por revisar."""
    yo = str(ajustes.leer("perfil").get("nombre_completo") or "").strip().lower()
    return MOVIMIENTOS + (((rf"^to {re.escape(yo)}", OWN),) if yo else ())
INGRESOS = (
    (r"devoluciones tributarias", "income:impuestos"),
    (r"money added via bizum", "income:bizum"),
)


def _ingresos() -> tuple:
    """Más la nómina: «Payment from <pagador>» de los pagadores de config finanzas.json (pagadores_nomina)."""
    pag = [re.escape(str(x).strip().lower()) for x in ajustes.leer("finanzas").get("pagadores_nomina") or [] if str(x).strip()]
    return ((rf"payment from ({'|'.join(pag)})", "income:nomina"),) + INGRESOS if pag else INGRESOS


REGLAS = {
    "expense:restaurantes": "uber eats|biergarten|bistro|patisserie|déryné|bella napoli|cafe europa|restaurant|el baresito|la pepa|pizzeria|frankfurt|bon aire|vinito|sandor 1944|sushiko|burger king|mcdonald|five guys|enrique tomás|kebab|gyoza|pastisseria|fornet|pans & company|crep nova|pizza|cafe |café|cafè|cafeteria|bar |bar$|cerveseria|grill|brunch|la parada|gelateria|forn |aspic|argento|il golfo|la oveja negra|mmm...ke bo|l'artigiano|wine palace|cagayana",
    "expense:comida": "spar food|zoldseg|multi-fruits|supermerc|supermarket|super express|super mercadal|super sale|one stop super|caprabo|mercadona|eroski|carrefour|condis|bonpreu|coaliment|alimentacion|fruites|suma",
    "expense:tabaco": "estanc|tabac|dohánybolt",
    "expense:transporte": "uber|cabify|taxi|lic.|lic |llic|transports metropolitans|renfe|sagalés|repsol|meroil|gnv|parking|gas division",
    "expense:suscripciones": "spotify|netflix|anthropic|microsoft|hostinger|cloudflare|elevenlabs|apple",
    "expense:ocio": "sala apolo|sala b|discoteca|jazzbah|luz de gas|ticketmaster|ticketpay|idticketing|weezevent|fourvenues|dice|oktoberfest|cova d'en xoroi|ama espectaculos|johnnys|steam|warhammer|airsoft|water world|lassdive|bling bling|tempus fugit|belushis",
    "expense:ropa": "bijou brigitte|zara|macson|uniqlo|clinica del calcat|tintorer|arista illa|2326 illa",
    "expense:salud": "óptica|fcia|farmacia",
    "expense:hogar": "la tienda home|ikea|ferreteria",
    "expense:viajes": "mercure|hotel|budavári sikló|photoautomat",
    "expense:educacion": "universidad|universitat|universitad|matrícula|matricula|casa del libro",
    "expense:deporte": "vivagym|fitness barcelone|bioenergy|crosmas",
    "expense:compras": "kakobuy|amazon|pay pal|fnac|el corte inglés|fedex|honghong|pabzhw",
    "expense:cuidado-personal": "barbers|hair salon",
}


def is_revolut(text: str) -> bool:
    first = text.lstrip("﻿").split("\n", 1)[0].strip().split(",")
    return first == HEADER


def currency_of(text: str) -> str:
    fila = next(csv.DictReader(io.StringIO(text.lstrip("\ufeff"))), None)
    if fila is None:
        raise HTTPException(422, "El extracto está vacío")
    return fila["Currency"]


def parse(text: str, moneda: str = "EUR") -> dict:
    """Lee el extracto y separa lo que movió dinero. Comprueba además que cada saldo sale del anterior."""
    if not is_revolut(text):
        raise HTTPException(422, "No es un extracto de Revolut")
    filas, ignoradas, retenidos, vistos = [], [], [], defaultdict(int)
    prev = None
    for n, r in enumerate(csv.DictReader(io.StringIO(text.lstrip("﻿"))), start=2):
        if r["State"] != "COMPLETED":
            ignoradas.append({"estado": r["State"], "descripcion": r["Description"], "importe": r["Amount"]})
            # Pendiente o revertido: no entra en la columna de saldo. Lo pendiente ya no está disponible.
            retenidos.append({"fecha": r["Started Date"][:10], "inicio": r["Started Date"], "tipo": r["Type"], "descripcion": " ".join(r["Description"].split()),
                              "importe": Decimal(r["Amount"]), "comision": Decimal(r["Fee"]), "orden": 1, "estado": r["State"]})
            continue
        if r["Currency"] != moneda:
            raise HTTPException(422, f"Línea {n}: se esperaba {moneda} y hay {r['Currency']}")
        importe, comision, saldo = Decimal(r["Amount"]), Decimal(r["Fee"]), Decimal(r["Balance"])
        if prev is not None and prev + importe - comision != saldo:
            raise HTTPException(422, f"Línea {n}: el saldo no cuadra con el anterior. No se importa nada.")
        prev = saldo
        clave = (r["Started Date"], r["Description"], r["Amount"])
        vistos[clave] += 1
        filas.append({"fecha": r["Completed Date"][:10], "inicio": r["Started Date"], "tipo": r["Type"], "descripcion": " ".join(r["Description"].split()),
                      "importe": importe, "comision": comision, "saldo": saldo, "orden": vistos[clave]})
    return {"filas": filas, "ignoradas": ignoradas, "retenidos": retenidos}


def classify(f: dict, rules: list[tuple[str, str]] = ()) -> str | None:
    """Cuenta de la otra parte. None: nadie sabe qué es, y se queda por revisar. Lo que el usuario enseñó manda."""
    d, t = f["descripcion"].lower(), f["tipo"]
    for pattern, cuenta in rules:
        if pattern in d:
            return cuenta
    if t == "Charge" and f["importe"] == 0:
        return FEES
    if t == "Deposit":
        for pat, cuenta in _ingresos():
            if re.search(pat, d):
                return cuenta
    if d.startswith("bizum payment to"):
        return "expense:bizum"
    for pat, cuenta in _movimientos():
        if re.search(pat, d):
            return cuenta
    if t == "Deposit":
        return None  # las reglas son de comercios: un depósito sin nombre no es una compra en Apple
    if d.startswith("refund "):
        d = d[7:]
    for cuenta, pats in REGLAS.items():
        if re.search(pats.replace("(", r"\(").replace(")", r"\)"), d):
            return cuenta
    return None


def revert(db: Session, ext: str, actor: str) -> None:
    e = db.scalar(select(JournalEntry).where(JournalEntry.external_id == ext))
    if e is None or db.scalar(select(JournalEntry.id).where(JournalEntry.reverses_id == e.id)):
        return
    lineas = [(p.account_id, -p.amount, p.currency) for p in db.scalars(select(Posting).where(Posting.entry_id == e.id))]
    fin.post_entry(db, e.entry_date, f"Revertido por el banco: {e.description}", lineas, actor, reverses_id=e.id)


def learned(db: Session) -> list[tuple[str, str]]:
    return fin.rules_list(db)


def external_id(f: dict) -> str:
    return "revolut:" + hashlib.sha256(f"{f['inicio']}|{f['descripcion']}|{f['importe']}|{f['orden']}".encode()).hexdigest()[:32]


def ensure_accounts(db: Session) -> None:
    for name, kind in ACCOUNTS.items():
        fin.account(db, name, kind)
    for name in REGLAS:
        fin.account(db, name, "expense")
    fin.account(db, "income:nomina", "income")


def apply(db: Session, text: str, filename: str, actor: str) -> dict:
    if currency_of(text) != "EUR":
        return apply_foreign(db, text, filename, actor)
    data = parse(text)
    ensure_accounts(db)
    banco = fin.account(db, BANK)
    sha = hashlib.sha256(text.encode()).hexdigest()
    batch = ImportBatch(account_id=banco.id, filename=filename[:200], sha256=sha, rows=len(data["filas"]), created_by=actor)
    db.add(batch)
    db.flush()
    existing = set(db.scalars(select(JournalEntry.external_id).where(JournalEntry.external_id.like("revolut:%"))))
    nuevos = dup = revisar = 0
    fin_de_mes: dict[str, dict] = {}
    rules = learned(db)
    for f in data["filas"]:
        fin_de_mes[f["fecha"][:7]] = f
        ext = external_id(f)
        if ext in existing:
            dup += 1
            continue
        cuenta = classify(f, rules)
        conocida = cuenta is not None
        contra = fin.account(db, cuenta) if conocida else fin.account(db, fin.SIN_CATEGORIZAR if f["importe"] < 0 else fin.INGRESO_SIN_CATEGORIZAR, "expense" if f["importe"] < 0 else "income")
        lineas = [(banco.id, f["importe"] - f["comision"], "EUR")]
        if f["importe"] != 0:
            lineas.append((contra.id, -f["importe"], "EUR"))
        if f["comision"] != 0:
            lineas.append((fin.account(db, FEES).id, f["comision"], "EUR"))
        fin.post_entry(db, f["fecha"], f["descripcion"], lineas, actor, status="posted" if conocida else "pending", external_id=ext, batch_id=batch.id)
        nuevos += 1
        revisar += 0 if conocida else 1
    retenido = Decimal(0)
    for f in data["retenidos"]:
        ext = external_id(f)
        if f["estado"] == "PENDING":
            retenido += f["importe"] - f["comision"]
            if ext not in existing:
                cuenta = classify(f, rules)
                contra = fin.account(db, cuenta) if cuenta else fin.account(db, fin.SIN_CATEGORIZAR, "expense")
                fin.post_entry(db, f["fecha"], f["descripcion"], [(banco.id, f["importe"], "EUR"), (contra.id, -f["importe"], "EUR")], actor,
                               status="posted" if cuenta else "pending", external_id=ext, batch_id=batch.id)
                nuevos += 1
        elif f["estado"] == "REVERTED" and ext in existing:
            revert(db, ext, actor)  # lo apuntamos cuando estaba pendiente y el banco lo ha anulado
    ultimo = max(fin_de_mes) if fin_de_mes else None
    declarados = {b.as_of: b for b in db.scalars(select(BalanceAssertion).where(BalanceAssertion.account_id == banco.id))}
    for mes, f in fin_de_mes.items():
        # El saldo del extracto no resta lo pendiente: el disponible real, sí
        final = mes == ultimo
        cifra = f["saldo"] + (retenido if final else 0)
        # Fechado en el último pendiente: si no, el saldo sería anterior al pago que ya resta
        dia = max([f["fecha"], *(x["fecha"] for x in data["retenidos"] if x["estado"] == "PENDING")]) if final else f["fecha"]
        if dia in declarados:
            declarados[dia].amount = cifra
        else:
            db.add(BalanceAssertion(account_id=banco.id, as_of=dia, amount=cifra, currency="EUR"))
    return {"lote": batch.id, "nuevos": nuevos, "duplicados": dup, "por_revisar": revisar, "ignorados": [x for x in data["ignoradas"] if x["estado"] != "PENDING"], "saldo_final": fin.money(data["filas"][-1]["saldo"] + retenido) if data["filas"] else None}


def _exchanges(db: Session) -> dict[str, Decimal]:
    """Euros cambiados a otra moneda cada día, según el extracto en euros."""
    banco = fin.account(db, BANK)
    q = (select(JournalEntry.entry_date, Posting.amount).join(Posting, Posting.entry_id == JournalEntry.id)
         .where(Posting.account_id == banco.id, JournalEntry.description.like("Exchanged to %"), ~JournalEntry.description.in_(("Exchanged to EUR", "Exchanged to XAU"))))
    dias: dict[str, Decimal] = defaultdict(Decimal)
    for dia, importe in db.execute(q):
        dias[dia] += -Decimal(str(importe))
    return dias


def foreign_plan(db: Session, text: str) -> dict:
    """Convierte a euros con el tipo que pagaste: euros cambiados ÷ moneda recibida esos mismos días."""
    moneda = currency_of(text)
    data = parse(text, moneda)
    ensure_accounts(db)
    dias = _exchanges(db)
    entradas = [f for f in data["filas"] if f["tipo"] == "Exchange" and f["importe"] > 0]
    casadas = [f for f in entradas if f["fecha"] in dias]
    recibido = sum((f["importe"] for f in casadas), Decimal(0))
    fechas = {f["fecha"] for f in casadas}
    rate = sum((dias[d] for d in fechas), Decimal(0)) / recibido if recibido else None
    if not rate:
        return {"moneda": moneda, "rate": None, "movimientos": [], "data": data}  # solo de paso: no hay nada que apuntar en euros
    movimientos = []
    for f in data["filas"]:
        if f["tipo"] == "Exchange" and not (f["importe"] > 0 and f["fecha"] not in dias):
            continue  # su lado en euros ya está en el extracto principal
        movimientos.append(f | {"eur": (f["importe"] * rate).quantize(Decimal("0.01")), "fee_eur": (f["comision"] * rate).quantize(Decimal("0.01"))})
    return {"moneda": moneda, "rate": rate, "movimientos": movimientos, "data": data}


def apply_foreign(db: Session, text: str, filename: str, actor: str) -> dict:
    plan = foreign_plan(db, text)
    ensure_accounts(db)
    if not plan["rate"]:
        return {"lote": None, "nuevos": 0, "duplicados": 0, "por_revisar": 0, "ignorados": [], "saldo_final": "0.00", "moneda": plan["moneda"], "tipo": None}
    fx = fin.account(db, FX)
    batch = ImportBatch(account_id=fx.id, filename=filename[:200], sha256=hashlib.sha256(text.encode()).hexdigest(), rows=len(plan["movimientos"]), created_by=actor)
    db.add(batch)
    db.flush()
    existing = set(db.scalars(select(JournalEntry.external_id).where(JournalEntry.external_id.like("revolut:%"))))
    rules, nuevos, dup, revisar = learned(db), 0, 0, 0
    for f in plan["movimientos"]:
        ext = f"revolut:{plan['moneda']}:{external_id(f).split(':')[1]}"[:160]
        if ext in existing:
            dup += 1
            continue
        cuenta = SOLD if f["tipo"] == "Exchange" else classify(f, rules)
        conocida = cuenta is not None
        contra = fin.account(db, cuenta) if conocida else fin.account(db, fin.SIN_CATEGORIZAR if f["importe"] < 0 else fin.INGRESO_SIN_CATEGORIZAR, "expense" if f["importe"] < 0 else "income")
        desc = f"{f['descripcion']} ({abs(f['importe'])} {plan['moneda']})"
        lineas = [(fx.id, f["eur"] - f["fee_eur"], "EUR"), (contra.id, -f["eur"], "EUR")]
        if f["fee_eur"]:
            lineas.append((fin.account(db, FEES).id, f["fee_eur"], "EUR"))
        fin.post_entry(db, f["fecha"], desc, lineas, actor, status="posted" if conocida else "pending", external_id=ext, batch_id=batch.id)
        nuevos += 1
        revisar += 0 if conocida else 1
    return {"lote": batch.id, "nuevos": nuevos, "duplicados": dup, "por_revisar": revisar, "ignorados": [], "saldo_final": "0.00", "moneda": plan["moneda"], "tipo": str(plan["rate"].quantize(Decimal("0.000001")))}


def preview(db: Session, text: str) -> dict:
    if currency_of(text) != "EUR":
        plan = foreign_plan(db, text)
        return {"filas": len(plan["movimientos"]), "nuevos": len(plan["movimientos"]), "duplicados": 0, "errores": [], "ignorados": 0, "moneda": plan["moneda"],
                "muestra": [{"fecha": f["fecha"], "descripcion": f"{f['descripcion']} ({f['importe']} {plan['moneda']})", "importe": fin.money(f["eur"])} for f in plan["movimientos"][:5]]}
    data = parse(text)
    existing = set(db.scalars(select(JournalEntry.external_id).where(JournalEntry.external_id.like("revolut:%"))))
    dup = sum(1 for f in data["filas"] if external_id(f) in existing)
    rules = learned(db)
    return {"filas": len(data["filas"]), "nuevos": len(data["filas"]) - dup, "duplicados": dup, "errores": [],
            "ignorados": len(data["ignoradas"]), "por_revisar": sum(1 for f in data["filas"] if classify(f, rules) is None),
            "muestra": [{"fecha": f["fecha"], "descripcion": f["descripcion"], "importe": fin.money(f["importe"])} for f in data["filas"][:5]]}


