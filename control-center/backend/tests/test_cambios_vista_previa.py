"""Vista previa (control-center/cambios/vista_previa.py) y turno del Constructor (constructor.py): lo que se copia, lo
que nunca, el encierro y el entorno limpio."""
import importlib
import sqlite3
import sys
from pathlib import Path

import pytest

CAMBIOS = Path(__file__).resolve().parents[2] / "cambios"


@pytest.fixture()
def vp(tmp_path, monkeypatch):
    root = tmp_path / "pos"
    cc = root / "data/control-center"
    (cc / "proveedores").mkdir(parents=True)
    (cc / "proveedores/openrouter.key").write_text("sk-or-secreta")
    (cc / "secrets.env").write_text("CC_HOSTAGENT_TOKEN=" + "h" * 40 + "\nCC_BACKUP_KEY=clave\nCC_ALLOWED_ORIGINS=http://127.0.0.1:8770\nCC_TMDB_TOKEN=tmdb\n")
    (cc / "secrets.env.bak-1").write_text("viejo")
    (cc / "vapid.pem").write_text("privada")
    (cc / "backups/x").mkdir(parents=True)
    (cc / "ocio/w92").mkdir(parents=True)
    (cc / "ocio/w92/a.jpg").write_text("img")
    (cc / "fuente-gym-bd").write_text("1")
    with sqlite3.connect(cc / "cc.db") as c:
        c.execute("create table t (x)")
        c.execute("insert into t values ('real')")
    (root / "data/config").mkdir()
    (root / "data/config/modulos.json").write_text('{"activos": ["gym"]}')
    (root / "data/config/banco.json").write_text('{"session_id": "secreto"}')
    (root / "Jarvis-Vault/Jarvis").mkdir(parents=True)
    (root / "Jarvis-Vault/Jarvis/nota.md").write_text("nota")
    (root / ".env").write_text("POS_INSTANCE=pruebacc\nPOS_PORT=59990\nCLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat-secreto\n")
    monkeypatch.setenv("POS_ROOT", str(root))
    monkeypatch.setenv("POS_INSTANCE", "pruebacc")
    for k in ("CC_DB_URL", "CC_DATA_DIR", "CC_VAULT", "POS_CONFIG_DIR"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.syspath_prepend(str(CAMBIOS))
    for m in ("comun", "vista_previa", "constructor"):
        sys.modules.pop(m, None)
    return importlib.import_module("vista_previa")


def test_copia_de_datos_sin_secretos(vp):
    vp.copiar_datos()
    d = vp.C.DATOS_VP
    with sqlite3.connect(d / "control-center/cc.db") as c:
        assert c.execute("select x from t").fetchone()[0] == "real"
    assert (d / "vault/Jarvis/nota.md").read_text() == "nota"
    assert (d / "config/modulos.json").exists() and not (d / "config/banco.json").exists()
    assert (d / "control-center/ocio/w92/a.jpg").exists() and (d / "control-center/fuente-gym-bd").exists()
    for secreto in ("secrets.env", "secrets.env.bak-1", "vapid.pem", "proveedores", "backups"):
        assert not (d / "control-center" / secreto).exists(), secreto
    # escribir en la copia no toca lo real
    with sqlite3.connect(d / "control-center/cc.db") as c:
        c.execute("update t set x = 'vista previa'")
    with sqlite3.connect(vp.C.DATA / "control-center/cc.db") as c:
        assert c.execute("select x from t").fetchone()[0] == "real"


def test_entorno_limpio(vp):
    env = vp.entorno_vp({"token": "t" * 40})
    assert env["CC_VISTA_PREVIA"] == "1" and env["CC_MONITOR"] == "0" and env["CC_HOSTAGENT_TOKEN"] == ""
    assert env["CC_DATA_DIR"].startswith(str(vp.C.DATOS_VP)) and env["CC_VAULT"].startswith(str(vp.C.DATOS_VP))
    assert env["CC_ALLOWED_ORIGINS"] == "http://127.0.0.1:8770"
    todo = " ".join(env.values())
    for secreto in ("clave", "tmdb", "sk-ant-oat-secreto", "h" * 40):
        assert secreto not in todo


def test_jaula_oculta_la_instalacion(vp):
    argv = vp.jaula(["uvicorn"], escritura=[vp.C.DATOS_VP], lectura=[vp.C.COPIA], chdir=vp.C.COPIA)
    s = " ".join(argv)
    assert argv[:5] == ["bwrap", "--ro-bind", "/", "/", "--dev"]
    i = argv.index(str(vp.C.ROOT))
    assert argv[i - 1] == "--tmpfs"                                   # la instalación real no existe dentro…
    assert argv.index(str(vp.C.COPIA)) > i and argv.index(str(vp.C.DATOS_VP)) > i  # …salvo lo que se monta después
    assert f"--bind {vp.C.DATOS_VP} {vp.C.DATOS_VP}" in s and f"--ro-bind {vp.C.COPIA} {vp.C.COPIA}" in s
    assert "--die-with-parent" in argv and argv[-2:] == ["--", "uvicorn"]


def test_no_abre_una_segunda(vp):
    vp.C.escribir_json(vp.C.ABIERTA, {"conversacion": "una", "estado": "lista", "token": "x"})
    with pytest.raises(vp.Fallo) as e:
        vp.abrir("otra")
    assert e.value.codigo == "ocupada"


def test_cerrar_borra_la_copia(vp, monkeypatch):
    monkeypatch.setattr(vp, "_parar", lambda n: None)
    vp.C.COPIA.mkdir(parents=True)
    vp.C.DATOS_VP.mkdir(parents=True)
    vp.C.escribir_json(vp.C.ABIERTA, {"conversacion": "una", "estado": "lista", "token": "x"})
    vp.cerrar("descartada")
    assert not vp.C.ABIERTA.exists() and not vp.C.COPIA.exists() and not vp.C.DATOS_VP.exists()
    assert '"motivo": "descartada"' in vp.HISTORIAL.read_text()


def test_turno_del_constructor_sin_secretos_del_panel(vp, monkeypatch):
    cons = importlib.import_module("constructor")
    monkeypatch.setattr(cons, "binario", lambda n: f"/opt/{n}")
    argv, env = cons.preparar_cli({"proveedor": "claude", "modelo": "opus", "resume": None}, "instrucciones")
    assert argv[0] == "/opt/claude" and "--dangerously-skip-permissions" in argv and argv[argv.index("--model") + 1] == "opus"
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat-secreto" and env["HOME"] == str(cons.HOME)
    assert env["CC_VISTA_PREVIA"] == "1" and env["CC_DATA_DIR"].startswith(str(vp.C.DATOS_VP))
    assert "CC_HOSTAGENT_TOKEN" not in env and "CC_BACKUP_KEY" not in env
    argv, env = cons.preparar_cli({"proveedor": "opencode", "modelo": "x/y", "resume": None}, "instrucciones")
    assert env["OPENROUTER_API_KEY"] == "sk-or-secreta" and argv[0] == "/opt/opencode"
    with pytest.raises(vp.Fallo):
        cons.preparar_cli({"proveedor": "antigravity", "modelo": "", "resume": None}, "")
