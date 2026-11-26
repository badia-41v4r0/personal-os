"""OpenCode con sus dos servicios: clave de opencode.ai (Zen y Go) u OpenRouter. El prefijo del modelo decide cuál
entra en el turno, y solo esa."""
import importlib
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import proveedores  # noqa: E402

TOKEN = "t" * 40
H = {"Authorization": f"Bearer {TOKEN}"}
CLAVE_OC = "oc_sk_" + "a" * 30
CLAVE_OR = "sk-or-v1-" + "b" * 30


@pytest.fixture()
def ha(tmp_path, monkeypatch):
    monkeypatch.setenv("CC_HOSTAGENT_TOKEN", TOKEN)
    monkeypatch.setenv("CC_DATA_DIR", str(tmp_path))
    import hostagent
    importlib.reload(hostagent)
    return hostagent


@pytest.mark.parametrize("modelo,servicio", [
    ("opencode/claude-sonnet-5-5", "opencode"), ("opencode-go/kimi-k3", "opencode"), ("openrouter/a/b", "openrouter")])
def test_el_prefijo_decide_el_servicio(modelo, servicio):
    assert proveedores.servicio_opencode(modelo) == servicio


@pytest.mark.parametrize("modelo", ["", "kimi-k3", "anthropic/claude", "opencodex/a"])
def test_modelo_sin_prefijo_conocido(modelo):
    with pytest.raises(ValueError, match="opencode-go"):
        proveedores.servicio_opencode(modelo)


def test_config_trae_los_tres_proveedores_sin_claves_escritas(tmp_path):
    env = proveedores.preparar_home("opencode", tmp_path, {}, "read", "", {"opencode_key": CLAVE_OC})
    cfg = json.loads((tmp_path / ".config/opencode/opencode.json").read_text())
    assert set(cfg["provider"]) == {"opencode", "opencode-go", "openrouter"}
    assert CLAVE_OC not in json.dumps(cfg)
    assert env == {"OPENCODE_API_KEY": CLAVE_OC}  # la de OpenRouter no entra


def test_guardar_y_usar_cada_clave(ha):
    c = TestClient(ha.app)
    assert c.put("/v1/proveedores/opencode/clave", json={"clave": CLAVE_OR}, headers=H).status_code == 422  # campo equivocado
    assert c.put("/v1/proveedores/openrouter/clave", json={"clave": CLAVE_OC}, headers=H).status_code == 422
    assert c.put("/v1/proveedores/otra/clave", json={"clave": CLAVE_OC}, headers=H).status_code == 404
    r = c.put("/v1/proveedores/opencode/clave", json={"clave": CLAVE_OC}, headers=H).json()
    assert r["conectado"] and r["claves"] == {"opencode": True, "openrouter": False}
    f = ha._prov_file("opencode.key")
    assert f.read_text() == CLAVE_OC and f.stat().st_mode & 0o777 == 0o600

    assert ha.proveedores_credenciales("opencode", "opencode-go/kimi-k3") == {"opencode_key": CLAVE_OC}
    with pytest.raises(ValueError, match="OpenRouter"):
        ha.proveedores_credenciales("opencode", "openrouter/a/b")

    c.put("/v1/proveedores/openrouter/clave", json={"clave": CLAVE_OR}, headers=H)
    assert ha.proveedores_credenciales("opencode", "openrouter/a/b") == {"openrouter_key": CLAVE_OR}

    r = c.delete("/v1/proveedores/opencode/clave", headers=H).json()
    assert r["claves"] == {"opencode": False, "openrouter": True} and r["conectado"]
    r = c.delete("/v1/proveedores/opencode", headers=H).json()  # desconectar el motor borra las dos
    assert not r["conectado"]
