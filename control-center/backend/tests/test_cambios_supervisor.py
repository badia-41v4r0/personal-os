"""Supervisor de cambios (control-center/cambios/supervisor.py) con una instalación de mentira: un repo git temporal.

Los pasos pesados (dependencias, compilar, Docker, reiniciar, salud) se sustituyen; lo que se prueba es el orden, la
copia de seguridad, git y la vuelta atrás.
"""
import importlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

CAMBIOS = Path(__file__).resolve().parents[2] / "cambios"
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def git(cwd: Path, *args: str) -> str:
    import os
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env={**os.environ, **GIT_ENV}).stdout.strip()


def _instalacion(root: Path) -> None:
    (root / "control-center/apps/web/out").mkdir(parents=True)
    (root / "control-center/apps/web/out/index.html").write_text("<html>vieja</html>")
    (root / "control-center/apps/web/node_modules").mkdir()
    (root / "control-center/backend").mkdir(parents=True)
    (root / "Jarvis-Vault/Jarvis").mkdir(parents=True)
    (root / "Jarvis-Vault/Jarvis/nota.md").write_text("mi nota")
    (root / "data/control-center").mkdir(parents=True)
    (root / "data/control-center/secrets.env").write_text("CC_BACKUP_KEY=\n")
    (root / "data/config").mkdir()
    (root / "data/config/perfil.json").write_text("{}")
    (root / ".env").write_text("POS_INSTANCE=pruebacc\nPOS_PORT=59999\n")
    (root / ".gitignore").write_text("data/\nJarvis-Vault/\n.env\ncontrol-center/apps/web/out*/\ncontrol-center/apps/web/node_modules/\n")
    (root / "VERSION").write_text("0.1.0\n")
    (root / "CHANGELOG.md").write_text("# Cambios\n\n## [0.1.0] — 2026-11-26\n\n- Primera\n")
    (root / "app.py").write_text("print('hola')\n")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "inicio")


@pytest.fixture()
def sup(tmp_path, monkeypatch):
    root = tmp_path / "pos"
    root.mkdir()
    _instalacion(root)
    monkeypatch.setenv("POS_ROOT", str(root))
    monkeypatch.setenv("POS_INSTANCE", "pruebacc")
    monkeypatch.delenv("CC_DB_URL", raising=False)
    monkeypatch.delenv("CC_DATA_DIR", raising=False)
    monkeypatch.delenv("CC_VAULT", raising=False)
    monkeypatch.syspath_prepend(str(CAMBIOS))
    for m in ("comun", "vista_previa", "supervisor"):
        sys.modules.pop(m, None)
    s = importlib.import_module("supervisor")
    llamadas: list[str] = []
    s.llamadas = llamadas
    s.SALUD_SEGUNDOS = 1

    def compilar(op):
        llamadas.append("compilar")
        (s.C.WEB / "out-nuevo").mkdir()
        (s.C.WEB / "out-nuevo/index.html").write_text("<html>nueva</html>")

    def base(op, sub="base"):
        llamadas.append(f"copia_{sub}")
        d = op.copia / sub / "20260101-000000"
        d.mkdir(parents=True)
        (d / "cc.db").write_text("x")
        return d

    monkeypatch.setattr(s, "dependencias", lambda op, c: llamadas.append("dependencias"))
    monkeypatch.setattr(s, "compilar_web", compilar)
    monkeypatch.setattr(s, "imagen_docker", lambda op: llamadas.append("docker"))
    monkeypatch.setattr(s, "revision_bd", lambda: "a1")
    monkeypatch.setattr(s, "revision_codigo", lambda: "a1")
    monkeypatch.setattr(s, "copia_base", base)
    monkeypatch.setattr(s, "migrar", lambda op: llamadas.append("migrar"))
    monkeypatch.setattr(s, "unidades", lambda op: llamadas.append("unidades"))
    monkeypatch.setattr(s, "reiniciar", lambda op: llamadas.append("reiniciar"))
    monkeypatch.setattr(s, "parar_panel", lambda op: llamadas.append("parar"))
    monkeypatch.setattr(s, "comprobar_salud", lambda op, segundos=1: llamadas.append("salud"))
    monkeypatch.setattr(s.C, "ejecutar", lambda *a, **k: llamadas.append("ejecutar") or "")
    return s


def _personalizacion(s, cambio: str = "print('adiós')\n", conv: str = "c1") -> None:
    """Lo que deja la vista previa: un clon con commits del Constructor en su rama."""
    copia = s.C.COPIA
    copia.parent.mkdir(parents=True, exist_ok=True)
    git(s.C.ROOT, "clone", "-q", str(s.C.ROOT), str(copia))
    git(copia, "checkout", "-q", "-b", s.C.RAMA)
    (copia / "app.py").write_text(cambio)
    git(copia, "commit", "-qam", "Constructor: cambio")
    s.C.escribir_json(s.C.ABIERTA, {"conversacion": conv, "estado": "lista"})


def _estado(s) -> dict:
    return json.loads(s.C.ESTADO.read_text())


def test_aplicar_bien(sup):
    _personalizacion(sup)
    antes = git(sup.C.ROOT, "rev-parse", "HEAD")
    assert sup.main(["aplicar", "--titulo", "Saludo nuevo"]) == 0
    e = _estado(sup)
    assert e["estado"] == "ok" and e["commit_antes"] == antes
    assert git(sup.C.ROOT, "log", "-1", "--format=%s") == "Personalización: Saludo nuevo"
    assert (sup.C.ROOT / "app.py").read_text() == "print('adiós')\n"
    assert (sup.C.WEB / "out/index.html").read_text() == "<html>nueva</html>"
    assert not (sup.C.WEB / "out-anterior").exists()
    # orden: compilar antes de reiniciar; sin migraciones nuevas, ni copia de la base ni migrar
    ll = sup.llamadas
    assert ll.index("compilar") < ll.index("reiniciar") < ll.index("salud") and "migrar" not in ll
    assert ll.index("copia_base") < ll.index("compilar") and "copia_base-antes-de-migrar" not in ll
    # copia de seguridad hecha antes: vault y configuración
    copia = sup.C.COPIAS / e["copia"]
    assert (copia / "vault.tar.gz").exists() and (copia / "configuracion.tar.gz").exists() and (copia / "LEEME.txt").exists()
    # personalización cerrada
    assert not sup.C.ABIERTA.exists() and not sup.C.COPIA.exists()
    p = sup.personalizaciones()
    assert p[0]["titulo"] == "Saludo nuevo" and not p[0]["deshecha"] and "app.py" in p[0]["archivos"]


def test_si_no_arranca_vuelve_atras(sup, monkeypatch):
    _personalizacion(sup)
    antes = git(sup.C.ROOT, "rev-parse", "HEAD")
    monkeypatch.setattr(sup, "revision_codigo", lambda: "b2")  # trae una migración
    restaurada = []
    monkeypatch.setattr(sup, "restaurar_base", lambda copia, op: restaurada.append(copia))

    def salud(op, segundos=1):
        if "volver" not in sup.llamadas:
            sup.llamadas.append("volver")
            raise sup.Fallo("El panel no responde", "salud")

    monkeypatch.setattr(sup, "comprobar_salud", salud)
    assert sup.main(["aplicar"]) == 1
    e = _estado(sup)
    assert e["estado"] == "revertido" and e["codigo"] == "salud"
    assert git(sup.C.ROOT, "rev-parse", "HEAD") == antes            # código de antes
    assert (sup.C.ROOT / "app.py").read_text() == "print('hola')\n"
    assert (sup.C.WEB / "out/index.html").read_text() == "<html>vieja</html>"  # web de antes
    assert len(restaurada) == 1 and restaurada[0].parent.name == "base-antes-de-migrar"  # base de antes de migrar
    assert sup.llamadas.count("reiniciar") == 2
    # la personalización sigue abierta para poder arreglarla
    assert sup.C.ABIERTA.exists() and sup.C.COPIA.exists()


def test_si_falla_la_compilacion_no_reinicia(sup, monkeypatch):
    _personalizacion(sup)
    antes = git(sup.C.ROOT, "rev-parse", "HEAD")

    def rota(op):
        raise sup.Fallo("Falló «npm run build»")

    monkeypatch.setattr(sup, "compilar_web", rota)
    assert sup.main(["aplicar"]) == 1
    assert _estado(sup)["estado"] == "revertido"
    assert git(sup.C.ROOT, "rev-parse", "HEAD") == antes
    assert "reiniciar" not in sup.llamadas and (sup.C.WEB / "out/index.html").read_text() == "<html>vieja</html>"


def test_conflicto_no_toca_nada(sup):
    _personalizacion(sup)
    (sup.C.ROOT / "app.py").write_text("print('otro')\n")  # alguien cambió lo mismo en la instalación
    git(sup.C.ROOT, "commit", "-qam", "cambio a mano")
    antes = git(sup.C.ROOT, "rev-parse", "HEAD")
    assert sup.main(["aplicar"]) == 1
    e = _estado(sup)
    assert e["estado"] == "fallo" and e["codigo"] == "conflicto"
    assert git(sup.C.ROOT, "rev-parse", "HEAD") == antes and git(sup.C.ROOT, "status", "--porcelain") == ""
    assert "reiniciar" not in sup.llamadas


def test_sin_cambios_nuevos(sup):
    _personalizacion(sup)
    git(sup.C.COPIA, "reset", "-q", "--hard", "HEAD~1")
    assert sup.main(["aplicar"]) == 1
    assert _estado(sup)["codigo"] == "sin_cambios"


def test_sin_espacio_no_toca_nada(sup, monkeypatch):
    _personalizacion(sup)
    antes = git(sup.C.ROOT, "rev-parse", "HEAD")
    monkeypatch.setattr(sup.shutil, "disk_usage", lambda p: type("U", (), {"free": 10})())
    assert sup.main(["aplicar"]) == 1
    assert _estado(sup)["codigo"] == "sin_espacio"
    assert git(sup.C.ROOT, "rev-parse", "HEAD") == antes


def test_cambios_a_mano_se_guardan(sup):
    _personalizacion(sup, cambio="print('adiós')\n")
    (sup.C.ROOT / "VERSION").write_text("0.1.0-mia\n")  # editado a mano, sin commit
    assert sup.main(["aplicar"]) == 0
    assert "Cambios hechos fuera del panel" in git(sup.C.ROOT, "log", "--format=%s")
    assert (sup.C.ROOT / "VERSION").read_text() == "0.1.0-mia\n"


def test_deshacer(sup):
    _personalizacion(sup)
    assert sup.main(["aplicar", "--titulo", "Saludo"]) == 0
    p = sup.personalizaciones()[0]
    assert sup.main(["deshacer", p["commit"]]) == 0
    assert (sup.C.ROOT / "app.py").read_text() == "print('hola')\n"
    assert git(sup.C.ROOT, "log", "-1", "--format=%s") == "Deshacer personalización: Saludo"
    assert sup.personalizaciones()[0]["deshecha"] is True
    assert sup.main(["deshacer", p["commit"]]) == 1 and _estado(sup)["codigo"] == "ya_deshecha"


def _upstream(sup, tmp_path) -> Path:
    """El repo del proyecto, clonado antes de que el usuario personalizara nada (de ahí instaló)."""
    up = tmp_path / "upstream"
    git(tmp_path, "clone", "-q", str(sup.C.ROOT), str(up))
    git(sup.C.ROOT, "remote", "add", "origin", str(up))
    return up


def _publicar(up: Path, version: str, cambio: str | None = None) -> None:
    """Una versión nueva etiquetada en el proyecto."""
    (up / "VERSION").write_text(version + "\n")
    (up / "CHANGELOG.md").write_text(f"# Cambios\n\n## [{version}] — 2026-12-01\n\n### Novedades\n- Algo nuevo\n\n## [0.1.0] — 2026-11-26\n\n- Primera\n")
    if cambio is not None:
        (up / "app.py").write_text(cambio)
    (up / "nuevo.py").write_text("x = 1\n")
    git(up, "add", "-A")
    git(up, "commit", "-qm", f"v{version}")
    git(up, "tag", f"v{version}")


def test_buscar_y_actualizar_con_personalizaciones(sup, tmp_path):
    up = _upstream(sup, tmp_path)
    _personalizacion(sup, cambio="print('hola')\nprint('mío')\n")
    assert sup.main(["aplicar", "--titulo", "Lo mío"]) == 0
    _publicar(up, "0.2.0")
    b = sup.buscar()
    assert b["hay_nueva"] and b["ultima"] == "0.2.0" and "Algo nuevo" in b["notas"]
    assert sup.main(["actualizar"]) == 0
    assert sup.C.version_actual() == "0.2.0" and (sup.C.ROOT / "nuevo.py").exists()
    assert "print('mío')" in (sup.C.ROOT / "app.py").read_text()  # la personalización sigue
    assert git(sup.C.ROOT, "log", "-1", "--format=%s") == "Actualización a v0.2.0"
    assert sup.buscar()["hay_nueva"] is False
    assert sup.main(["actualizar"]) == 1 and _estado(sup)["codigo"] == "al_dia"


def test_actualizar_sin_personalizaciones_avanza_directo(sup, tmp_path):
    up = _upstream(sup, tmp_path)
    _publicar(up, "0.2.0")
    assert sup.main(["actualizar"]) == 0
    assert git(sup.C.ROOT, "rev-parse", "HEAD") == git(up, "rev-parse", "HEAD")


def test_actualizar_que_choca(sup, tmp_path):
    up = _upstream(sup, tmp_path)
    _personalizacion(sup, cambio="print('mío')\n")
    assert sup.main(["aplicar"]) == 0
    _publicar(up, "0.2.0", cambio="print('de la versión')\n")
    antes = git(sup.C.ROOT, "rev-parse", "HEAD")
    assert sup.main(["actualizar"]) == 1
    e = _estado(sup)
    assert e["codigo"] == "conflicto" and e["estado"] == "fallo"
    assert git(sup.C.ROOT, "rev-parse", "HEAD") == antes and git(sup.C.ROOT, "status", "--porcelain") == ""


def test_actualizar_sin_origen(sup):
    assert sup.main(["actualizar"]) == 1
    assert _estado(sup)["codigo"] == "sin_origen"


def test_no_actualiza_con_personalizacion_abierta(sup, tmp_path):
    _publicar(_upstream(sup, tmp_path), "0.2.0")
    sup.C.escribir_json(sup.C.ABIERTA, {"conversacion": "c1", "estado": "lista"})
    assert sup.main(["actualizar"]) == 1
    assert _estado(sup)["codigo"] == "personalizacion_abierta"


def test_un_cambio_a_la_vez(sup):
    import fcntl
    sup.C.CAMBIOS.mkdir(parents=True, exist_ok=True)
    with (sup.C.CAMBIOS / "cambios.lock").open("w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        with pytest.raises(SystemExit):
            sup.main(["deshacer", "abcdef1"])


def test_restaurar_base_sqlite(sup):
    datos = sup.C.DATA / "control-center"
    with sqlite3.connect(datos / "cc.db") as c:
        c.execute("create table t (x)")
        c.execute("insert into t values ('actual')")
    copia = sup.C.COPIAS / "20260101-000000-aplicar/base/20260101-000000"
    copia.mkdir(parents=True)
    with sqlite3.connect(copia / "cc.db") as c:
        c.execute("create table t (x)")
        c.execute("insert into t values ('de la copia')")
    op = sup.Operacion("restaurar", "prueba")
    sup.restaurar_base(copia, op)
    with sqlite3.connect(datos / "cc.db") as c:
        assert c.execute("select x from t").fetchone()[0] == "de la copia"
    assert "parar" in sup.llamadas


def test_rotacion_de_copias(sup):
    for i in range(8):
        (sup.C.COPIAS / f"2026010{i}-000000-aplicar").mkdir(parents=True)
    sup.rotar_copias(sup.C.COPIAS / "20260100-000000-aplicar")
    quedan = sorted(p.name for p in sup.C.COPIAS.iterdir())
    assert len(quedan) == sup.MANTENER_COPIAS + 1 and "20260100-000000-aplicar" in quedan


def test_listar(sup):
    _personalizacion(sup)
    assert sup.main(["aplicar", "--titulo", "Uno"]) == 0
    d = sup.listar()
    assert d["version"] == "0.1.0" and d["estado"]["estado"] == "ok" and d["origen"] is False
    assert d["personalizaciones"][0]["titulo"] == "Uno" and d["copias"][0]["vault"] is True
    assert d["historial"][0]["op"] == "aplicar"
