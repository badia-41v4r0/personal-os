import pytest

from app import db as dbm
from app.models import JournalEntry
from app.modules import finance as fin
from app.modules import revolut as rv

H = ",".join(rv.HEADER) + "\n"


def csv(*rows):
    return "﻿" + H + "".join(",".join(map(str, r)) + "\n" for r in rows)


def r(tipo, fecha, desc, imp, fee, saldo, estado="COMPLETED"):
    return (tipo, "Current", f"{fecha} 10:00:00", f"{fecha} 10:00:01" if estado == "COMPLETED" else "", desc, imp, fee, "EUR", estado, saldo)


EXTRACTO = csv(
    r("Deposit", "2026-01-07", "Payment from EMPRESA EJEMPLO SL", "1000.00", "0.00", "1000.00"),
    r("Card Payment", "2026-01-08", "La Pepa Restaurante", "-10.50", "0.00", "989.50"),
    r("Transfer", "2026-01-09", "To EUR Flexible Cash Funds", "-100.00", "0.00", "889.50"),
    r("Transfer", "2026-01-10", "From EUR Flexible Cash Funds", "40.00", "0.00", "929.50"),
    r("Exchange", "2026-01-11", "Transfer to Revolut Digital Assets Europe Ltd", "-5.00", "0.00", "924.50"),
    r("Deposit", "2026-02-01", "Money added via BIZUM", "20.00", "0.00", "944.50"),
    r("Transfer", "2026-02-02", "Bizum payment to: Pol B.M.", "-5.00", "0.00", "939.50"),
    r("Charge", "2026-02-03", "Plan", "0.00", "15.99", "923.51"),
    r("Card Payment", "2026-02-04", "Comercio Rarísimo", "-7.00", "0.00", "916.51"),
    r("Card Payment", "2026-02-05", "Cabify", "-8.17", "0.00", "", "REVERTED"),
)


@pytest.fixture()
def hecho(client):
    with dbm.session_scope() as s:
        return rv.apply(s, EXTRACTO, "e.csv", "ana")


def saldo(nombre):
    with dbm.session_scope() as s:
        return fin.balance(s, fin.account(s, nombre).id)


def test_detecta_el_formato():
    assert rv.is_revolut(EXTRACTO) and not rv.is_revolut("Fecha;Concepto\n")


def test_el_saldo_del_ledger_es_el_del_banco(hecho):
    with dbm.session_scope() as s:
        total = fin.balance(s, fin.account(s, rv.BANK).id, include_pending=True)
    assert fin.money(total) == "916.51" == hecho["saldo_final"]


def test_revertidos_no_cuentan(hecho):
    assert hecho["ignorados"][0]["estado"] == "REVERTED" and hecho["nuevos"] == 9


BASE = [r("Deposit", "2026-11-01", "Payment from EMPRESA EJEMPLO SL", "100.00", "0.00", "100.00")]
PENDIENTE = csv(*BASE, r("Card Payment", "2026-11-05", "Cabify", "-25.72", "0.00", "", "PENDING"))


def test_pendiente_ya_no_esta_disponible(client):
    with dbm.session_scope() as s:
        x = rv.apply(s, PENDIENTE, "e", "a")
        assert fin.money(fin.balance(s, fin.account(s, rv.BANK).id)) == "74.28"
        assert all(c["cuadra"] for c in fin.reconcile(s))
    assert x["saldo_final"] == "74.28"


def test_pendiente_que_se_completa_no_se_duplica(client):
    with dbm.session_scope() as s:
        rv.apply(s, PENDIENTE, "e", "a")
    t = csv(*BASE, ("Card Payment", "Current", "2026-11-05 10:00:00", "2026-11-06 09:00:00", "Cabify", "-25.72", "0.00", "EUR", "COMPLETED", "74.28"))
    with dbm.session_scope() as s:
        assert rv.apply(s, t, "e", "a")["nuevos"] == 0
        assert fin.money(fin.balance(s, fin.account(s, rv.BANK).id)) == "74.28"
        assert all(c["cuadra"] for c in fin.reconcile(s))


def test_pendiente_que_se_revierte_se_anula(client):
    with dbm.session_scope() as s:
        rv.apply(s, PENDIENTE, "e", "a")
    t = csv(*BASE, r("Card Payment", "2026-11-05", "Cabify", "-25.72", "0.00", "", "REVERTED"))
    with dbm.session_scope() as s:
        rv.apply(s, t, "e", "a")
        rv.apply(s, t, "e", "a")  # dos veces no lo revierte dos veces
        assert fin.money(fin.balance(s, fin.account(s, rv.BANK).id)) == "100.00"


def test_saldo_en_la_cuenta_es_la_del_dia_a_dia(client, auth, hecho):
    client.post("/api/v1/finance/value", json={"cuenta": "asset:revolut-cripto", "valor": "0"}, headers=auth)
    assert client.get("/api/v1/finance/summary").json()["conciliadas"][0]["name"] == rv.BANK


def test_mover_dinero_propio_no_es_gasto_ni_ingreso(hecho):
    with dbm.session_scope() as s:
        m = fin.month_summary(s, "2026-01")
    assert m["ingresos"] == "1000.00" and m["gastos"] == "10.50"
    assert fin.money(saldo("asset:revolut-flexible")) == "60.00" and fin.money(saldo("asset:revolut-cripto")) == "5.00"


def test_comision_y_bizum(hecho):
    with dbm.session_scope() as s:
        m = fin.month_summary(s, "2026-02")
    assert m["por_categoria"][rv.FEES] == "15.99" and m["por_categoria"]["expense:bizum"] == "5.00" and m["ingresos"] == "20.00"


def test_lo_pendiente_cuenta_en_el_saldo_y_concilia(hecho):
    with dbm.session_scope() as s:
        assert all(x["cuadra"] for x in fin.reconcile(s))
        assert [a for a in fin._accounts_view(s) if a["name"] == rv.BANK][0]["balance"] == "916.51"


def test_lo_dudoso_queda_por_revisar_y_no_cuenta(hecho):
    assert hecho["por_revisar"] == 1
    with dbm.session_scope() as s:
        assert "7.00" not in fin.month_summary(s, "2026-02")["por_categoria"].values()


def test_reimportar_no_duplica(hecho):
    with dbm.session_scope() as s:
        r2 = rv.apply(s, EXTRACTO, "e.csv", "ana")
    assert r2["nuevos"] == 0 and r2["duplicados"] == 9


def test_gemelos_exactos_son_dos(client):
    t = csv(r("Card Payment", "2026-01-08", "Caprabo", "-1.00", "0.00", "-1.00"), r("Card Payment", "2026-01-08", "Caprabo", "-1.00", "0.00", "-2.00"))
    with dbm.session_scope() as s:
        assert rv.apply(s, t, "e", "a")["nuevos"] == 2


def test_saldo_roto_no_importa_nada(client):
    t = csv(r("Card Payment", "2026-01-08", "Caprabo", "-1.00", "0.00", "99.00"), r("Card Payment", "2026-01-09", "Caprabo", "-1.00", "0.00", "50.00"))
    with pytest.raises(Exception) as e, dbm.session_scope() as s:
        rv.apply(s, t, "e", "a")
    assert e.value.status_code == 422


def test_moneda_mezclada_se_rechaza(client):
    t = EXTRACTO.replace("EUR,COMPLETED", "USD,COMPLETED", 1)
    with pytest.raises(Exception):
        rv.parse(t)


def fx_row(tipo, fecha, desc, imp, fee, saldo):
    return (tipo, "Current", f"{fecha} 10:00:00", f"{fecha} 10:00:01", desc, imp, fee, "HUF", "COMPLETED", saldo)


EUR_VIAJE = csv(r("Deposit", "2026-09-01", "Payment from EMPRESA EJEMPLO SL", "500.00", "0.00", "500.00"),
                r("Exchange", "2026-09-03", "Exchanged to HUF", "-100.00", "0.00", "400.00"))
HUF = csv(fx_row("Exchange", "2026-09-03", "Exchanged to HUF", "36000.00", "0.00", "36000.00"),
          fx_row("Card Payment", "2026-09-04", "SPAR Food & Fuel", "-3600.00", "0.00", "32400.00"),
          fx_row("Card Payment", "2026-09-04", "Comercio Raro", "-1800.00", "0.00", "30600.00"),
          fx_row("Exchange", "2026-09-04", "Exchanged to EUR", "-158.00", "0.00", "30442.00"))


def test_gasto_en_divisa_al_tipo_pagado(client):
    with dbm.session_scope() as s:
        rv.apply(s, EUR_VIAJE, "e", "a")
        r2 = rv.apply(s, HUF, "h", "a")
    assert r2["moneda"] == "HUF" and r2["nuevos"] == 2 and r2["por_revisar"] == 1
    with dbm.session_scope() as s:
        m = fin.month_summary(s, "2026-09")
        e = s.query(JournalEntry).filter(JournalEntry.description.like("SPAR%")).one()
    assert m["por_categoria"]["expense:comida"] == "10.00"  # 100 € por 36.000 HUF
    assert e.description == "SPAR Food & Fuel (3600.00 HUF)"


def test_reimportar_divisa_no_duplica(client):
    with dbm.session_scope() as s:
        rv.apply(s, EUR_VIAJE, "e", "a")
        rv.apply(s, HUF, "h", "a")
        r2 = rv.apply(s, HUF, "h", "a")
    assert r2["nuevos"] == 0 and r2["duplicados"] == 2


def test_cuenta_puente_no_apunta_nada(client):
    t = csv(("Exchange", "Current", "2026-02-03 10:00:00", "2026-02-03 10:00:01", "Exchanged to CNY", "100.00", "0.00", "CNY", "COMPLETED", "100.00"),
            ("Exchange", "Current", "2026-02-03 10:00:00", "2026-02-03 10:00:01", "Exchanged to USD", "-100.00", "0.00", "CNY", "COMPLETED", "0.00"))
    with dbm.session_scope() as s:
        assert rv.apply(s, t, "c", "a")["nuevos"] == 0


def test_entrada_sin_salida_de_euros_viene_de_inversion(client):
    t = csv(fx_row("Exchange", "2026-09-03", "Exchanged to HUF", "36000.00", "0.00", "36000.00"), fx_row("Exchange", "2026-09-08", "Exchanged to HUF", "3600.00", "0.00", "39600.00"))
    with dbm.session_scope() as s:
        rv.apply(s, EUR_VIAJE, "e", "a")
        rv.apply(s, t, "h", "a")
    assert fin.money(saldo(rv.SOLD)) == "-10.00" and fin.money(saldo(rv.FX)) == "110.00"


def test_concilia_cada_fin_de_mes(hecho):
    with dbm.session_scope() as s:
        c = fin.reconcile(s)
    assert {x["fecha"] for x in c} == {"2026-01-11", "2026-02-03"}  # el último, como cierre del día anterior
    assert all(x["cuadra"] for x in c)


@pytest.mark.parametrize("desc,cuenta", [("Uber Eats", "expense:restaurantes"), ("Uber", "expense:transporte"), ("Estanco", "expense:tabaco"), ("Spotify", "expense:suscripciones"),
                                         ("Zara", "expense:ropa"), ("UOC (Universitat Oberta de Catalunya)", "expense:educacion"), ("Sala Apolo", "expense:ocio"),
                                         ("Caprabo", "expense:comida"), ("Bar Stop", "expense:restaurantes"), ("Taxi Lic.1769", "expense:transporte"), ("Algo Desconocido", None)])
def test_reglas(desc, cuenta):
    assert rv.classify({"descripcion": desc, "tipo": "Card Payment", "importe": -1}) == cuenta


@pytest.mark.parametrize("desc", ["Open banking deposit", "Deposit", "Apple Pay deposit by *1234"])
def test_deposito_sin_nombre_no_se_asume(desc):
    assert rv.classify({"descripcion": desc, "tipo": "Deposit", "importe": 50}) is None


def test_lo_ensenado_manda_sobre_la_regla():
    assert rv.classify({"descripcion": "Uber", "tipo": "Card Payment", "importe": -1}, [("uber", "expense:ocio")]) == "expense:ocio"


def test_recordar_categoriza_los_demas_y_lo_proximo(client, auth):
    t = csv(r("Card Payment", "2026-01-08", "Comercio Nuevo", "-1.00", "0.00", "-1.00"), r("Card Payment", "2026-01-09", "Comercio Nuevo", "-2.00", "0.00", "-3.00"))
    client.post("/api/v1/finance/import/revolut", json={"contenido": t}, headers=auth)
    p = client.get("/api/v1/finance/entries?estado=pending").json()
    assert len(p) == 2
    x = client.post(f"/api/v1/finance/entries/{p[0]['id']}/categorize", json={"cuenta": "expense:ocio", "recordar": True}, headers=auth).json()
    assert x["otros"] == 1 and client.get("/api/v1/finance/entries?estado=pending").json() == []
    t2 = csv(r("Card Payment", "2026-02-08", "Comercio Nuevo", "-1.00", "0.00", "-4.00"))
    assert client.post("/api/v1/finance/import/revolut", json={"contenido": t2}, headers=auth).json()["por_revisar"] == 0


def test_poner_el_valor_real_de_una_cuenta(client, auth, hecho):
    assert client.get("/api/v1/finance/savings").json()["patrimonio"] is None  # hay cuentas sin valor real
    r2 = client.post("/api/v1/finance/value", json={"cuenta": "asset:revolut-flexible", "valor": "75.50"}, headers=auth).json()
    assert r2["ajuste"] == "15.50"
    with dbm.session_scope() as s:
        assert fin.month_summary(s, "2026-11")["ingresos"] == "0.00"  # revalorizar no es un ingreso
    assert fin.money(saldo("asset:revolut-flexible")) == "75.50"


def test_con_todo_valorado_hay_patrimonio(client, auth, hecho):
    client.post("/api/v1/finance/value", json={"cuenta": "asset:revolut-flexible", "valor": "0"}, headers=auth)
    client.post("/api/v1/finance/value", json={"cuenta": "asset:revolut-cripto", "valor": "0"}, headers=auth)
    assert client.get("/api/v1/finance/savings").json()["patrimonio"] == "916.51"


def test_solo_se_valoran_activos(client, auth, hecho):
    assert client.post("/api/v1/finance/value", json={"cuenta": "expense:ocio", "valor": "1"}, headers=auth).status_code == 422


def test_devolucion_vuelve_a_su_categoria():
    assert rv.classify({"descripcion": "Refund Recibo VivaGym", "tipo": "TRANSFER_CHARGEBACK", "importe": 30}) == "expense:deporte"


def test_por_la_api(client, auth):
    b = {"contenido": EXTRACTO, "filename": "e.csv"}
    assert client.post("/api/v1/finance/import/revolut/preview", json=b, headers=auth).json()["nuevos"] == 9
    assert client.post("/api/v1/finance/import/revolut", json=b, headers=auth).json()["nuevos"] == 9


import pytest


@pytest.fixture(autouse=True)
def _nombre_completo(config_instancia):
    (config_instancia / "perfil.json").write_text('{"nombre_completo": "Ana Prueba"}')
    (config_instancia / "finanzas.json").write_text('{"pagadores_nomina": ["empresa ejemplo"]}')
