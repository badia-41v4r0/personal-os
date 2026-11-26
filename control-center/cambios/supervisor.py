"""Supervisor de cambios: aplica, deshace y actualiza el código de la instalación sin dejar al usuario tirado.

Lo lanza el Host Agent como unidad transitoria de systemd (`<instancia>-cc-cambios`), así que sigue vivo aunque el
panel y el propio Host Agent se reinicien a mitad. Solo puede haber uno a la vez (cerrojo en data/cambios/).

Cada operación:
1. Copia de seguridad (data/cambios/copias/<id>/): base de datos (cifrada con CC_BACKUP_KEY, como backup.py; otra
   vez justo antes de migrar, si hay migraciones), la vault y la configuración (.env, secrets.env, data/config, credenciales de los motores). Si no hay espacio en el
   disco para la copia, no se toca nada.
2. Cambio de código con git (fusión de la personalización, `git revert` para deshacer, fusión de la etiqueta de la
   versión nueva). Si choca con algo, se deja todo como estaba.
3. Despliegue: dependencias, web compilada en una carpeta aparte (`out-nuevo`), imagen de Docker, copia de la base justo
   antes de migrar, migraciones, cambio de la web de golpe, reinicio y comprobación de /api/v1/health.
4. Si algo falla: vuelve al commit anterior, a la web anterior y, si se migró la base, a la copia. Reinicia y comprueba.

El panel lee data/cambios/estado.json para enseñar «Aplicando cambios…» y cómo ha ido.

Uso (python del backend):
  supervisor.py aplicar --titulo "..."      fusiona la personalización abierta (data/constructor/copia)
  supervisor.py deshacer <commit>           deshace una personalización ya aplicada
  supervisor.py buscar                      ¿hay versión nueva en el repo de origen? (JSON; no cambia nada)
  supervisor.py actualizar [--version X]    pasa a la versión nueva conservando las personalizaciones
  supervisor.py restaurar <copia> [--vault] vuelve a una copia de seguridad (antes hace otra del estado actual)
  supervisor.py listar                      personalizaciones, copias y estado (JSON)
  supervisor.py desplegar                   recompila y reinicia lo que hay (bin/pos actualizar), con copia
"""
import argparse
import fcntl
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun as C  # noqa: E402
from comun import Fallo  # noqa: E402

MANTENER_COPIAS = 5
SALUD_SEGUNDOS = 150
MARGEN_DISCO = 1_500_000_000  # la compilación de la web y la imagen también ocupan
PRIMER_PLANO = False  # bin/pos actualizar: además de los archivos, lo cuenta por la terminal


# ---------- estado de la operación ----------

class Operacion:
    def __init__(self, op: str, titulo: str, **extra):
        self.id = time.strftime("%Y%m%d-%H%M%S") + f"-{op}"
        self.copia: Path | None = None
        self.registro = C.CAMBIOS / "registros" / f"{self.id}.log"
        self.registro.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.estado = {"id": self.id, "op": op, "titulo": titulo, "estado": "en_curso", "paso": "Empezando",
                       "pasos": [], "inicio": C.ahora(), "fin": None, "error": "", "codigo": "",
                       "version_antes": C.version_actual(), "version_despues": None,
                       "commit_antes": _head(), "commit_despues": None, "copia": None, **extra}
        self._guardar()

    def _guardar(self) -> None:
        C.escribir_json(C.ESTADO, self.estado)

    def paso(self, texto: str) -> None:
        self.estado["paso"] = texto
        self.estado["pasos"].append({"texto": texto, "ts": C.ahora()})
        self._guardar()
        self.log(f"== {texto}")
        if PRIMER_PLANO:
            print(f"· {texto}", flush=True)

    def log(self, texto: str) -> None:
        with self.registro.open("a", encoding="utf-8") as f:
            f.write(texto.rstrip() + "\n")

    def terminar(self, estado: str, error: str = "", codigo: str = "") -> None:
        self.estado.update(estado=estado, error=error[:1500], codigo=codigo, fin=C.ahora(),
                           version_despues=C.version_actual(), commit_despues=_head(),
                           copia=self.copia.name if self.copia else None)
        self.estado["paso"] = {"ok": "Hecho", "revertido": "Vuelto a la versión anterior", "fallo": "No se ha podido hacer",
                               "roto": "El panel no arranca"}.get(estado, estado)
        self._guardar()
        with C.HISTORIAL.open("a", encoding="utf-8") as f:
            f.write(json.dumps({k: self.estado[k] for k in ("id", "op", "titulo", "estado", "inicio", "fin", "error",
                                                            "codigo", "version_antes", "version_despues", "commit_antes",
                                                            "commit_despues", "copia")}, ensure_ascii=False) + "\n")


def _head() -> str:
    try:
        return C.git("rev-parse", "HEAD")
    except Fallo:
        return ""


# ---------- copias de seguridad ----------

def _tam(p: Path) -> int:
    if not p.exists():
        return 0
    if p.is_file():
        return p.stat().st_size
    total = 0
    for raiz, _, archivos in os.walk(p):
        for a in archivos:
            try:
                total += os.lstat(os.path.join(raiz, a)).st_size
            except OSError:
                pass
    return total


def vault_dir() -> Path:
    return Path(C.entorno().get("CC_VAULT") or C.ROOT / "Jarvis-Vault")


def espacio_suficiente() -> None:
    necesita = _tam(vault_dir()) + 2 * _tam(C.DATA / "control-center/cc.db") + MARGEN_DISCO
    libre = shutil.disk_usage(C.ROOT).free
    if libre < necesita:
        raise Fallo(f"No hay espacio en el disco para la copia de seguridad: hacen falta {necesita // 2**20} MB y quedan "
                    f"{libre // 2**20} MB. No he cambiado nada.", "sin_espacio")


def copia_de_seguridad(op: Operacion) -> Path:
    """Base de datos, vault y configuración. Si hay que migrar, justo antes se copia otra vez la base (copia_base)."""
    espacio_suficiente()
    d = C.COPIAS / op.id
    d.mkdir(parents=True, mode=0o700)
    op.copia = d
    op.estado["copia"] = d.name
    vault = vault_dir()
    if vault.is_dir():
        with tarfile.open(d / "vault.tar.gz", "w:gz") as t:
            t.add(vault, arcname="vault", filter=lambda ti: None if "/.stversions" in ti.name or "/.trash" in ti.name else ti)
    cfg = d / "configuracion.tar.gz"
    with tarfile.open(cfg, "w:gz") as t:
        for rel in (".env", "data/control-center/secrets.env", "data/config", "data/control-center/proveedores",
                    "data/control-center/vapid.pem"):
            if (C.ROOT / rel).exists():
                t.add(C.ROOT / rel, arcname=rel)
    clave = C.entorno().get("CC_BACKUP_KEY", "")
    if clave:  # lleva credenciales: cifrada como las copias de la base
        _cifrar(cfg, clave)
    (d / "LEEME.txt").write_text(
        f"Copia de seguridad antes de «{op.estado['titulo']}» ({op.estado['inicio']})\n"
        f"Versión: {op.estado['version_antes']} · commit {op.estado['commit_antes'][:10]}\n\n"
        "- base/: la base de datos del panel (cifrada con CC_BACKUP_KEY si está puesta)\n"
        "- vault.tar.gz: tu vault de notas\n"
        "- configuracion.tar.gz(.enc): .env, secrets.env, data/config y credenciales de los motores\n\n"
        "Para volver a ella: panel → Ajustes → Versiones → Copias de seguridad → Restaurar.\n"
        "Sin panel: control-center/backend/.venv/bin/python control-center/cambios/supervisor.py restaurar "
        f"{d.name} --vault\n", encoding="utf-8")
    copia_base(op)  # la base, siempre (antes de migrar se hace otra, más reciente, para poder volver)
    for f in d.rglob("*"):
        f.chmod(0o700 if f.is_dir() else 0o600)
    op.log(f"Copia en {d}")
    return d


def _backup_mod():
    sys.path.insert(0, str(C.ROOT / "control-center/deployment"))
    import backup  # noqa: PLC0415
    return backup


def _cifrar(f: Path, clave: str) -> Path:
    return _backup_mod().cifrar(f, clave)


def copia_base(op: Operacion, sub: str = "base") -> Path:
    """Copia consistente de la base (backup.py: SQLite en caliente o pg_dump) dentro de la copia de la operación.
    `base`: la de antes de la operación (la que se restaura a mano); `base-antes-de-migrar`: la de la vuelta atrás."""
    dest = (op.copia or C.COPIAS / op.id) / sub
    dest.mkdir(parents=True, exist_ok=True, mode=0o700)
    C.ejecutar([str(C.BACKEND / ".venv/bin/python"), str(C.ROOT / "control-center/deployment/backup.py"),
                "--dest", str(dest), "--keep", "1"], log=op.log, timeout=900)
    hechas = sorted(p for p in dest.iterdir() if p.is_dir())
    if not hechas:
        raise Fallo("La copia de la base no se ha creado")
    return hechas[-1]


def _postgres() -> bool:
    return C.entorno().get("CC_DB_URL", "").startswith("postgresql")


def revision_bd() -> str:
    """Migración en la que está la base ahora mismo."""
    try:
        if _postgres():
            r = subprocess.run(["docker", "exec", f"{C.instancia()}-db", "psql", "-U", "jarvis", "-d", "personal_os", "-Atc",
                                "SELECT version_num FROM alembic_version"], capture_output=True, text=True, timeout=30)
            return r.stdout.strip()
        db = Path(C.entorno().get("CC_DATA_DIR") or C.DATA / "control-center") / "cc.db"
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as c:
            return c.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    except Exception:  # noqa: BLE001
        return ""


def revision_codigo() -> str:
    """Última migración que trae el código (alembic heads)."""
    out = C.ejecutar([str(C.BACKEND / ".venv/bin/alembic"), "heads"], cwd=C.BACKEND, timeout=120)
    return out.split()[0] if out.split() else ""


def restaurar_base(copia: Path, op: Operacion) -> None:
    """Sustituye la base por la de la copia (con el panel parado)."""
    clave = C.entorno().get("CC_BACKUP_KEY", "")
    tmp = Path(C.CAMBIOS / f".restaurar-{op.id}")
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(copia, tmp)
    try:
        if any(tmp.glob("*.enc")):
            if not clave:
                raise Fallo("La copia está cifrada y falta CC_BACKUP_KEY")
            for enc in tmp.glob("*.enc"):
                _backup_mod().descifrar(enc, clave)
        parar_panel(op)
        if (tmp / "personal_os.dump").exists():
            with (tmp / "personal_os.dump").open("rb") as f:
                r = subprocess.run(["docker", "exec", "-i", f"{C.instancia()}-db", "pg_restore", "-U", "jarvis", "-d", "personal_os",
                                    "--clean", "--if-exists"], stdin=f, capture_output=True, timeout=900)
            op.log(r.stderr.decode(errors="replace")[-2000:])
        elif (tmp / "cc.db").exists():
            datos = Path(C.entorno().get("CC_DATA_DIR") or C.DATA / "control-center")
            for extra in ("cc.db-wal", "cc.db-shm"):
                (datos / extra).unlink(missing_ok=True)
            shutil.copy2(tmp / "cc.db", datos / "cc.db")
            (datos / "cc.db").chmod(0o600)
        else:
            raise Fallo("La copia no tiene base de datos")
        op.log(f"Base restaurada desde {copia}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def rotar_copias(actual: Path | None) -> None:
    if not C.COPIAS.is_dir():
        return
    copias = sorted(p for p in C.COPIAS.iterdir() if p.is_dir() and p.name[:8].isdigit())
    for vieja in copias[:-MANTENER_COPIAS]:
        if actual is None or vieja != actual:
            shutil.rmtree(vieja, ignore_errors=True)


# ---------- despliegue ----------

def dependencias(op: Operacion, cambiados: set[str] | None) -> None:
    C.ejecutar(["uv", "sync", "--frozen"], cwd=C.BACKEND, log=op.log, timeout=900)
    if cambiados is None or "control-center/apps/web/package-lock.json" in cambiados or not (C.WEB / "node_modules").is_dir():
        C.ejecutar(["npm", "ci", "--no-fund", "--no-audit"], cwd=C.WEB, log=op.log, timeout=1800)


def compilar_web(op: Operacion) -> None:
    nuevo = C.WEB / "out-nuevo"
    shutil.rmtree(nuevo, ignore_errors=True)
    C.ejecutar(["npm", "run", "build"], cwd=C.WEB, env={**C.entorno(secretos=False), "CC_WEB_OUT": "out-nuevo"},
               log=op.log, timeout=1800)
    if not (nuevo / "index.html").exists():
        raise Fallo("La web no se ha compilado bien (falta index.html)")


def imagen_docker(op: Operacion) -> None:
    if shutil.which("docker") is None:
        raise Fallo("Docker no está disponible")
    tz = C.config_instancia().get("POS_TZ", "Europe/Madrid")
    C.ejecutar(["docker", "build", "-q", "-t", f"{C.instancia()}:local", "--build-arg", f"TZ={tz}", str(C.ROOT)],
               log=op.log, timeout=3600)


def migrar(op: Operacion) -> None:
    C.ejecutar([str(C.BACKEND / ".venv/bin/alembic"), "upgrade", "head"], cwd=C.BACKEND, log=op.log, timeout=900)


def cambiar_web() -> None:
    out, nuevo, anterior = C.WEB / "out", C.WEB / "out-nuevo", C.WEB / "out-anterior"
    shutil.rmtree(anterior, ignore_errors=True)
    if out.exists():
        out.rename(anterior)
    nuevo.rename(out)


def restaurar_web() -> None:
    out, anterior = C.WEB / "out", C.WEB / "out-anterior"
    if anterior.is_dir():
        shutil.rmtree(out, ignore_errors=True)
        anterior.rename(out)


def unidades(op: Operacion) -> None:
    C.ejecutar([str(C.ROOT / "bin/pos"), "_unidades"], log=op.log, timeout=120)


def _systemctl(*args: str) -> None:
    subprocess.run(["systemctl", "--user", *args], capture_output=True, timeout=120)


def parar_panel(op: Operacion) -> None:
    op.log("Parando el panel")
    _systemctl("stop", f"{C.instancia()}-cc-backend.service")


def _reinicios_backend() -> int:
    """Cuántas veces ha reiniciado systemd el backend por fallar (Restart=on-failure)."""
    r = subprocess.run(["systemctl", "--user", "show", "-p", "NRestarts", "--value", f"{C.instancia()}-cc-backend.service"],
                       capture_output=True, text=True, timeout=30)
    try:
        return int(r.stdout.strip() or 0)
    except ValueError:
        return 0


def reiniciar(op: Operacion) -> None:
    op.log("Reiniciando el panel")
    inst = C.instancia()
    _systemctl("reset-failed", f"{inst}-cc-backend.service", f"{inst}-cc-hostagent.service")
    _systemctl("restart", f"{inst}-cc-hostagent.service", f"{inst}-cc-backend.service")
    op.reinicios = _reinicios_backend()


def comprobar_salud(op: Operacion, segundos: int = SALUD_SEGUNDOS) -> None:
    base = f"http://127.0.0.1:{C.puerto()}"
    fin, ultimo = time.monotonic() + segundos, ""
    time.sleep(2)
    while time.monotonic() < fin:
        caidas = _reinicios_backend() - getattr(op, "reinicios", 0)
        if caidas >= 2:  # en bucle de fallos: no hace falta esperar al plazo entero
            raise Fallo(f"El panel no arranca con el cambio (se ha caído {caidas} veces seguidas)", "salud")
        try:
            with urllib.request.urlopen(base + "/api/v1/health", timeout=10) as r:
                ok = json.loads(r.read()).get("ok") is True
            with urllib.request.urlopen(base + "/", timeout=10) as r:
                web = r.status == 200 and b"<html" in r.read(4096).lower()
            if ok and web:
                op.log("El panel responde")
                return
            ultimo = "la web no responde bien"
        except Exception as e:  # noqa: BLE001
            ultimo = str(e)[:200]
        time.sleep(3)
    raise Fallo(f"El panel no responde después del cambio ({ultimo})", "salud")


def desplegar(op: Operacion, commit_antes: str | None) -> None:
    """Instala lo que hay en disco. `commit_antes`: el código venía de ese commit (si algo falla se vuelve a él).
    None (bin/pos actualizar): no se toca git; si falla antes de reiniciar, el panel sigue con lo de antes."""
    cambiados = set(C.git("diff", "--name-only", commit_antes, "HEAD").splitlines()) if commit_antes else None
    hecho = {"web": False, "bd": None, "migrada": False, "reiniciado": False}
    try:
        op.paso("Instalando dependencias")
        dependencias(op, cambiados)
        op.paso("Compilando la web")
        compilar_web(op)
        op.paso("Preparando los servicios")
        imagen_docker(op)
        rev_antes, rev_nueva = revision_bd(), revision_codigo()
        if rev_antes != rev_nueva:
            op.paso("Copiando la base de datos")
            hecho["bd"] = copia_base(op, "base-antes-de-migrar")
            op.paso("Actualizando la base de datos")
            hecho["migrada"] = True
            migrar(op)
        cambiar_web()
        hecho["web"] = True
        unidades(op)
        op.paso("Reiniciando el panel")
        hecho["reiniciado"] = True
        reiniciar(op)
        op.paso("Comprobando que todo funciona")
        comprobar_salud(op)
        shutil.rmtree(C.WEB / "out-anterior", ignore_errors=True)
    except Exception as e:  # noqa: BLE001
        op.log(f"Falla: {e}")
        volver_atras(op, commit_antes, hecho)
        raise


def volver_atras(op: Operacion, commit_antes: str | None, hecho: dict) -> None:
    op.paso("Volviendo a la versión anterior")
    problemas = []

    def intenta(nombre, f, *a):
        try:
            f(*a)
        except Exception as e:  # noqa: BLE001
            problemas.append(f"{nombre}: {e}")
            op.log(f"! {nombre}: {e}")

    if commit_antes:
        intenta("código", C.git, "reset", "--hard", commit_antes)
        intenta("dependencias", C.ejecutar, ["uv", "sync", "--frozen"], C.BACKEND)
    shutil.rmtree(C.WEB / "out-nuevo", ignore_errors=True)
    if hecho["web"]:
        intenta("web", restaurar_web)
    # Una migración que falla se deshace sola (alembic va en una transacción). La copia se pone si la base llegó a
    # migrarse y el código vuelve atrás, o si el código nuevo ya arrancó sobre ella.
    restaura_bd = hecho["migrada"] and hecho["bd"] and (commit_antes or hecho["reiniciado"])
    if restaura_bd:
        intenta("base de datos", restaurar_base, hecho["bd"], op)
    if hecho["web"] or commit_antes:
        intenta("servicios", unidades, op)
    if hecho["reiniciado"] or restaura_bd:
        intenta("reinicio", reiniciar, op)
        try:
            comprobar_salud(op)
        except Fallo as e:
            op.estado["roto"] = True
            problemas.append(str(e))
    if problemas:
        op.estado["problemas_vuelta_atras"] = problemas


# ---------- git ----------

def asegurar_limpio(op: Operacion) -> None:
    """Si alguien cambió archivos del código a mano, se guardan en un commit antes de tocar nada (no se pierden)."""
    if C.git("status", "--porcelain", "--untracked-files=no"):
        C.git("commit", "-am", "Cambios hechos fuera del panel")
        op.log("Había cambios sin guardar en el código: guardados en un commit")


def personalizaciones() -> list[dict]:
    """Personalizaciones aplicadas (fusiones en la rama de la instalación), de la más reciente a la más antigua."""
    sep = "\x1f"
    try:
        log = C.git("log", "--first-parent", "--merges", f"--format=%H{sep}%cI{sep}%s",
                    f"--grep=^{C.PREFIJO_PERSONALIZACION}", "-n", "200")
        deshechas_txt = C.git("log", "--first-parent", "--format=%b", f"--grep=^{C.PREFIJO_DESHACER}", "-n", "400")
    except Fallo:
        return []
    deshechas = {ln.split()[1] for ln in deshechas_txt.splitlines() if ln.startswith("Deshace ") and len(ln.split()) > 1}
    out = []
    for linea in log.splitlines():
        sha, fecha, asunto = (linea.split(sep) + ["", ""])[:3]
        if not asunto.startswith(C.PREFIJO_PERSONALIZACION):
            continue
        archivos = C.git("diff", "--name-only", f"{sha}^1", sha).splitlines()
        out.append({"commit": sha, "fecha": fecha, "titulo": asunto[len(C.PREFIJO_PERSONALIZACION):],
                    "deshecha": sha in deshechas, "archivos": archivos[:50], "n_archivos": len(archivos)})
    return out


def origen() -> str:
    return C.git("remote", "get-url", "origin", check=False)


def buscar() -> dict:
    """Busca versiones nuevas en el repo de origen (solo lee: `git fetch --tags`)."""
    actual = C.version_actual()
    res = {"actual": actual, "ultima": actual, "hay_nueva": False, "notas": "", "origen": bool(origen()), "error": ""}
    if not res["origen"]:
        res["error"] = "Esta instalación no tiene repo de origen (git remote «origin»): las versiones llegan por otro camino."
        return res
    try:
        C.git("fetch", "--quiet", "--tags", "--force", "origin")
    except Fallo as e:
        res["error"] = f"No he podido consultar el repo de origen: {e}"
        return res
    tags = [t for t in C.git("tag", "-l", "v*").split() if C.version_tupla(t)]
    if not tags:
        return res
    ultima = max(tags, key=lambda t: C.version_tupla(t))
    if C.version_tupla(ultima) > (C.version_tupla(actual) or (0, 0, 0)):
        res.update(ultima=ultima.lstrip("v"), hay_nueva=True, etiqueta=ultima)
        try:
            res["notas"] = C.notas_de_version(C.git("show", f"{ultima}:CHANGELOG.md"), ultima)
        except Fallo:
            pass
    return res


# ---------- operaciones ----------

def _personalizacion_abierta() -> dict | None:
    return C.leer_json(C.ABIERTA)


def aplicar(op: Operacion) -> None:
    if not (C.COPIA / ".git").exists():
        raise Fallo("No hay ninguna personalización abierta", "sin_personalizacion")
    C.git("fetch", "--quiet", "--no-tags", str(C.COPIA), C.RAMA)
    nuevo = C.git("rev-parse", "FETCH_HEAD")
    if C.git_ok("merge-base", "--is-ancestor", nuevo, "HEAD"):
        raise Fallo("No hay cambios nuevos que aplicar: el Constructor aún no ha guardado nada", "sin_cambios")
    op.paso("Copia de seguridad")
    copia_de_seguridad(op)
    asegurar_limpio(op)
    antes = C.git("rev-parse", "HEAD")
    op.estado["commit_antes"] = antes
    op.paso("Juntando los cambios")
    if not C.git_ok("merge", "--no-ff", "-m", f"{C.PREFIJO_PERSONALIZACION}{op.estado['titulo']}", nuevo):
        C.git_ok("merge", "--abort")
        raise Fallo("Los cambios chocan con el código actual (alguien lo cambió mientras tanto). No he tocado nada.", "conflicto")
    desplegar(op, antes)
    _cerrar_personalizacion()


def _cerrar_personalizacion() -> None:
    try:
        import vista_previa  # noqa: PLC0415
        vista_previa.cerrar("aplicada")
    except Exception:  # noqa: BLE001  (lo importante, el cambio, ya está hecho)
        pass


def deshacer(op: Operacion, commit: str) -> None:
    p = next((x for x in personalizaciones() if x["commit"] == commit or x["commit"].startswith(commit)), None)
    if p is None or len(commit) < 7:
        raise Fallo("Esa personalización no existe", "no_existe")
    if p["deshecha"]:
        raise Fallo("Esa personalización ya está deshecha", "ya_deshecha")
    op.estado["titulo"] = p["titulo"]
    op.paso("Copia de seguridad")
    copia_de_seguridad(op)
    asegurar_limpio(op)
    antes = C.git("rev-parse", "HEAD")
    op.estado["commit_antes"] = antes
    op.paso("Quitando la personalización")
    if not C.git_ok("revert", "--no-commit", "-m", "1", p["commit"]):
        C.git_ok("revert", "--abort")
        C.git_ok("reset", "--hard", antes)
        raise Fallo("No se puede deshacer sola: cambios posteriores tocan lo mismo. Pídeselo al Constructor.", "conflicto")
    C.git("commit", "-m", f"{C.PREFIJO_DESHACER}{p['titulo']}\n\nDeshace {p['commit']}")
    desplegar(op, antes)


def actualizar(op: Operacion, version: str | None) -> None:
    if _personalizacion_abierta():
        raise Fallo("Tienes una personalización abierta: aplícala o descártala antes de actualizar.", "personalizacion_abierta")
    info = buscar()
    if info["error"]:
        raise Fallo(info["error"], "sin_origen")
    etiqueta = f"v{version.lstrip('v')}" if version else info.get("etiqueta")
    if not etiqueta or not info["hay_nueva"] or not C.git_ok("rev-parse", "--verify", f"refs/tags/{etiqueta}"):
        raise Fallo("Ya tienes la última versión", "al_dia")
    op.estado["titulo"] = f"Actualización a {etiqueta}"
    op.paso("Copia de seguridad")
    copia_de_seguridad(op)
    asegurar_limpio(op)
    antes = C.git("rev-parse", "HEAD")
    op.estado["commit_antes"] = antes
    op.paso(f"Trayendo la versión {etiqueta.lstrip('v')}")
    if C.git_ok("merge-base", "--is-ancestor", "HEAD", etiqueta):
        ok = C.git_ok("merge", "--ff-only", etiqueta)
    else:  # tiene personalizaciones: se juntan con la versión nueva
        ok = C.git_ok("merge", "--no-ff", "-m", f"{C.PREFIJO_ACTUALIZACION}{etiqueta}", etiqueta)
    if not ok:
        C.git_ok("merge", "--abort")
        C.git_ok("reset", "--hard", antes)
        raise Fallo(f"La versión {etiqueta.lstrip('v')} choca con tus personalizaciones. No he tocado nada: el Constructor "
                    "puede juntarlas por ti.", "conflicto")
    desplegar(op, antes)


def restaurar(op: Operacion, nombre: str, con_vault: bool) -> None:
    copia = C.COPIAS / nombre
    if "/" in nombre or not copia.is_dir():
        raise Fallo("Esa copia no existe", "no_existe")
    bases = sorted(p for p in (copia / "base").iterdir() if p.is_dir()) if (copia / "base").is_dir() else []
    if not bases and not con_vault:
        raise Fallo("Esa copia no tiene base de datos (la operación no llegó a migrar nada)", "sin_base")
    op.paso("Copia de seguridad del estado actual")
    copia_de_seguridad(op)
    if bases:
        op.paso("Restaurando la base de datos")
        restaurar_base(bases[-1], op)
    if con_vault and (copia / "vault.tar.gz").exists():
        op.paso("Restaurando la vault")
        vault = vault_dir()
        if vault.exists():  # no se borra: se aparta
            vault.rename(vault.with_name(f"{vault.name}.antes-de-restaurar-{time.strftime('%Y%m%d-%H%M%S')}"))
        tmp = vault.with_name(f".{vault.name}.restaurando")
        shutil.rmtree(tmp, ignore_errors=True)
        with tarfile.open(copia / "vault.tar.gz") as t:
            t.extractall(tmp, filter="data")
        (tmp / "vault").rename(vault)
        shutil.rmtree(tmp, ignore_errors=True)
    op.paso("Reiniciando el panel")
    reiniciar(op)
    op.paso("Comprobando que todo funciona")
    comprobar_salud(op)


def listar() -> dict:
    copias = []
    if C.COPIAS.is_dir():
        for d in sorted((p for p in C.COPIAS.iterdir() if p.is_dir() and p.name[:8].isdigit()), reverse=True):
            copias.append({"id": d.name, "tam": _tam(d), "base": (d / "base").is_dir() and any((d / "base").iterdir()),
                           "vault": (d / "vault.tar.gz").exists()})
    historial = []
    try:
        historial = [json.loads(x) for x in C.HISTORIAL.read_text(encoding="utf-8").splitlines()[-30:] if x.strip()][::-1]
    except (OSError, ValueError):
        pass
    return {"version": C.version_actual(), "estado": C.leer_json(C.ESTADO), "personalizaciones": personalizaciones(),
            "copias": copias, "historial": historial, "origen": bool(origen()),
            "personalizacion_abierta": _personalizacion_abierta()}


def _cerrojo():
    C.CAMBIOS.mkdir(parents=True, exist_ok=True, mode=0o700)
    f = (C.CAMBIOS / "cambios.lock").open("w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("Ya hay un cambio en marcha")
    return f


def main(argv: list[str] | None = None) -> int:
    global PRIMER_PLANO
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="orden", required=True)
    a = sub.add_parser("aplicar")
    a.add_argument("--titulo", default="Cambios del Constructor")
    d = sub.add_parser("deshacer")
    d.add_argument("commit")
    u = sub.add_parser("actualizar")
    u.add_argument("--version")
    r = sub.add_parser("restaurar")
    r.add_argument("copia")
    r.add_argument("--vault", action="store_true")
    sub.add_parser("buscar")
    sub.add_parser("listar")
    dp = sub.add_parser("desplegar")
    dp.add_argument("--primer-plano", action="store_true")
    args = ap.parse_args(argv)

    if args.orden in ("buscar", "listar"):
        print(json.dumps(buscar() if args.orden == "buscar" else listar(), ensure_ascii=False))
        return 0
    cerrojo = _cerrojo()  # noqa: F841  (se suelta al salir)
    titulos = {"aplicar": args.__dict__.get("titulo"), "deshacer": "Deshacer una personalización",
               "actualizar": "Actualización", "restaurar": "Restaurar una copia de seguridad", "desplegar": "Recompilar y reiniciar"}
    if args.orden == "desplegar":
        PRIMER_PLANO = bool(args.primer_plano)
    op = Operacion(args.orden, titulos[args.orden])
    try:
        if args.orden == "aplicar":
            aplicar(op)
        elif args.orden == "deshacer":
            deshacer(op, args.commit)
        elif args.orden == "actualizar":
            actualizar(op, args.version)
        elif args.orden == "restaurar":
            restaurar(op, args.copia, args.vault)
        else:
            op.paso("Copia de seguridad")
            copia_de_seguridad(op)
            desplegar(op, None)
    except Exception as e:  # noqa: BLE001
        codigo = e.codigo if isinstance(e, Fallo) else "error"
        mensaje = str(e) or e.__class__.__name__
        cambio_hecho = op.estado["pasos"] and any(p["texto"] == "Volviendo a la versión anterior" for p in op.estado["pasos"])
        estado = "roto" if op.estado.get("roto") else "revertido" if cambio_hecho else "fallo"
        op.terminar(estado, mensaje, codigo)
        rotar_copias(op.copia)
        if PRIMER_PLANO:
            print(f"✗ {mensaje}", file=sys.stderr)
        return 1
    op.terminar("ok")
    rotar_copias(op.copia)
    if PRIMER_PLANO:
        print("✓ Hecho", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
