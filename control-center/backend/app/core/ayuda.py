"""Ayuda de uso del Personal OS para los agentes: buscar y leer la documentación (lecturas `help.search` y `help.read`).

Solo una lista cerrada de documentos pensados para el usuario. Nunca el registro de decisiones, la auditoría, `privado/`
ni el código: el agente pide un documento por su nombre corto y aquí se traduce a la ruta, así no puede salirse.
"""
import re
from pathlib import Path

from ..config import ROOT

DOCS: dict[str, str] = {
    "inicio": "README.md",
    "guia-de-uso": "docs/guia-de-uso.md",
    "instalacion": "docs/instalacion.md",
    "motores-de-ia": "docs/motores-de-ia.md",
    "modulos": "docs/modulos.md",
    "seguridad": "docs/seguridad.md",
    "agentes": "control-center/docs/agentes.md",
    "candidaturas": "control-center/docs/candidaturas.md",
    "checkin": "control-center/docs/checkin.md",
    "constructor": "control-center/docs/constructor.md",
    "educacion": "control-center/docs/educacion.md",
    "google": "control-center/docs/google.md",
    "gym": "control-center/docs/gym.md",
    "ocio": "control-center/docs/ocio.md",
    "ordenadores-virtuales": "control-center/docs/ordenadores-virtuales.md",
}
MAX_DOC = 40_000  # caracteres: lo bastante para cualquier documento, sin llenar el contexto
_TITULO = re.compile(r"^(#{1,4})\s+(.+?)\s*$")


def _texto(doc: str) -> str:
    rel = DOCS.get(doc)
    if rel is None:
        raise ValueError(f"No hay ningún documento «{doc}». Disponibles: {', '.join(DOCS)}")
    f = ROOT / rel
    return f.read_text(encoding="utf-8") if f.exists() else ""


def _apartados(texto: str) -> list[tuple[str, str]]:
    """[(título, contenido)] por cada encabezado; lo de antes del primero va con el título del documento."""
    out: list[tuple[str, list[str]]] = [("", [])]
    for linea in texto.splitlines():
        m = _TITULO.match(linea)
        if m:
            out.append((m.group(2), [linea]))
        else:
            out[-1][1].append(linea)
    return [(t, "\n".join(ls).strip()) for t, ls in out if "\n".join(ls).strip()]


def _norm(s: str) -> str:
    tabla = str.maketrans("áéíóúüñ", "aeiouun")
    return s.lower().translate(tabla)


def indice() -> list[dict]:
    """Qué documentos hay y sus apartados (para `help.read` sin argumentos)."""
    res = []
    for doc in DOCS:
        aps = [t for t, _ in _apartados(_texto(doc)) if t]
        if aps:
            res.append({"doc": doc, "titulo": aps[0], "apartados": aps[1:]})
    return res


def buscar(q: str, limite: int = 6) -> list[dict]:
    """Apartados que más se parecen a la pregunta: cuenta las palabras de `q` (sin tildes) en título y texto."""
    palabras = [p for p in re.findall(r"\w+", _norm(q)) if len(p) > 2]
    if not palabras:
        return []
    hits = []
    for doc in DOCS:
        for titulo, cuerpo in _apartados(_texto(doc)):
            t, c = _norm(titulo), _norm(cuerpo)
            puntos = sum(3 * t.count(p) + c.count(p) for p in palabras) + 2 * sum(p in c for p in palabras)
            if puntos:
                hits.append((puntos, doc, titulo, cuerpo))
    hits.sort(key=lambda h: -h[0])
    return [{"doc": d, "apartado": t, "texto": c[:1500] + ("…" if len(c) > 1500 else "")} for _, d, t, c in hits[:limite]]


def leer(doc: str, apartado: str = "") -> dict:
    texto = _texto(doc)
    if apartado:
        objetivo = _norm(apartado)
        for t, c in _apartados(texto):
            if objetivo in _norm(t):
                return {"doc": doc, "apartado": t, "texto": c[:MAX_DOC]}
        raise ValueError(f"«{doc}» no tiene un apartado «{apartado}»")
    return {"doc": doc, "texto": texto[:MAX_DOC], "recortado": len(texto) > MAX_DOC}
