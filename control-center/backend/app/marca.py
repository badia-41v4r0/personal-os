"""Nombre que el usuario ha puesto a su asistente (perfil → asistente; por defecto Jarvis)."""
import sys

from .config import ROOT

sys.path.insert(0, str(ROOT / "collectors"))
import ajustes  # noqa: E402


def asistente() -> str:
    return ajustes.asistente()
