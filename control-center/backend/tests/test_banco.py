"""Descarga del banco con Enable Banking (sin red: la API se simula)."""
from datetime import datetime, timezone
from decimal import Decimal
from itertools import count

import pytest
from sqlalchemy import select

from app import db as dbm
from app.models import JournalEntry
from app.modules import banco as bk
from app.modules import finance as fin
from app.modules import revolut as rv

from .test_revolut import csv, r

_ref = count(1)


def tx(fecha, texto, importe, codigo="CARD_PAYMENT", estado="BOOK", valor=None, **extra):
    imp = Decimal(importe)
    return {"entry_reference": f"ref-{next(_ref)}", "transaction_amount": {"currency": "EUR", "amount": str(abs(imp))},
            "credit_debit_indicator": "DBIT" if imp < 0 else "CRDT", "status": estado, "booking_date": fecha, "value_date": valor or fecha,
            "bank_transaction_code": {"code": codigo}, "remittance_information": texto if isinstance(texto, list) else [texto]} | extra


EXTRACTO = csv(
    r("Deposit", "2026-01-07", "Payment from EMPRESA EJEMPLO SL", "1000.00", "0.00", "1000.00"),
    r("Card Payment", "2026-01-08", "La Pepa Restaurante", "-10.50", "0.00", "989.50"),
    r("Transfer", "2026-01-09", "To EUR Flexible Cash Funds", "-100.00", "0.00", "889.50"),
)


def saldo(nombre, pendientes=True):
    with dbm.session_scope() as s:
        return fin.balance(s, fin.account(s, nombre).id, include_pending=pendientes)


def importar(txs, disponible=None, desde="2026-01-01"):
    with dbm.session_scope() as s:
        return bk.importar(s, txs, (Decimal(disponible), False) if disponible is not None else None, desde)


@pytest.fixture()
def con_csv(client):
    with dbm.session_scope() as s:
        rv.apply(s, EXTRACTO, "e.csv", "ana")


# ---------- de la API al formato del extracto ----------

def test_bizum_primero_y_sin_pending():
    f = bk.fila(tx("2026-02-01", ["Cena", "Bizum payment from: Ana P.G."], "15.00", "TOPUP"), {})
    assert f["descripcion"] == "Bizum payment from: Ana P.G. · Cena" and f["tipo"] == "Deposit"
    assert bk.fila(tx("2026-02-01", "Uber * Eats Pending", "-13.16"), {})["descripcion"] == "Uber * Eats"


@pytest.mark.parametrize("texto,importe,codigo,cuenta", [
    (["Cena", "Bizum payment from: Ana P.G."], "15.00", "TOPUP", "income:bizum"),
    (["Mcdonalds", "Bizum payment to: Pol B.M."], "-18.00", "TRANSFER", "expense:bizum"),
    ("To Flexible Cash Funds", "-1.80", "TRANSFER", "asset:revolut-flexible"),
    ("From Flexible Cash Funds", "4.48", "TRANSFER", "asset:revolut-flexible"),
    ("Exchanged to HUF", "-50.00", "EXCHANGE", "asset:revolut-divisas"),
    ("Payment from EMPRESA EJEMPLO SL", "1200.00", "TRANSFER", None),  # sin pagadores configurados: por revisar
])
def test_clasifica_como_el_extracto(texto, importe, codigo, cuenta):
    assert rv.classify(bk.fila(tx("2026-02-01", texto, importe, codigo), {})) == cuenta


# ---------- importación ----------

def test_sin_extracto_previo_importa_todo_y_concilia(client):
    res = importar([tx("2026-02-01", "Mercadona C Aribau", "-20.00"), tx("2026-02-02", ["x", "Bizum payment from: Ana"], "50.00", "TOPUP"),
                    tx("2026-02-03", "Uber * Eats Pending", "-13.16", estado="PDNG")], disponible="16.84")
    assert res["nuevos"] == 2 and res["por_revisar"] == 0 and res["saldo"] == "30.00"  # 16.84 disponible + 13.16 pendiente
    assert saldo(rv.BANK) == Decimal("30.00")
    with dbm.session_scope() as s:
        assert all(x["cuadra"] for x in fin.reconcile(s))


def test_lo_que_ya_entro_por_csv_no_se_duplica_y_ensena_el_nombre(con_csv):
    res = importar([
        tx("2026-01-07", "Payment from EMPRESA EJEMPLO SL", "1000.00", "TRANSFER"),
        tx("2026-01-07", "365 T178", "-10.50", valor="2026-01-08"),           # La Pepa, con otro nombre y otra fecha
        tx("2026-01-09", "To Flexible Cash Funds", "-100.00", "TRANSFER"),
        tx("2026-01-12", "365 T178", "-6.00", valor="2026-01-13"),            # nuevo: ya sabe que es La Pepa
    ])
    assert res["ya_en_csv"] == 3 and res["nuevos"] == 1 and res["por_revisar"] == 0  # con su nombre del CSV, la regla de restaurantes vale
    with dbm.session_scope() as s:
        e = s.scalar(select(JournalEntry).where(JournalEntry.external_id.like("eb:%")))
        assert e.description == "La Pepa Restaurante" and e.entry_date == "2026-01-12"
    assert bk.cfg()["alias"] == {"365 t178": "La Pepa Restaurante"} and bk.cfg()["desde"] == {rv.BANK: "2026-01-09"}
    assert saldo(rv.BANK) == Decimal("883.50")


def test_lo_anterior_al_ultimo_extracto_sin_pareja_no_entra(con_csv):
    res = importar([tx("2026-01-05", "Algo viejo", "-3.00"), tx("2026-01-10", "Algo nuevo", "-4.00")])
    assert res["anteriores_sin_pareja"] == 1 and res["nuevos"] == 1


def test_repetir_la_descarga_no_duplica(client):
    txs = [tx("2026-02-01", "Mercadona", "-20.00"), tx("2026-02-01", "Mercadona", "-20.00")]  # gemelos: dos compras
    assert importar(txs)["nuevos"] == 2
    res = importar(txs)
    assert res["nuevos"] == 0 and res["duplicados"] == 2
    assert saldo(rv.BANK) == Decimal("-40.00")


def test_las_reglas_aprendidas_valen_para_la_api(client, auth):
    importar([tx("2026-02-01", "Tienda Rara", "-5.00")])
    with dbm.session_scope() as s:
        eid = s.scalar(select(JournalEntry.id).where(JournalEntry.status == "pending"))
    assert client.post(f"/api/v1/finance/entries/{eid}/categorize", json={"cuenta": "expense:compras", "recordar": True}, headers=auth).status_code == 200
    assert importar([tx("2026-02-05", "Tienda Rara", "-7.00")])["por_revisar"] == 0


def test_un_extracto_despues_de_la_api_no_duplica(client):
    importar([tx("2026-03-02", "Carrefour Hospitalet", "-11.49", valor="2026-03-03"), tx("2026-03-04", "Frankfurt Europa", "-2.65")])
    extracto = csv(r("Deposit", "2026-03-01", "Payment from EMPRESA EJEMPLO SL", "100.00", "0.00", "100.00"),
                   r("Card Payment", "2026-03-03", "Carrefour", "-11.49", "0.00", "88.51"),
                   r("Card Payment", "2026-03-04", "Frankfurt Europa", "-2.65", "0.00", "85.86"))
    with dbm.session_scope() as s:
        assert rv.preview(s, extracto)["duplicados"] == 2
        res = rv.apply(s, extracto, "e.csv", "ana")
    assert res["nuevos"] == 1 and res["duplicados"] == 2
    assert saldo(rv.BANK) == Decimal("85.86")


# ---------- conexión ----------

class Llamadas(list):
    respuestas: dict


@pytest.fixture()
def api(client, monkeypatch, tmp_path):
    """Enable Banking simulado: guarda las llamadas y responde lo mínimo."""
    llamadas = Llamadas()
    respuestas = {
        ("GET", "/aspsps"): {"aspsps": [{"name": "Revolut", "country": "ES", "maximum_consent_validity": 15552000},
                                        {"name": "BBVA", "country": "ES", "maximum_consent_validity": 7776000}]},
        ("GET", "/application"): {"name": "Personal OS", "environment": "PRODUCTION", "active": True,
                                  "redirect_urls": ["https://pc.ts.net:8770/finanzas/banco"]},
        ("POST", "/auth"): {"url": "https://tilisy.enablebanking.com/ais/start?sessionid=x"},
        ("POST", "/sessions"): {"session_id": "ses-1", "access": {"valid_until": "2099-01-01T00:00:00Z"},
                                "accounts": [{"uid": "eur-1", "currency": "EUR"}, {"uid": "huf-1", "currency": "HUF"}]},
        ("GET", "/accounts/eur-1/transactions"): {"transactions": [tx("2026-02-01", "Mercadona", "-20.00")]},
        ("GET", "/accounts/eur-1/balances"): {"balances": [{"balance_type": "ITAV", "balance_amount": {"currency": "EUR", "amount": "80.00"}}]},
    }

    def falsa(method, path, body=None, params=None):
        llamadas.append((method, path, body, params))
        return respuestas[(method, path)]
    monkeypatch.setattr(bk, "_call", falsa)
    monkeypatch.setenv("POS_SECRETS_DIR", str(tmp_path))
    (tmp_path / "app-1.pem").write_text("x")
    bk._guardar(app_id="app-1", aspsp={"name": "Revolut", "country": "ES"})
    llamadas.respuestas = respuestas
    return llamadas


def test_conectar_y_sincronizar_por_el_panel(api, auth, client):
    assert client.get("/api/v1/finance/banco").json()["clave"] is True
    r_ = client.post("/api/v1/finance/banco/conectar", json={"redirect_url": "https://pc.ts.net:8770/finanzas/banco"}, headers=auth)
    assert r_.status_code == 200 and r_.json()["url"].startswith("https://tilisy")
    auth_body = next(c[2] for c in api if c[1] == "/auth")
    assert auth_body["aspsp"] == {"name": "Revolut", "country": "ES"} and auth_body["redirect_url"].endswith("/finanzas/banco")
    mal = client.post("/api/v1/finance/banco/vuelta", json={"code": "codigo-123", "state": "otro-estado"}, headers=auth)
    assert mal.status_code == 502  # el estado debe ser el de la última conexión pedida
    e = client.post("/api/v1/finance/banco/vuelta", json={"code": "codigo-123", "state": auth_body["state"]}, headers=auth).json()
    assert e["conectado"] and e["dias"] > 1000
    s = client.post("/api/v1/finance/banco/sincronizar", headers=auth).json()
    assert s["nuevos"] == 1 and s["saldo"] == "80.00" and s["estado"]["ultima"]["nuevos"] == 1
    assert ("GET", "/accounts/huf-1/transactions", None, None) not in api  # de momento solo euros


def test_redirect_url_solo_a_la_ruta_del_panel(api, auth, client):
    assert client.post("/api/v1/finance/banco/conectar", json={"redirect_url": "https://malo.example/robar"}, headers=auth).status_code == 422


def test_tarea_de_las_3(api, monkeypatch):
    bk._guardar(session_id="ses-1", valid_until="2099-01-01T00:00:00Z", cuentas=[{"uid": "eur-1", "moneda": "EUR"}])
    antes = datetime(2026, 2, 10, 1, 30, tzinfo=timezone.utc)   # 2:30 en Madrid
    despues = datetime(2026, 2, 10, 2, 5, tzinfo=timezone.utc)  # 3:05
    monkeypatch.setattr(bk, "hoy", lambda: "2026-02-10")
    assert not bk.toca(bk.cfg(), antes) and bk.toca(bk.cfg(), despues)
    bk._diario_sync(despues)
    assert bk.cfg()["ultima"]["fecha"] == "2026-02-10" and not bk.toca(bk.cfg(), despues)


def test_fallo_reintenta_y_avisa_al_tercero(api, monkeypatch):
    bk._guardar(session_id="ses-1", valid_until="2099-01-01T00:00:00Z", cuentas=[{"uid": "eur-1", "moneda": "EUR"}])

    def roto(*a, **k):
        raise bk.BancoError("Enable Banking respondió 500")
    monkeypatch.setattr(bk, "_call", roto)
    avisos = []
    monkeypatch.setattr(bk, "_avisar", lambda *a: avisos.append(a))
    t = [1_000_000.0]
    monkeypatch.setattr(bk.time, "time", lambda: t[0])
    ahora = datetime(2026, 2, 10, 2, 5, tzinfo=timezone.utc)
    bk._diario_sync(ahora)
    assert not bk.toca(bk.cfg(), ahora) and bk.cfg()["error"]["mensaje"].endswith("500")  # espera una hora
    for _ in range(2):
        t[0] += 3600
        bk._diario_sync(ahora)
    assert len(avisos) == 1 and not bk.toca(bk.cfg(), ahora)  # tres intentos: avisa y no insiste más hoy


def test_aviso_de_caducidad(api, monkeypatch):
    bk._guardar(session_id="ses-1", valid_until=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                cuentas=[{"uid": "eur-1", "moneda": "EUR"}], ultima={"fecha": "2099-01-01"})
    avisos = []
    monkeypatch.setattr(bk, "_avisar", lambda *a: avisos.append(a))
    bk._diario_sync(datetime.now(timezone.utc))
    bk._diario_sync(datetime.now(timezone.utc))
    assert len(avisos) == 1 and "Reconecta" in avisos[0][1]


def test_el_saldo_de_ahora_no_descuadra_con_lo_que_llega_despues(client, monkeypatch):
    """El 5/11 el saldo se vio a media mañana y luego entraron más pagos de ese día: descuadraba sin haber error."""
    monkeypatch.setattr(bk, "hoy", lambda: "2026-11-05")
    manana = [tx("2026-11-04", "Mercadona", "-20.00"), tx("2026-11-05", "Cabify", "-5.00")]
    assert importar(manana, disponible="-25.00")["saldo"] == "-25.00"
    monkeypatch.setattr(bk, "hoy", lambda: "2026-11-06")
    importar([*manana, tx("2026-11-05", "Can Marlau", "-18.35")], disponible="-43.35")
    with dbm.session_scope() as s:
        c = fin.reconcile(s)
    assert {(x["fecha"], x["banco"]) for x in c} == {("2026-11-04", "-20.00"), ("2026-11-05", "-43.35")}
    assert all(x["cuadra"] for x in c)


def test_poner_el_valor_y_luego_llega_un_movimiento_del_mismo_dia(client):
    with dbm.session_scope() as s:
        flex, banco = fin.account(s, "asset:revolut-flexible", "asset"), fin.account(s, rv.BANK, "asset")
        fin.set_value(s, flex, Decimal("27.82"), "2026-11-05", "a")
        fin.post_entry(s, "2026-11-05", "To Flexible Cash Funds", [(flex.id, Decimal("2.00"), "EUR"), (banco.id, Decimal("-2.00"), "EUR")], "a")
        assert all(x["cuadra"] for x in fin.reconcile(s))
        assert fin.savings_view(s)["cuentas"][-1]["valorada"] == "2026-11-04"
