"""Gateway de modelos: de una necesidad (perfil) a un proveedor concreto.

La política de cuota sigue siendo model_policy.py. Aquí se añade lo que le faltaba para ser real: qué datos admite cada
proveedor y cómo se traduce cada perfil. Solo CLI oficiales, sin API keys.

Claude trabaja con herramientas. Codex y Antigravity entran en **modo consulta**: solo texto, sin herramientas, sin memoria
y sin datos sensibles, encerrados por el Host Agent. Sirven para seguir respondiendo cuando Claude se queda sin cuota.
"""
from dataclasses import dataclass

from ..model_policy import Choice, choose

PROFILES = ("fast", "standard", "deep", "code")


@dataclass(frozen=True)
class Provider:
    key: str
    models: dict[str, str]  # perfil -> modelo
    executes: bool = False
    sensitive_ok: bool = False  # puede recibir datos personales detallados


PROVIDERS: dict[str, Provider] = {
    "claude": Provider("claude", {"fast": "sonnet", "standard": "sonnet", "deep": "opus", "code": "sonnet"}, executes=True, sensitive_ok=True),
    "antigravity-flash": Provider("antigravity-flash", {p: "gemini-3.8-flash-medium" for p in PROFILES}, executes=True),
    "antigravity-opus": Provider("antigravity-opus", {p: "claude-opus-4-6-thinking" for p in PROFILES}, executes=True),
    "codex-terra": Provider("codex-terra", {p: "gpt-5.6-terra" for p in PROFILES}, executes=True),
}


@dataclass(frozen=True)
class Route:
    provider: str
    model: str
    reason: str
    suggested: str | None = None  # lo que la política habría elegido si pudiera ejecutarlo


def route(profile: str, usage: dict[str, dict], sensitive: bool = False) -> Route:
    """Elige proveedor. Si la política apunta a uno que aún no ejecuta, se queda en Claude y deja constancia."""
    if profile not in PROFILES:
        raise ValueError(f"Perfil desconocido: {profile}")
    c: Choice = choose(usage)
    p = PROVIDERS.get(c.provider)
    if p and p.executes and (p.sensitive_ok or not sensitive):
        return Route(p.key, p.models[profile], c.reason)
    fallback = PROVIDERS["claude"]
    motivo = "datos sensibles" if p and p.executes else "sin proveedor disponible"
    return Route(fallback.key, fallback.models[profile], f"{c.reason}. Se queda en Claude: {motivo}", suggested=c.provider)
