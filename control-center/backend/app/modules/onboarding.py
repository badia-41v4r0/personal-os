"""Onboarding con agente: cada apartado tiene un asistente que ayuda a configurarlo la primera vez.

- Lee la configuración con `config.get` y propone cambios con `config.<nombre>.set`. Esas acciones son de nivel 2 sin
  regla automática: **siempre esperan la aprobación del usuario**, que ve en el panel exactamente lo que se guardará
  (la configuración completa resultante). Se pueden deshacer (vuelve la anterior).
- Al acabar, `onboarding.hecho` marca el apartado como configurado (nivel 1).
- Un asistente solo recibe las configuraciones de su módulo (core/modules.py → config). No toca el motor de IA ni
  credenciales: eso se hace en Ajustes, a mano.
"""
import copy
import sys

from sqlalchemy.orm import Session

from ..config import ROOT
from ..core import actions, gateway, modules
from .. import instancia

sys.path.insert(0, str(ROOT / "collectors"))
import ajustes  # noqa: E402

# Configuraciones que un agente puede proponer (ia y onboarding no: son del usuario)
CONFIGS_AGENTE = ("perfil", "correo", "github", "estudios", "ofertas", "finanzas", "agenda")
GUIAS = ROOT / "control-center/agents/onboarding"


def _fusionar(base: dict, cambios: dict) -> dict:
    """Mezcla en profundidad los diccionarios; las listas se sustituyen enteras."""
    out = copy.deepcopy(base)
    for k, v in cambios.items():
        out[k] = _fusionar(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def resultado(nombre: str, payload: dict) -> dict:
    """La configuración propia que quedaría guardada (es lo que se enseña al aprobar)."""
    datos = payload.get("datos")
    if not isinstance(datos, dict):
        raise ValueError("`datos` tiene que ser un objeto")
    previo = ajustes.propia(nombre)
    nuevo = datos if payload.get("modo") == "reemplazar" else _fusionar(previo, datos)
    return instancia.validar(nombre, nuevo)


def _set(nombre: str):
    def handler(p: dict, db: Session) -> dict:
        previo = ajustes.propia(nombre)
        nuevo = resultado(nombre, p)
        instancia.guardar_config(nombre, nuevo, "agente")
        return {"nombre": nombre, "previo": previo, "guardado": nuevo}
    return handler


def _undo(r: dict, db: Session) -> dict:
    instancia.guardar_config(r["nombre"], r.get("previo") or {}, "deshacer")
    return {"restaurado": r["nombre"]}


def _resumen(nombre: str):
    def f(p: dict) -> str:
        try:
            import json
            texto = json.dumps(resultado(nombre, p), ensure_ascii=False)
        except ValueError as e:
            texto = f"(no válida: {e})"
        return f"Configurar {nombre}: {texto}"[:300]
    return f


def hecho(p: dict, db: Session) -> dict:
    apartado = str(p.get("apartado") or "")
    if apartado not in modules.MODULES:
        raise ValueError("Apartado desconocido")
    o = ajustes.propia("onboarding")
    o["apartados"] = {**(o.get("apartados") or {}), apartado: "hecho"}
    instancia.guardar_config("onboarding", o, "agente")
    return {"apartado": apartado}


for _n in CONFIGS_AGENTE:
    actions.register(actions.Capability(f"config.{_n}.set", 2, _set(_n), f"Cambiar la configuración «{_n}»",
                                        inverse=_undo, summary=_resumen(_n)))
actions.register(actions.Capability("onboarding.hecho", 1, hecho, "Dar por configurado un apartado",
                                    summary=lambda p: f"Apartado configurado: {p.get('apartado')}"))


@gateway.tool("config.get")
def _config_get(args: dict, db: Session):
    nombre = str(args.get("nombre") or "")
    if nombre not in CONFIGS_AGENTE:
        raise ValueError(f"Configuraciones que puedes leer: {', '.join(CONFIGS_AGENTE)}")
    return {"nombre": nombre, "datos": ajustes.leer(nombre), "campos": sorted(instancia.ESQUEMAS[nombre])}


def configs_de(mod: str) -> tuple[str, ...]:
    m = modules.MODULES[mod]
    return tuple(c for c in (*m.config, *(("perfil",) if mod == "inicio" else ())) if c in CONFIGS_AGENTE)


def guia(mod: str) -> str:
    base = (GUIAS / "_comun.md").read_text(encoding="utf-8") if (GUIAS / "_comun.md").exists() else ""
    propia = GUIAS / f"{mod}.md"
    extra = propia.read_text(encoding="utf-8") if propia.exists() else f"Ayuda a configurar el apartado {modules.MODULES[mod].nombre}."
    return f"{base}\n\n{extra}".strip()
