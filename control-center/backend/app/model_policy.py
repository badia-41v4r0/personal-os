"""Política común de relevo de modelos. Hoy solo sugiere: Jarvis y el orquestador siguen en Claude.

No ejecuta CLIs ni guarda secretos: recibe lecturas normalizadas de uso.  Es pura para que
se pruebe sin gastar cuota, y solo existe aquí: orq-top lee el resultado, no la repite.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

THRESHOLD = 0.85
ORDER = ("claude", "antigravity-flash", "antigravity-opus", "codex-terra")
WEEKLY = ("seven_day", "weekly", "week")
MAX_AGE = timedelta(minutes=30)  # más que dos rondas de sondas: una lectura más vieja ya no cuenta


@dataclass(frozen=True)
class Choice:
    provider: str
    model: str
    emergency: bool = False
    reason: str = ""


def _time(value) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.astimezone(timezone.utc).replace(tzinfo=None) if d.tzinfo else d


def over_limit(windows: list[dict], threshold: float = THRESHOLD, now: datetime | None = None) -> bool:
    """Una ventana cuenta hasta el 85%, salvo si ya se reinició después de leerla."""
    for w in windows:
        reset = _time(w.get("resets_at"))
        if now and reset and reset <= now:
            continue
        if isinstance(w.get("utilization"), (int, float)) and w["utilization"] >= threshold:
            return True
    return False


def usable(row: dict, now: datetime) -> bool:
    """Sin lectura real y reciente no se sabe si queda cuota: no se elige."""
    ts = _time(row.get("ts"))
    return bool(row.get("available") and row.get("windows")) and (ts is None or now - ts <= MAX_AGE)


def choose(rows: dict[str, dict], now: datetime | None = None) -> Choice:
    """Elige un proveedor con cuota.

    El límite voluntario de Claude es solo el semanal; el de los demás, cualquier ventana
    que informen.  Si no queda ninguno, Claude es a propósito el último recurso: su límite
    real sigue protegiendo la cuenta.
    """
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    c = rows.get("claude", {})
    weekly = [w for w in c.get("windows", []) if w.get("name") in WEEKLY]
    if usable(c, now) and weekly and not over_limit(weekly, now=now):
        return Choice("claude", "claude", reason="Claude semanal por debajo del 85%")
    for provider in ORDER[1:]:
        row = rows.get(provider, {})
        if usable(row, now) and not over_limit(row.get("windows", []), now=now):
            return Choice(provider, str(row.get("model") or provider), reason="siguiente proveedor con cuota")
    if usable(c, now):
        return Choice("claude", "claude", emergency=True, reason="último recurso: alternativas agotadas o sin lectura")
    return Choice("", "", reason="ningún proveedor con lectura válida")
