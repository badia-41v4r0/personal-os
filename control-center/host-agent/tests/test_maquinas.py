import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import maquinas  # noqa: E402


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    root = tmp_path / "pos"
    (root / "archivos/Uni").mkdir(parents=True)
    (root / "Jarvis-Vault/Uni").mkdir(parents=True)
    (root / "Jarvis-Vault/Uni/enunciado.txt").write_text("enunciado")
    secrets = root / "secrets"
    (secrets / "vm").mkdir(parents=True)
    (secrets / "vm/k").write_text("clave")
    data = root / "data"
    data.mkdir()
    base = {"id": "veriluoc", "vbox": "VerilUOC_Desktop_1025", "usuario": "mooccf", "puerto": 2222,
            "clave": "vm/k", "agentes": ["tutor"]}
    (data / "maquinas.json").write_text(json.dumps({"maquinas": [
        base,
        base | {"id": "fuera", "clave": "../../../etc/passwd"},      # clave fuera de secrets/: se ignora
        base | {"id": "mala", "usuario": "root; rm -rf /"},         # usuario raro: se ignora
        base | {"id": "Mayus"},                                     # id no válido
    ]}))
    monkeypatch.delenv("POS_MAQUINAS", raising=False)
    llamadas = []

    def fake_run(argv, **kw):
        llamadas.append(argv)
        if argv[0] == "VBoxManage" and argv[1] == "showvminfo":
            return subprocess.CompletedProcess(argv, 0, b'name="x"\nVMState="running"\n', b"")
        if argv[0] == "ssh":
            return subprocess.CompletedProcess(argv, 0, b"contenido", b"")
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(maquinas.subprocess, "run", fake_run)
    return root, data, secrets, llamadas


def test_carga_solo_maquinas_validas(entorno):
    root, data, secrets, _ = entorno
    ms = maquinas.cargar(data, secrets)
    assert [m["id"] for m in ms] == ["veriluoc"]
    assert maquinas.de_agente(ms, "tutor") and not maquinas.de_agente(ms, "jarvis") and not maquinas.de_agente(ms, None)


def test_sin_configuracion_no_hay_maquinas(tmp_path):
    assert maquinas.cargar(tmp_path, tmp_path) == []


def test_otro_agente_no_puede(entorno):
    root, data, secrets, llamadas = entorno
    r = maquinas.op([], "exec", {"command": "id"}, root, lambda *a, **k: None)
    assert "error" in r and not llamadas
    ms = maquinas.cargar(data, secrets)
    assert "error" in maquinas.op(ms, "exec", {"command": "id", "maquina": "otra"}, root, lambda *a, **k: None)
    assert maquinas.op(ms, "borrar_todo", {}, root, lambda *a, **k: None) == {"error": "Operación no permitida"}


def test_exec_va_por_ssh_a_localhost_con_su_clave(entorno):
    root, data, secrets, llamadas = entorno
    ms = maquinas.cargar(data, secrets)
    r = maquinas.op(ms, "exec", {"command": "echo hola"}, root, lambda *a, **k: None)
    assert r["codigo"] == 0
    ssh = next(a for a in llamadas if a[0] == "ssh")
    assert "mooccf@127.0.0.1" in ssh and str((secrets / "vm/k").resolve()) in ssh and "BatchMode=yes" in ssh
    assert ssh[1:3] == ["-F", "/dev/null"]  # sin la config. del sistema (en el servicio se ve con otro dueño)
    assert "echo hola" in ssh[-1] and "DISPLAY=:0" in ssh[-1]


def test_copias_solo_entre_entregables_y_vault(entorno):
    root, data, secrets, llamadas = entorno
    ms = maquinas.cargar(data, secrets)
    nada = lambda *a, **k: None  # noqa: E731
    for mal in ("/etc/passwd", "/entregables/../../secrets/vm/k", "/vault/../secrets/vm/k", "../x"):
        assert "error" in maquinas.op(ms, "copy_in", {"origen": mal}, root, nada)
    assert "error" in maquinas.op(ms, "copy_out", {"origen": "a", "destino": "/vault/Uni/x"}, root, nada)
    assert maquinas.op(ms, "copy_in", {"origen": "/vault/Uni/enunciado.txt"}, root, nada)["ok"]
    r = maquinas.op(ms, "copy_out", {"origen": "pec/x.circ", "destino": "/entregables/FC/PR/x.circ"}, root, nada)
    assert r["ok"] and (root / "archivos/Uni/FC/PR/x.circ").read_bytes() == b"contenido"
    assert "error" in maquinas.op(ms, "copy_out", {"origen": "pec/x.circ", "destino": "/entregables/FC/PR/x.circ"}, root, nada)


def test_navegador_solo_http_y_por_ssh(entorno):
    root, data, secrets, llamadas = entorno
    ms = maquinas.cargar(data, secrets)
    nada = lambda *a, **k: None  # noqa: E731
    for mal in ("file:///etc/passwd", "javascript:alert(1)", "chrome://settings", ""):
        assert "error" in maquinas.op(ms, "open_url", {"url": mal}, root, nada)
    assert not any(a[0] == "ssh" for a in llamadas)
    maquinas.op(ms, "open_url", {"url": "https://campus.example.edu/"}, root, nada)
    ssh = [a for a in llamadas if a[0] == "ssh"]
    assert "remote-debugging-port=9222" in ssh[0][-1] and "python3 - open https://campus.example.edu/" in ssh[1][-1]


def test_cdp_ws_frames():
    import vm_cdp
    ws = vm_cdp.WS.__new__(vm_cdp.WS)
    payload = json.dumps({"id": 1, "result": {"x": "a" * 70000}}).encode()
    ws.rest = bytes([0x81, 127]) + len(payload).to_bytes(8, "big") + payload
    assert ws.recv()["result"]["x"] == "a" * 70000


def test_en_pausa_se_reanuda(entorno, monkeypatch):
    root, data, secrets, llamadas = entorno
    real = maquinas.subprocess.run

    def pausada(argv, **kw):
        if argv[:2] == ["VBoxManage", "showvminfo"]:
            llamadas.append(argv)
            return subprocess.CompletedProcess(argv, 0, b'VMState="paused"\n', b"")
        return real(argv, **kw)

    monkeypatch.setattr(maquinas.subprocess, "run", pausada)
    r = maquinas.op(maquinas.cargar(data, secrets), "start", {}, root, lambda *a, **k: None)
    assert r["ok"]
    assert any(a[:2] == ["VBoxManage", "controlvm"] and "resume" in a for a in llamadas)
    assert not any("startvm" in a for a in llamadas)
