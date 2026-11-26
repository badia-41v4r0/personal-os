import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import maquinas  # noqa: E402
import maquinas_admin as ma  # noqa: E402


class FakeVBox:
    """VirtualBox simulado: dos VMs, una encendida con NAT y otra apagada sin NAT."""

    def __init__(self):
        self.vms = {"VerilUOC Desktop": {"VMState": "running", "nic1": "nat", "fwd": []},
                    "Sin red": {"VMState": "poweroff", "nic1": "none", "fwd": []}}
        self.snaps: set[str] = set()
        self.llamadas: list[tuple] = []

    def __call__(self, *args, timeout=60):
        self.llamadas.append(args)
        ok = lambda out=b"": subprocess.CompletedProcess(args, 0, out, b"")  # noqa: E731
        if args[0] == "--version":
            return ok(b"7.2.22r175245\n")
        if args[:2] == ("list", "vms"):
            return ok("".join(f'"{n}" {{4dab4486-25f4-4cf1-9545-04{i:010d}}}\n' for i, n in enumerate(self.vms)).encode())
        if args[0] == "showvminfo":
            v = self.vms.get(args[1])
            if v is None:
                return subprocess.CompletedProcess(args, 1, b"", b"not found")
            lines = [f'VMState="{v["VMState"]}"', f'nic1="{v["nic1"]}"'] + [f'Forwarding({i})="{f}"' for i, f in enumerate(v["fwd"])]
            return ok(("\n".join(lines) + "\n").encode())
        if args[0] == "snapshot" and args[2] == "list":
            return ok("".join(f'SnapshotName="{s}"\n' for s in self.snaps).encode())
        if args[0] == "snapshot" and args[2] == "take":
            self.snaps.add(args[3])
            return ok()
        if args[0] in ("controlvm", "modifyvm") and "natpf1" in args[2]:
            v = self.vms[args[1]]
            if args[3] == "delete":
                v["fwd"] = [f for f in v["fwd"] if not f.startswith(args[4] + ",")]
            else:
                v["fwd"].append(args[3])
            return ok()
        if args[0] == "controlvm" and args[2] == "resume":
            self.vms[args[1]]["VMState"] = "running"
            return ok()
        if args[0] == "startvm":
            self.vms[args[1]]["VMState"] = "running"
            return ok()
        return ok()


@pytest.fixture
def vb(tmp_path, monkeypatch):
    fake = FakeVBox()
    monkeypatch.setattr(maquinas, "vbox", fake)
    monkeypatch.setattr(ma, "puerto_libre", lambda usados: max([2221, *usados]) + 1)
    monkeypatch.delenv("POS_MAQUINAS", raising=False)
    data, secrets = tmp_path / "data", tmp_path / "secrets"
    data.mkdir()
    return fake, data, secrets


def test_estado_lista_vms_y_conectadas(vb):
    fake, data, secrets = vb
    e = ma.estado(data, secrets)
    assert e["virtualbox"]["instalado"] and [v["vbox"] for v in e["vms"]] == ["VerilUOC Desktop", "Sin red"]
    assert e["maquinas"] == [] and all(v["conectada"] is None for v in e["vms"])


def test_sin_virtualbox(tmp_path, monkeypatch):
    def nada(*a, **k):
        raise FileNotFoundError
    monkeypatch.setattr(maquinas, "vbox", nada)
    assert ma.estado(tmp_path, tmp_path) == {"virtualbox": {"instalado": False, "version": None}, "vms": [], "maquinas": []}


def test_preparar_crea_clave_redireccion_e_instantanea(vb):
    fake, data, secrets = vb
    r = ma.preparar(data, secrets, "VerilUOC Desktop", "VerilUOC (FC)")
    assert r["id"] == "veriluoc-fc" and r["puerto"] == 2222 and set(r["hecho"]) == {"instantánea", "clave", "redirección"}
    clave = secrets / "vm/veriluoc-fc_ed25519"
    assert clave.exists() and oct(clave.stat().st_mode & 0o777) == "0o600"
    pub = (secrets / "vm/veriluoc-fc_ed25519.pub").read_text().strip()
    assert pub in r["comandos"]["base"] and "PasswordAuthentication no" in r["comandos"]["base"]
    assert "pos-ssh,tcp,127.0.0.1,2222,,22" in fake.vms["VerilUOC Desktop"]["fwd"]
    assert ("controlvm", "VerilUOC Desktop", "natpf1", "pos-ssh,tcp,127.0.0.1,2222,,22") in fake.llamadas  # encendida: controlvm
    cfg = json.loads((data / "maquinas.json").read_text())
    assert oct((data / "maquinas.json").stat().st_mode & 0o777) == "0o600"
    m = cfg["maquinas"][0]
    assert m["usuario"] == "" and m["agentes"] == [] and m["clave"] == "vm/veriluoc-fc_ed25519"
    assert maquinas.cargar(data, secrets) == []  # pendiente: los agentes aún no la ven
    # repetir no duplica nada
    r2 = ma.preparar(data, secrets, "VerilUOC Desktop")
    assert r2["id"] == "veriluoc-fc" and r2["puerto"] == 2222 and r2["hecho"] == []
    assert len(json.loads((data / "maquinas.json").read_text())["maquinas"]) == 1


def test_preparar_rechaza(vb):
    fake, data, secrets = vb
    with pytest.raises(ValueError, match="NAT"):
        ma.preparar(data, secrets, "Sin red")
    with pytest.raises(ValueError, match="No existe"):
        ma.preparar(data, secrets, "Otra")
    with pytest.raises(ValueError):
        ma.preparar(data, secrets, "x; rm -rf /")


def test_asignar_solo_tras_probar_y_quitar(vb, monkeypatch):
    fake, data, secrets = vb
    mid = ma.preparar(data, secrets, "VerilUOC Desktop", "VerilUOC")["id"]
    with pytest.raises(ValueError, match="prueba"):
        ma.actualizar(data, mid, agentes=["tutor"])
    with pytest.raises(ValueError, match="usuario"):
        ma.probar(data, secrets, mid, "Root; id")

    def ssh(m, cmd, timeout=60, data=None):
        assert m["usuario"] == "mooccf" and m["puerto"] == 2222
        out = b"ok\n" if cmd == "echo ok" else b"GEO=1280 800\nNAV=/usr/bin/chromium\n"
        return subprocess.CompletedProcess([], 0, out, b"")
    monkeypatch.setattr(maquinas, "ssh", ssh)
    r = ma.probar(data, secrets, mid, "mooccf")
    assert r["ok"] and [p["ok"] for p in r["pasos"]] == [True, True, True] and "1280x800" in r["pasos"][1]["detalle"]
    ma.actualizar(data, mid, agentes=["tutor", "tutor"], notas="VerilUOC: java -jar …")
    m = maquinas.cargar(data, secrets)
    assert [x["id"] for x in m] == ["verilu" + "oc"] and m[0]["agentes"] == ["tutor"]
    with pytest.raises(ValueError):
        ma.actualizar(data, mid, agentes=["../x"])
    ma.quitar(data, secrets, mid)
    assert not (secrets / "vm/veriluoc_ed25519").exists() and fake.vms["VerilUOC Desktop"]["fwd"] == []
    assert json.loads((data / "maquinas.json").read_text())["maquinas"] == []
    with pytest.raises(KeyError):
        ma.quitar(data, secrets, mid)


def test_accion_reanuda_si_esta_en_pausa(vb):
    fake, data, secrets = vb
    mid = ma.preparar(data, secrets, "VerilUOC Desktop", instantanea=False)["id"]
    fake.vms["VerilUOC Desktop"]["VMState"] = "paused"
    ma.accion(data, mid, "encender")
    assert ("controlvm", "VerilUOC Desktop", "resume") in fake.llamadas and not any(a[0] == "startvm" for a in fake.llamadas)
    with pytest.raises(ValueError):
        ma.accion(data, mid, "borrar")


def test_slug():
    assert ma.slug("VerilUOC_Desktop_1025") == "veriluoc-desktop-1025"
    assert ma.slug("1234") == "vm" and ma.slug("Ñandú VM") == "nandu-vm" and ma.slug("Máquina de FC") == "maquina-de-fc"


def test_endpoints_del_host_agent(vb, monkeypatch):
    import importlib
    from fastapi.testclient import TestClient
    fake, data, secrets = vb
    monkeypatch.setenv("CC_HOSTAGENT_TOKEN", "t" * 40)
    monkeypatch.setenv("CC_DATA_DIR", str(data))
    monkeypatch.setenv("POS_SECRETS_DIR", str(secrets))
    import hostagent
    importlib.reload(hostagent)
    c, h = TestClient(hostagent.app), {"Authorization": "Bearer " + "t" * 40}
    assert c.get("/v1/maquinas").status_code == 401
    assert c.get("/v1/maquinas", headers=h).json()["virtualbox"]["instalado"]
    assert c.post("/v1/maquinas", json={"vbox": "Sin red"}, headers=h).status_code == 422
    r = c.post("/v1/maquinas", json={"vbox": "VerilUOC Desktop", "nombre": "VerilUOC", "instantanea": False}, headers=h)
    assert r.status_code == 200 and r.json()["id"] == "veriluoc"
    assert c.post("/v1/maquinas/otra/probar", json={"usuario": "x"}, headers=h).status_code == 404
    assert c.patch("/v1/maquinas/veriluoc", json={"agentes": ["tutor"]}, headers=h).status_code == 422  # sin probar
    assert c.patch("/v1/maquinas/veriluoc", json={"notas": "hola"}, headers=h).json() == {"ok": True}
    assert c.post("/v1/maquinas/veriluoc/accion", json={"que": "x"}, headers=h).status_code == 422
    assert c.delete("/v1/maquinas/veriluoc", headers=h).json() == {"ok": True}
    audit = (data / "hostagent-audit.jsonl").read_text()
    assert "maquinas.preparar" in audit and "maquinas.quitar" in audit and "BEGIN OPENSSH" not in audit
