"""Host Agent: Constructor, vista previa y supervisor de cambios. Lo largo va en unidades aparte (aquí, sustituidas)."""
import importlib
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TOKEN = "t" * 40
H = {"Authorization": f"Bearer {TOKEN}"}
CONV = "11111111-2222-3333-4444-555555555555"
OTRA = "99999999-2222-3333-4444-555555555555"
RUN = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


@pytest.fixture()
def ha(tmp_path, monkeypatch):
    monkeypatch.setenv("CC_HOSTAGENT_TOKEN", TOKEN)
    monkeypatch.setenv("CC_DATA_DIR", str(tmp_path / "cc"))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import hostagent
    importlib.reload(hostagent)
    monkeypatch.setattr(hostagent, "CONSTR_DIR", tmp_path / "constructor")
    lanzadas: list[tuple] = []
    activas: set[str] = set()
    monkeypatch.setattr(hostagent, "_systemd_run", lambda nombre, script, *args: lanzadas.append((nombre, script, *args)))
    monkeypatch.setattr(hostagent, "_unidad_activa", lambda nombre: nombre in activas)
    monkeypatch.setattr(hostagent.shutil, "which", lambda n, *a, **k: f"/usr/bin/{n}")
    hostagent.lanzadas, hostagent.activas = lanzadas, activas
    return hostagent


def test_abrir_reserva_en_el_acto(ha):
    c = TestClient(ha.app)
    r = c.post("/v1/constructor/abrir", json={"conversacion": CONV}, headers=H)
    assert r.status_code == 200
    p = json.loads((ha.CONSTR_DIR / "personalizacion.json").read_text())
    assert p["conversacion"] == CONV and p["estado"] == "preparando"
    assert ha.lanzadas == [("vp-preparar", "vista_previa.py", "abrir", CONV)]
    # otra conversación no puede abrir otra vista previa
    assert c.post("/v1/constructor/abrir", json={"conversacion": OTRA}, headers=H).status_code == 409
    # la misma sí (reintento), sin lanzar otra preparación si ya hay una en marcha
    ha.activas.add("vp-preparar")
    assert c.post("/v1/constructor/abrir", json={"conversacion": CONV}, headers=H).status_code == 200
    assert len(ha.lanzadas) == 1


def test_abrir_valida(ha, monkeypatch):
    c = TestClient(ha.app)
    assert c.post("/v1/constructor/abrir", json={"conversacion": "../x"}, headers=H).status_code == 422
    assert c.post("/v1/constructor/abrir", json={"conversacion": CONV, "version": "1; rm"}, headers=H).status_code == 422
    assert c.post("/v1/constructor/abrir", json={"conversacion": CONV}).status_code == 401
    monkeypatch.setattr(ha.shutil, "which", lambda n, *a, **k: None)
    assert c.post("/v1/constructor/abrir", json={"conversacion": CONV}, headers=H).status_code == 503
    ha.activas.add("cambios")


def test_no_abre_mientras_se_aplica(ha):
    ha.activas.add("cambios")
    assert TestClient(ha.app).post("/v1/constructor/abrir", json={"conversacion": CONV}, headers=H).status_code == 409


def test_turno(ha):
    c = TestClient(ha.app)
    body = {"run_id": RUN, "prompt": "Cambia el saludo", "proveedor": "claude", "modelo": "opus", "resume": None}
    assert c.post("/v1/constructor/turno", json=body, headers=H).status_code == 409  # sin personalización
    c.post("/v1/constructor/abrir", json={"conversacion": CONV}, headers=H)
    assert c.post("/v1/constructor/turno", json=body, headers=H).status_code == 200
    req = json.loads((ha.CONSTR_DIR / "turnos" / f"{RUN}.json").read_text())
    assert req["prompt"] == "Cambia el saludo" and req["modelo"] == "opus"
    assert ("constructor", "constructor.py", "turno", RUN) in ha.lanzadas
    ha.activas.add("constructor")
    assert c.post("/v1/constructor/turno", json=body, headers=H).status_code == 409  # uno a la vez
    for malo in ({"proveedor": "antigravity"}, {"modelo": "haiku-evil"}, {"run_id": "x"}, {"resume": "no-uuid"}, {"prompt": " "}):
        assert c.post("/v1/constructor/turno", json={**body, **malo}, headers=H).status_code == 422, malo


def test_cambios_validan_y_lanzan_el_supervisor(ha):
    c = TestClient(ha.app)
    assert c.post("/v1/cambios/aplicar", json={}, headers=H).status_code == 409  # nada abierto
    c.post("/v1/constructor/abrir", json={"conversacion": CONV}, headers=H)
    assert c.post("/v1/cambios/aplicar", json={"titulo": "Saludo\n nuevo"}, headers=H).status_code == 200
    assert ha.lanzadas[-1] == ("cambios", "supervisor.py", "aplicar", "--titulo", "Saludo nuevo")
    assert c.post("/v1/cambios/deshacer", json={"commit": "abc1234"}, headers=H).status_code == 200
    assert ha.lanzadas[-1] == ("cambios", "supervisor.py", "deshacer", "abc1234")
    assert c.post("/v1/cambios/actualizar", json={"version": "0.2.0"}, headers=H).status_code == 200
    assert c.post("/v1/cambios/restaurar", json={"copia": "20261126-101010-aplicar", "vault": True}, headers=H).status_code == 200
    assert ha.lanzadas[-1] == ("cambios", "supervisor.py", "restaurar", "20261126-101010-aplicar", "--vault")
    for op, body in (("deshacer", {"commit": "HEAD; rm"}), ("actualizar", {"version": "main"}), ("restaurar", {"copia": "../../etc"})):
        assert c.post(f"/v1/cambios/{op}", json=body, headers=H).status_code == 422
    assert c.post("/v1/cambios/borrar-todo", json={}, headers=H).status_code == 404
    ha.activas.add("cambios")
    assert c.post("/v1/cambios/deshacer", json={"commit": "abc1234"}, headers=H).status_code == 409  # uno a la vez


def test_no_aplica_mientras_trabaja(ha):
    c = TestClient(ha.app)
    c.post("/v1/constructor/abrir", json={"conversacion": CONV}, headers=H)
    ha.activas.add("constructor")
    assert c.post("/v1/cambios/aplicar", json={}, headers=H).status_code == 409


def test_estado_sin_secretos(ha):
    ha.CONSTR_DIR.mkdir(parents=True)
    (ha.CONSTR_DIR / "personalizacion.json").write_text(json.dumps({"conversacion": CONV, "token": "secreto", "db_url": "postgresql://x"}))
    d = TestClient(ha.app).get("/v1/constructor", headers=H).json()
    assert d["personalizacion"] == {"conversacion": CONV} and d["bwrap"] is True
