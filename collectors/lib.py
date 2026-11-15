"""Utilidades comunes de los recopiladores (sin IA, solo librería estándar)."""
import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VAULT = ROOT / "Jarvis-Vault"
if not VAULT.exists() and Path("/vault/Jarvis").exists():  # dentro del contenedor de Jarvis
    VAULT = Path("/vault")
JARVIS = VAULT / "Jarvis"
SISTEMA = JARVIS / "Sistema"

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

WIKILINK = re.compile(r"\[\[([^\]|]+)(?:\\?\|([^\]]+))?\]\]")
CHECKBOX = re.compile(r"^\s*[-*] \[( |x|X)\] (.*)$")


def plain(text: str) -> str:
    """Quita wikilinks y negritas: '[[Uni/X|Y]]' -> 'Y'."""
    text = WIKILINK.sub(lambda m: m.group(2) or m.group(1).split("/")[-1], text)
    return text.replace("**", "").strip()


def fecha_larga(d: date) -> str:
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]}"


def fecha_corta(d: date) -> str:
    return f"{DIAS[d.weekday()][:3]} {d.day:02d}/{d.month:02d}"


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("." + path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
