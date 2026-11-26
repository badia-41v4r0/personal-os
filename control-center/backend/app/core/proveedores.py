"""Motor de IA elegido en Ajustes (config ia.json) y cómo se traduce cada turno a ese proveedor.

- proveedor: claude | codex | opencode (OpenCode Zen/Go u OpenRouter, según el prefijo del modelo) | antigravity (solo consulta).
- modelos[proveedor][perfil]: el modelo de cada perfil (fast, standard, deep, code). Vacío en Codex = el suyo por defecto.
- limite_mensual_usd: tope de gasto de OpenCode por uso (Zen y OpenRouter; la suscripción Go no cuenta). Al llegar, no
  se lanzan más turnos con él.
- relevo: si Claude se queda sin cuota, otro proveedor responde en modo consulta (model_policy, como hasta ahora).

Si el proveedor no sabe hacer algo que el turno pide (subagentes, web), se le quita al turno y se dice en la respuesta:
el usuario eligió ese motor y se respeta, sin cambiar de proveedor a escondidas.
"""
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select

from ..config import ROOT

sys.path.insert(0, str(ROOT / "collectors"))
import ajustes  # noqa: E402

PROVEEDORES = ("claude", "codex", "opencode", "antigravity")
NOMBRES = {"claude": "Claude Code", "codex": "Codex (ChatGPT)", "opencode": "OpenCode", "antigravity": "Antigravity"}
# Igual que host-agent/proveedores.py: lo que sabe hacer cada uno
CAPACIDADES = {
    "claude": {"mcp": True, "subagentes": True, "web": True, "contenedor": True},
    "codex": {"mcp": True, "subagentes": False, "web": False, "contenedor": True},
    "opencode": {"mcp": True, "subagentes": False, "web": False, "contenedor": True},
    "antigravity": {"mcp": False, "subagentes": False, "web": False, "contenedor": False},
}
PREFIJOS_OPENCODE = ("opencode/", "opencode-go/", "openrouter/")
SUSCRIPCION = ("opencode-go/",)  # tarifa plana: lo que informe de coste no es gasto real
PERFIL_DE_MODELO = {"opus": "deep", "sonnet": "standard", "haiku": "fast", "inherit": "standard"}


@dataclass
class Turno:
    proveedor: str
    modelo: str
    quitado: list[str] = field(default_factory=list)  # lo que el proveedor no sabe hacer y se ha quitado
    error: str = ""


def config() -> dict:
    return ajustes.leer("ia")


def elegido() -> str:
    p = str(config().get("proveedor") or "claude")
    return p if p in PROVEEDORES else "claude"


def modelo(prov: str, perfil: str) -> str:
    m = ((config().get("modelos") or {}).get(prov) or {}).get(perfil, "")
    if prov == "claude":
        return m if m in ("sonnet", "opus", "haiku") else ("opus" if perfil == "deep" else "sonnet")
    return str(m or "")


def gasto_mes(db, prov: str = "opencode") -> float:
    """Lo gastado este mes con un proveedor de pago por uso, según lo que informa cada turno."""
    from ..models import AgentRun
    ini = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None)
    total = 0.0
    for u in db.scalars(select(AgentRun.usage).where(AgentRun.started_at >= ini)):
        if isinstance(u, dict) and u.get("provider") == prov and u.get("cost_usd") and not str(u.get("model") or "").startswith(SUSCRIPCION):
            try:
                total += float(u["cost_usd"])
            except (TypeError, ValueError):
                pass
    return round(total, 4)


def limite() -> float:
    try:
        return max(0.0, float(config().get("limite_mensual_usd", 10)))
    except (TypeError, ValueError):
        return 10.0


def turno(db, modelo_claude: str, perms: dict) -> Turno:
    """Proveedor y modelo de un turno, a partir del modelo «de Claude» que guarda la sesión (sonnet/opus)."""
    prov = elegido()
    if not CAPACIDADES[prov]["contenedor"]:  # Antigravity: las sesiones con herramientas siguen en Claude
        prov = "claude"
    perfil = PERFIL_DE_MODELO.get(modelo_claude, "standard")
    t = Turno(prov, modelo_claude if prov == "claude" else modelo(prov, perfil))
    cap = CAPACIDADES[prov]
    if perms.get("subagents") and not cap["subagentes"]:
        t.quitado.append("subagentes")
    if perms.get("internet") and not cap["web"]:
        t.quitado.append("búsqueda web")
    if prov == "opencode":
        if not t.modelo:
            t.error = "Elige un modelo de OpenCode en Ajustes → Motor de IA (opencode/…, opencode-go/… u openrouter/…)"
        elif not t.modelo.startswith(PREFIJOS_OPENCODE):
            t.error = f"El modelo «{t.modelo}» no vale para OpenCode: empieza por opencode/, opencode-go/ u openrouter/ (Ajustes → Motor de IA)"
        elif not t.modelo.startswith(SUSCRIPCION) and gasto_mes(db) >= limite():
            t.error = f"Has llegado al límite de gasto de OpenCode de este mes ({limite():.2f} $). Súbelo en Ajustes → Motor de IA."
    return t
