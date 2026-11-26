"""Soporte de uso: Jarvis busca y lee la documentación del Personal OS (solo la lista cerrada de documentos)."""
import pytest

from app.core import ayuda, gateway, orchestrator


def test_encuentra_como_configurar_opencode():
    hits = ayuda.buscar("cómo configuro opencode con mi clave")
    assert hits and hits[0]["doc"] == "motores-de-ia"
    assert any("opencode-go/" in h["texto"] for h in hits)


def test_indice_y_apartado():
    idx = {d["doc"]: d for d in ayuda.indice()}
    assert "motores-de-ia" in idx and "OpenCode" in idx["motores-de-ia"]["apartados"]
    r = ayuda.leer("motores-de-ia", "opencode")
    assert r["apartado"] == "OpenCode" and "Clave de OpenCode" in r["texto"]


@pytest.mark.parametrize("doc", ["registro", "auditoria-open-source", "../.env", "docs/registro.md", "/etc/passwd"])
def test_no_sale_de_la_lista(doc):
    with pytest.raises(ValueError, match="Disponibles"):
        ayuda.leer(doc)


def test_todos_los_documentos_existen():
    for doc, rel in ayuda.DOCS.items():
        assert (ayuda.ROOT / rel).is_file(), doc


def test_jarvis_la_tiene_por_la_pasarela(client):
    assert {"help.search", "help.read"} <= set(orchestrator.DEFAULT.tools)
    h = {"X-Run-Token": gateway.issue_token("r-ayuda", "jarvis", list(orchestrator.DEFAULT.tools), [])}
    r = client.post("/api/v1/internal/pos/call", json={"kind": "read", "name": "help.search", "args": {"q": "OpenRouter límite de gasto"}}, headers=h).json()
    assert r["result"][0]["doc"] == "motores-de-ia"
    r = client.post("/api/v1/internal/pos/call", json={"kind": "read", "name": "help.read", "args": {"doc": "../.env"}}, headers=h).json()
    assert "error" in r and "Disponibles" in r["error"]
