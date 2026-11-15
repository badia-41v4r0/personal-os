"""Filtro del proxy del ordenador del campus: solo los dominios permitidos (sin mitmproxy instalado: se simula el módulo)."""
import sys
import types
from pathlib import Path

import pytest

fake = types.ModuleType("mitmproxy")
fake.http = types.SimpleNamespace(HTTPFlow=object, Response=None)
sys.modules.setdefault("mitmproxy", fake)
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "virtual-computers/egress"))
import filtro as f  # noqa: E402

CAMPUS = ("ejemplo.edu", "du11hjcvx0uqb.cloudfront.net", "canvas-user-content.com")


@pytest.mark.parametrize("host", ["aula.ejemplo.edu", "id-provider.ejemplo.edu", "campus.ejemplo.edu", "ejemplo.edu", "EJEMPLO.EDU.",
                                  "du11hjcvx0uqb.cloudfront.net", "x.canvas-user-content.com"])
def test_dominios_permitidos(host):
    assert f.host_permitido(host, CAMPUS)


@pytest.mark.parametrize("host", ["google.com", "ejemplo.edu.evil.com", "evilejemplo.edu", "pastebin.com", "cloudfront.net", ""])
def test_dominios_no_permitidos(host):
    assert not f.host_permitido(host, CAMPUS)


def test_sin_lista_no_sale_nada(tmp_path, monkeypatch):
    monkeypatch.setattr(f, "ALLOW", tmp_path / "no-existe.json")
    assert f.permitidos() == () and not f.host_permitido("aula.ejemplo.edu")
