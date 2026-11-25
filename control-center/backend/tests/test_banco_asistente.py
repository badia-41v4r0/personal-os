"""Banco: asistente de configuración desde el panel y bancos que no son Revolut (sin red: la API se simula)."""
import json
from decimal import Decimal

from app import db as dbm
from app.modules import banco as bk
from app.modules import finance as fin

from .test_banco import api, saldo, tx  # noqa: F401  (api es una fixture)


def test_otro_banco_tiene_su_cuenta_y_reglas_genericas(api, config_instancia):  # noqa: F811
    (config_instancia / "finanzas.json").write_text(json.dumps({"pagadores_nomina": ["Empresa Ejemplo"]}))
    bk.elegir_banco("BBVA", "ES")
    bk._guardar(session_id="ses-2", valid_until="2099-01-01T00:00:00Z",
                cuentas=[{"uid": "eur-1", "moneda": "EUR"}, {"uid": "eur-2", "moneda": "EUR"}, {"uid": "usd", "moneda": "USD"}])
    assert [a["ledger"] for a in bk.cuentas()] == ["asset:bbva", "asset:bbva-2"]
    api.respuestas[("GET", "/accounts/eur-1/transactions")] = {"transactions": [
        tx("2026-02-01", "BIZUM ENVIADO A PEPE", "-10.00", "TRANSFER"),
        tx("2026-02-02", "TRANSFERENCIA NOMINA EMPRESA EJEMPLO SL", "1500.00", "TRANSFER"),
        tx("2026-02-03", "COMPRA TARJ. MERCADONA", "-30.00", ""),
        tx("2026-02-04", "Algo raro", "-5.00", "")]}
    api.respuestas[("GET", "/accounts/eur-2/transactions")] = {"transactions": []}
    api.respuestas[("GET", "/accounts/eur-1/balances")] = {"balances": [
        {"balance_type": "ITAV", "balance_amount": {"amount": "1.00"}}, {"balance_type": "CLBD", "balance_amount": {"amount": "1455.00"}}]}
    api.respuestas[("GET", "/accounts/eur-2/balances")] = {"balances": [{"balance_type": "CLBD", "balance_amount": {"amount": "0.00"}}]}
    with dbm.session_scope() as s:
        r = bk.sincronizar(s)
    assert r["nuevos"] == 4 and r["por_revisar"] == 1 and r["saldos"] == {"asset:bbva": "1455.00", "asset:bbva-2": "0.00"}
    assert saldo("asset:bbva") == Decimal("1455.00") and saldo("expense:bizum", False) == Decimal("10.00")
    assert saldo("income:nomina") == Decimal("-1500.00") and saldo("expense:comida") == Decimal("30.00")
    with dbm.session_scope() as s:
        assert all(x["cuadra"] for x in fin.reconcile(s))  # saldo contable: lo que declara el banco, sin sumar pendientes


def test_cambiar_de_banco_olvida_la_conexion(api):  # noqa: F811
    bk._guardar(session_id="ses-1", cuentas=[{"uid": "eur-1", "moneda": "EUR"}], alias={"x": "y"})
    e = bk.elegir_banco("BBVA", "ES")
    assert e["banco"] == "BBVA" and not e["conectado"] and bk.cfg()["alias"] == {}


def test_extracto_generico_despues_de_la_api_no_duplica(api, auth, client):  # noqa: F811
    bk.elegir_banco("BBVA", "ES")
    with dbm.session_scope() as s:
        bk.importar(s, [tx("2026-03-02", "COMPRA MERCADONA", "-11.49")], None, "2026-03-01", "asset:bbva")
    mapa = {"fecha": "Fecha", "descripcion": "Concepto", "importe": "Importe", "separador": ";", "coma_decimal": True}
    texto = "Fecha;Concepto;Importe\n02/03/2026;Mercadona;-11,49\n05/03/2026;Otra cosa;-3,00\n"
    r = client.post("/api/v1/finance/import", json={"cuenta": "asset:bbva", "contenido": texto, "mapa": mapa}, headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["nuevos"] == 1 and r.json()["duplicados"] == 1


def test_comprobar_la_aplicacion(api):  # noqa: F811
    api.respuestas[("GET", "/application")] = {"environment": "SANDBOX", "active": False, "redirect_urls": []}
    a = bk.aplicacion()
    assert len(a["problemas"]) == 3 and "Sandbox" in a["problemas"][0]


def test_si_la_vuelta_no_esta_registrada_se_pega_la_direccion(api, auth, client):  # noqa: F811
    r = client.post("/api/v1/finance/banco/conectar", json={"redirect_url": "http://127.0.0.1:8770/finanzas/banco"}, headers=auth).json()
    assert r["pegar"] and r["redirect_url"] == "https://pc.ts.net:8770/finanzas/banco"
    state = next(c[2] for c in api if c[1] == "/auth")["state"]
    url = f"https://pc.ts.net:8770/finanzas/banco?state={state}&code=codigo-123"
    e = client.post("/api/v1/finance/banco/vuelta", json={"url": url}, headers=auth).json()
    assert e["conectado"] and e["cuentas"] == [{"nombre": "", "iban": "", "ledger": "asset:revolut"}] and e["otras_divisas"] == ["HUF"]
    mal = client.post("/api/v1/finance/banco/vuelta", json={"url": "https://x/finanzas/banco?error=access_denied"}, headers=auth)
    assert mal.status_code == 502 and "no dio el permiso" in mal.json()["detail"]


def test_sin_la_vuelta_registrada_explica_que_anadir(api, auth, client):  # noqa: F811
    api.respuestas[("GET", "/application")]["redirect_urls"] = ["https://otra.cosa/callback"]
    r = client.post("/api/v1/finance/banco/conectar", json={"redirect_url": "http://127.0.0.1:8770/finanzas/banco"}, headers=auth)
    assert r.status_code == 502 and "http://127.0.0.1:8770/finanzas/banco" in r.json()["detail"]


def test_subir_la_clave_la_guarda_el_host_agent(api, auth, client, monkeypatch):  # noqa: F811
    from app.adapters import hostagent
    llamadas = []

    async def falsa(path, method="GET", json=None, **k):
        llamadas.append((path, method, json))
        return {"guardada": True}
    monkeypatch.setattr(hostagent, "call", falsa)
    app_id = "35f441d9-cf1e-4916-b09e-b67748d0fb0f"
    pem = "contenido-del-pem-de-prueba"  # el backend no la interpreta: la valida el Host Agent
    r = client.post("/api/v1/finance/banco/app", json={"app_id": app_id, "pem": pem}, headers=auth)
    assert r.status_code == 200 and r.json()["app_id"] == app_id
    assert llamadas == [("/v1/banco/clave", "PUT", {"app_id": app_id, "pem": pem})]
    assert "pem" not in bk.cfg()  # la clave nunca se guarda en la configuración


def test_saldo_contable_antes_que_disponible():
    assert bk._saldo([{"balance_type": "ITAV", "balance_amount": {"amount": "5"}},
                      {"balance_type": "CLBD", "balance_amount": {"amount": "9"}}]) == (Decimal("9"), True)
    assert bk._saldo([{"balance_type": "ITAV", "balance_amount": {"amount": "5"}}]) == (Decimal("5"), False)
    assert bk._saldo([]) is None
