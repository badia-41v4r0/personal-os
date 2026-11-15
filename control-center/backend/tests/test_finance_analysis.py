from app.core import actions, gateway, orchestrator as orq
from app.modules import finance as fin


def test_el_ultimo_analisis_es_el_que_se_ve(client, auth):
    assert client.get("/api/v1/finance/analysis").json()["texto"] is None
    for t in ("Primer análisis con suficiente texto para guardarse.", "Segundo análisis con suficiente texto para guardarse."):
        assert actions.request("finance.analysis.save", {"texto": t}, actor="finanzas")["status"] == "done"
    assert client.get("/api/v1/finance/analysis").json()["texto"].startswith("Segundo")


def test_analisis_vacio_o_enorme_falla(client):
    assert actions.request("finance.analysis.save", {"texto": "corto"}, actor="finanzas")["status"] == "failed"
    assert actions.request("finance.analysis.save", {"texto": "x" * 5000}, actor="finanzas")["status"] == "failed"


def test_resumen_anual_separa_bizum_y_agrega(client, auth):
    for n, k in (("asset:banco", "asset"), ("expense:comida", "expense"), ("expense:restaurantes", "expense"), ("expense:bizum", "expense"), ("income:nomina", "income"), ("income:bizum", "income")):
        client.post("/api/v1/finance/accounts", json={"name": n, "kind": k}, headers=auth)

    def entry(fecha, cuenta, importe, desc="x"):
        client.post("/api/v1/finance/entries", json={"fecha": fecha, "descripcion": desc, "lineas": [{"cuenta": "asset:banco", "importe": f"{-importe}"}, {"cuenta": cuenta, "importe": f"{importe}"}]}, headers=auth)
    entry("2026-03-02", "income:nomina", -1000)
    entry("2026-03-03", "income:bizum", -50)
    entry("2026-03-04", "expense:bizum", 20)
    entry("2026-03-06", "expense:restaurantes", 30, "Bar (1000.00 HUF)")  # viernes
    entry("2026-03-09", "expense:restaurantes", 10, "Bar")  # lunes
    d = client.get("/api/v1/finance/overview?año=2026").json()
    m = d["meses"][0]
    assert m["ingresos"] == "1000.00" and m["gastos"] == "40.00" and m["bizum_recibido"] == "50.00" and m["bizum_enviado"] == "20.00"
    assert d["mayores_comercios"][0] == {"comercio": "Bar", "total": "40.00", "veces": 2}
    assert d["restaurantes_y_ocio"] == {"viernes_a_domingo": "30.00", "lunes_a_jueves": "10.00"}


def test_solo_finanzas_publica_analisis():
    assert "finance.analysis.save" in orq.SECTIONS["finanzas"].capabilities
    assert not [k for k, s in orq.SECTIONS.items() if k != "finanzas" and "finance.analysis.save" in s.capabilities]
    assert "finance.overview" in gateway.TOOLS and fin.ANALYSIS_PROMPT
