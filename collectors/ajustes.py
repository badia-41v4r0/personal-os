"""Configuración de la instancia: lo que antes estaba escrito en el código (nombre, áreas, repos, cuentas, asignaturas…).

- Valores por defecto en config/defecto/<nombre>.json (en el repo, sin datos de nadie).
- Lo de cada instalación en data/config/<nombre>.json (fuera de git), que escriben el onboarding, Ajustes y los agentes
  de configuración (siempre por una acción con vista previa). Se mezcla encima de los valores por defecto.
Solo librería estándar: lo usan los collectors del host, los scripts y el backend.
"""
import json
import os
import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFECTO = ROOT / "config/defecto"
NOMBRE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,40}$")


def carpeta() -> Path:
    return Path(os.environ.get("POS_CONFIG_DIR", str(ROOT / "data/config")))


def _cargar(p: Path) -> dict:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def leer(nombre: str) -> dict:
    if not NOMBRE_RE.match(nombre):
        raise ValueError(f"Configuración no válida: {nombre}")
    return _cargar(DEFECTO / f"{nombre}.json") | _cargar(carpeta() / f"{nombre}.json")


def propia(nombre: str) -> dict:
    """Solo lo que ha configurado esta instalación (sin valores por defecto)."""
    if not NOMBRE_RE.match(nombre):
        raise ValueError(f"Configuración no válida: {nombre}")
    return _cargar(carpeta() / f"{nombre}.json")


def guardar(nombre: str, datos: dict) -> Path:
    """Escritura atómica con permisos 600. Sustituye la configuración propia de ese nombre entera."""
    if not NOMBRE_RE.match(nombre) or not isinstance(datos, dict):
        raise ValueError(f"Configuración no válida: {nombre}")
    d = carpeta()
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    destino = d / f"{nombre}.json"
    fd, tmp = tempfile.mkstemp(dir=d, prefix=f".{nombre}.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, destino)
    return destino


# ---------- atajos de uso común ----------

def nombre_usuario() -> str:
    return (leer("perfil").get("nombre") or "").strip() or "el usuario"


def areas() -> dict[str, str]:
    """id → etiqueta con emoji. «personal» existe siempre: es donde cae lo que no tiene área."""
    out = {}
    for a in leer("perfil").get("areas") or []:
        if isinstance(a, dict) and NOMBRE_RE.match(str(a.get("id", ""))):
            out[a["id"]] = f"{a.get('emoji', '•')} {a.get('nombre') or a['id']}".strip()
    out.setdefault("personal", "🏠 Personal")
    return out


def variables() -> dict[str, str]:
    """Lo que pueden usar las plantillas de instrucciones."""
    plat = leer("estudios").get("plataforma") or {}
    return {"nombre": nombre_usuario(), "campus_nombre": str(plat.get("nombre") or "tu campus virtual"),
            "campus_url": str(plat.get("url") or ""), "centro": str(plat.get("centro") or "tu universidad")}


def render(texto: str) -> str:
    """Rellena las plantillas de instrucciones: {{nombre}}, {{campus_nombre}}, {{campus_url}} y {{centro}}."""
    for k, v in variables().items():
        texto = texto.replace("{{" + k + "}}", v)
    return texto


if __name__ == "__main__":  # para los scripts de bash: python3 collectors/ajustes.py <nombre> [clave]
    import sys
    d = leer(sys.argv[1])
    v = d.get(sys.argv[2], "") if len(sys.argv) > 2 else d
    print(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))
