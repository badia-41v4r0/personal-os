import os
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app import db as dbm
from app.models import JournalEntry
from app.modules import finance as fin

MAPA = {"fecha": "Fecha", "descripcion": "Concepto", "importe": "Importe", "separador": ";", "coma_decimal": True}
CSV = "Fecha;Concepto;Importe\n01/11/2026;MERCADONA BCN;-45,30\n02/11/2026;NOMINA;1.500,00\n03/11/2026;CAFE;-1,50\n03/11/2026;CAFE;-1,50\n"


@pytest.fixture()
def cuentas(client, auth):
    for n, k in (("asset:banco", "asset"), ("expense:comida", "expense"), ("income:nomina", "income"), ("equity:apertura", "equity"), ("liability:tarjeta", "liability")):
        assert client.post("/api/v1/finance/accounts", json={"name": n, "kind": k}, headers=auth).status_code == 200
    return client


def asiento(c, auth, fecha="2026-11-01", importe="10.00", a="asset:banco", b="expense:comida"):
    return c.post("/api/v1/finance/entries", json={"fecha": fecha, "descripcion": "x", "lineas": [{"cuenta": a, "importe": f"-{importe}"}, {"cuenta": b, "importe": importe}]}, headers=auth)


def test_asiento_que_no_cuadra_se_rechaza(cuentas, auth):
    r = cuentas.post("/api/v1/finance/entries", json={"fecha": "2026-11-01", "descripcion": "x", "lineas": [{"cuenta": "asset:banco", "importe": "-10"}, {"cuenta": "expense:comida", "importe": "9.99"}]}, headers=auth)
    assert r.status_code == 422


def test_una_linea_sola_no_vale(cuentas, auth):
    r = cuentas.post("/api/v1/finance/entries", json={"fecha": "2026-11-01", "descripcion": "x", "lineas": [{"cuenta": "asset:banco", "importe": "0"}]}, headers=auth)
    assert r.status_code == 422


def test_saldos_y_patrimonio_exactos(cuentas, auth):
    cuentas.post("/api/v1/finance/entries", json={"fecha": "2026-11-01", "descripcion": "Apertura", "lineas": [{"cuenta": "asset:banco", "importe": "1000.10"}, {"cuenta": "equity:apertura", "importe": "-1000.10"}]}, headers=auth)
    assert asiento(cuentas, auth, importe="0.10").status_code == 200
    assert asiento(cuentas, auth, importe="0.20").status_code == 200
    v = {a["name"]: a["balance"] for a in cuentas.get("/api/v1/finance/accounts").json()}
    assert v["asset:banco"] == "999.80" and v["expense:comida"] == "0.30"  # sin error de coma flotante
    assert cuentas.get("/api/v1/finance/summary?mes=2026-11").json()["patrimonio"]["patrimonio"] == "999.80"


def test_la_base_impide_cambiar_un_asiento_confirmado(cuentas, auth):
    eid = asiento(cuentas, auth).json()["id"]
    for sql in (f"UPDATE journal_entries SET description='x2' WHERE id={eid}", f"DELETE FROM journal_entries WHERE id={eid}",
                f"UPDATE postings SET amount=999 WHERE entry_id={eid}", f"DELETE FROM postings WHERE entry_id={eid}"):
        with pytest.raises((IntegrityError, DBAPIError)):
            with dbm.session_scope() as s:
                s.execute(text(sql))


def test_corregir_es_revertir(cuentas, auth):
    eid = asiento(cuentas, auth).json()["id"]
    assert cuentas.post(f"/api/v1/finance/entries/{eid}/reverse", headers=auth).status_code == 200
    assert cuentas.post(f"/api/v1/finance/entries/{eid}/reverse", headers=auth).status_code == 409
    v = {a["name"]: a["balance"] for a in cuentas.get("/api/v1/finance/accounts").json()}
    assert v["asset:banco"] == "0.00"
    assert len(cuentas.get("/api/v1/finance/entries").json()) == 2  # el original sigue ahí


@pytest.mark.skipif(not os.environ.get("CC_DB_URL"), reason="requiere PostgreSQL")
def test_postgres_rechaza_descuadre_aunque_se_salte_el_codigo(cuentas, auth):
    with pytest.raises(DBAPIError):
        with dbm.session_scope() as s:
            e = JournalEntry(entry_date="2026-11-01", description="malo", status="pending")
            s.add(e)
            s.flush()
            s.execute(text("INSERT INTO postings (entry_id, account_id, amount, currency) VALUES (:e, 1, 5, 'EUR')"), {"e": e.id})


def body(**k):
    return {"cuenta": "asset:banco", "contenido": CSV, "mapa": MAPA, "filename": "b.csv"} | k


def test_importe_y_fecha_de_banco_espanol():
    assert fin.parse_amount("1.234,56 €", True) == Decimal("1234.56")
    assert fin.parse_amount("-1,50", True) == Decimal("-1.50")
    assert fin.parse_amount("1,234.56", False) == Decimal("1234.56")
    assert fin.parse_date("03/11/2026") == "2026-11-03"
    with pytest.raises(ValueError):
        fin.parse_amount("abc", True)


def test_importar_detecta_gemelos_y_no_duplica(cuentas, auth):
    p = cuentas.post("/api/v1/finance/import/preview", json=body(), headers=auth).json()
    assert p["filas"] == 4 and p["nuevos"] == 4 and p["errores"] == []
    r = cuentas.post("/api/v1/finance/import", json=body(), headers=auth).json()
    assert r["nuevos"] == 4  # dos cafés iguales son dos movimientos
    r2 = cuentas.post("/api/v1/finance/import", json=body(), headers=auth).json()
    assert r2["nuevos"] == 0 and r2["duplicados"] == 4


def test_csv_con_errores_no_importa_nada(cuentas, auth):
    malo = CSV + "fecha-mala;X;1,00\n"
    assert cuentas.post("/api/v1/finance/import", json=body(contenido=malo), headers=auth).status_code == 422
    assert cuentas.get("/api/v1/finance/entries").json() == []


def test_columna_que_falta(cuentas, auth):
    r = cuentas.post("/api/v1/finance/import/preview", json=body(mapa=MAPA | {"importe": "Cantidad"}), headers=auth)
    assert r.status_code == 422 and "Cantidad" in r.json()["detail"]


def test_reglas_categorizan_y_lo_dudoso_queda_por_revisar(cuentas, auth):
    cuentas.post("/api/v1/finance/rules", json={"patron": "mercadona", "cuenta": "expense:comida"}, headers=auth)
    r = cuentas.post("/api/v1/finance/import", json=body(), headers=auth).json()
    assert r["por_revisar"] == 3
    s = cuentas.get("/api/v1/finance/summary?mes=2026-11").json()
    assert s["resumen"]["gastos"] == "45.30" and s["por_revisar"] == 3  # lo pendiente no cuenta


def test_revisar_un_pendiente_lo_confirma(cuentas, auth):
    cuentas.post("/api/v1/finance/import", json=body(), headers=auth)
    p = cuentas.get("/api/v1/finance/entries?estado=pending").json()
    nomina = next(e for e in p if e["descripcion"] == "NOMINA")
    r = cuentas.post(f"/api/v1/finance/entries/{nomina['id']}/categorize", json={"cuenta": "income:nomina"}, headers=auth)
    assert r.json()["estado"] == "posted"
    assert cuentas.get("/api/v1/finance/summary?mes=2026-11").json()["resumen"]["ingresos"] == "1500.00"


def test_conciliacion_detecta_descuadre(cuentas, auth):
    cuentas.post("/api/v1/finance/entries", json={"fecha": "2026-11-01", "descripcion": "A", "lineas": [{"cuenta": "asset:banco", "importe": "100"}, {"cuenta": "equity:apertura", "importe": "-100"}]}, headers=auth)
    ok = cuentas.post("/api/v1/finance/assertions", json={"cuenta": "asset:banco", "fecha": "2026-11-02", "importe": "100"}, headers=auth).json()
    assert ok["cuadra"] is True
    mal = cuentas.post("/api/v1/finance/assertions", json={"cuenta": "asset:banco", "fecha": "2026-11-03", "importe": "90"}, headers=auth).json()
    assert mal["cuadra"] is False and mal["diferencia"] == "10.00"


def test_presupuesto_excedido(cuentas, auth):
    cuentas.post("/api/v1/finance/budgets", json={"cuenta": "expense:comida", "mes": "2026-11", "importe": "5"}, headers=auth)
    asiento(cuentas, auth, importe="10.00")
    assert cuentas.get("/api/v1/finance/summary?mes=2026-11").json()["presupuesto"][0]["excedido"] is True


def test_exporta_texto_plano(cuentas, auth):
    asiento(cuentas, auth)
    t = cuentas.get("/api/v1/finance/export.beancount").text
    assert "open Assets:Banco" in t and "Expenses:Comida  10.00 EUR" in t


def test_agente_nunca_escribe_sin_aprobacion(cuentas, auth):
    from app.core import actions
    r = actions.request("finance.entry.create", {"fecha": "2026-11-01", "descripcion": "x", "lineas": [{"cuenta": "asset:banco", "importe": "-1"}, {"cuenta": "expense:comida", "importe": "1"}]}, actor="finanzas")
    assert r["status"] == "pending"
    assert cuentas.get("/api/v1/finance/entries").json() == []
    assert actions.decide(r["id"], True, r["hash"], "ana")["status"] == "done"
    assert len(cuentas.get("/api/v1/finance/entries").json()) == 1


def test_no_existe_capacidad_de_mover_dinero(client):
    from app.core import actions
    assert not [c for c in actions.REGISTRY if any(x in c for x in ("transfer", "pago", "payment", "bizum"))]
