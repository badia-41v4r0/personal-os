"""Clave de Enable Banking: solo el Host Agent la escribe, en secrets/<app id>.pem con permisos 600."""
import importlib
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi.testclient import TestClient

TOKEN = "t" * 40
APP = "35f441d9-cf1e-4916-b09e-b67748d0fb0f"
H = {"Authorization": f"Bearer {TOKEN}"}


def _pem(key) -> str:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()


@pytest.fixture()
def ha(tmp_path, monkeypatch):
    monkeypatch.setenv("CC_HOSTAGENT_TOKEN", TOKEN)
    monkeypatch.setenv("CC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("POS_SECRETS_DIR", str(tmp_path / "secrets"))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import hostagent
    importlib.reload(hostagent)
    return hostagent


def test_guarda_la_clave_con_permisos_600(ha, tmp_path):
    pem = _pem(rsa.generate_private_key(public_exponent=65537, key_size=2048))
    r = TestClient(ha.app).put("/v1/banco/clave", json={"app_id": APP, "pem": pem}, headers=H)
    assert r.status_code == 200 and r.json() == {"app_id": APP, "guardada": True}
    f = tmp_path / "secrets" / f"{APP}.pem"
    assert f.read_text().strip() == pem.strip() and oct(f.stat().st_mode & 0o777) == "0o600"
    assert pem not in (tmp_path / "data" / "hostagent-audit.jsonl").read_text()  # la auditoría nunca lleva la clave


@pytest.mark.parametrize("app_id,pem,error", [
    ("no-es-un-id", "x", "no son válidos"),
    (APP, "hola", "no es una clave privada"),
    (APP, _pem(ec.generate_private_key(ec.SECP256R1())), "RSA"),
])
def test_rechaza_lo_que_no_es_una_clave_rsa(ha, tmp_path, app_id, pem, error):
    r = TestClient(ha.app).put("/v1/banco/clave", json={"app_id": app_id, "pem": pem}, headers=H)
    assert r.status_code == 422 and error in r.json()["detail"]
    assert not (tmp_path / "secrets").exists() or not any((tmp_path / "secrets").iterdir())


def test_sin_token_no_se_guarda_nada(ha, tmp_path):
    assert TestClient(ha.app).put("/v1/banco/clave", json={"app_id": APP, "pem": "x"}).status_code == 401
