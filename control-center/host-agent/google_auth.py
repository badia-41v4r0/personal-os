"""Renovación de los permisos de Google desde el panel (solo el Host Agent toca `secrets/`).

- `status()`: edad del token de cada cuenta (mtime del archivo, igual que build.py y renovar-google.sh) y días que
  le quedan en modo Prueba (7). Nunca devuelve el contenido del token.
- `auth_url()`: URL de consentimiento y un `state` aleatorio de un solo uso (10 min, en memoria).
- `exchange()`: recibe lo que el usuario pega (la dirección final `http://127.0.0.1:8765/?state=…&code=…` o solo el
  código), valida el `state` y canjea el código con `gcal.canjear`.

El cliente OAuth es de escritorio: Google solo redirige a 127.0.0.1, así que en el móvil la página final no carga;
basta con copiar su dirección.
"""
import re
import secrets
import sys
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "collectors"))
import gcal  # noqa: E402

DIAS_PRUEBA = 7
STATE_TTL = 600
MAX_PENDING = 8
_pending: dict[str, tuple[str, float]] = {}  # state -> (cuenta, creado)
CODE_RE = re.compile(r"^[A-Za-z0-9._/~+-]{10,512}$")


class GoogleError(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status, self.msg = status, msg


def cuentas() -> list[str]:
    return list(gcal.CUENTAS)


def _check(cuenta: str) -> None:
    if cuenta not in gcal.CUENTAS:
        raise GoogleError(404, "Cuenta desconocida")


def status(now: float | None = None) -> list[dict]:
    now = time.time() if now is None else now
    out = []
    for nombre, (token, _scopes, email) in gcal.CUENTAS.items():
        item = {"cuenta": nombre, "email": email, "autorizada": token.exists(), "edad_dias": None,
                "dias_restantes": None}
        if token.exists():
            edad = max(0.0, (now - token.stat().st_mtime) / 86400)
            item["edad_dias"] = round(edad, 2)
            item["dias_restantes"] = round(DIAS_PRUEBA - edad, 2)
        out.append(item)
    return out


def _purge(now: float) -> None:
    for k in [k for k, (_, t) in _pending.items() if now - t > STATE_TTL]:
        _pending.pop(k, None)


def auth_url(cuenta: str, now: float | None = None) -> dict:
    _check(cuenta)
    now = time.time() if now is None else now
    _purge(now)
    # una sola renovación en curso por cuenta: la nueva invalida la anterior
    for k in [k for k, (c, _) in _pending.items() if c == cuenta]:
        _pending.pop(k, None)
    if len(_pending) >= MAX_PENDING:
        raise GoogleError(429, "Demasiadas renovaciones en curso")
    state = secrets.token_urlsafe(24)
    try:
        url = gcal.url_autorizacion(cuenta, state)
    except gcal.Error as e:
        raise GoogleError(503, str(e))
    _pending[state] = (cuenta, now)
    return {"url": url, "expira_s": STATE_TTL}


def parse_pasted(text: str) -> tuple[str | None, str]:
    """Devuelve (state, code) de lo pegado: una URL con ?code=…&state=…, solo la query, o el código a secas."""
    text = (text or "").strip()
    if not text or len(text) > 2048:
        raise GoogleError(422, "Pega la dirección completa a la que te llevó Google")
    if "code=" in text:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(text if "://" in text else "http://x/?" + text.lstrip("?"))
                                  .query)
        code, state = q.get("code", [""])[0], q.get("state", [None])[0]
    else:
        code, state = text, None
    if not CODE_RE.match(code):
        raise GoogleError(422, "No encuentro el código en lo que has pegado")
    return state, code


def exchange(cuenta: str, pasted: str, now: float | None = None) -> dict:
    _check(cuenta)
    now = time.time() if now is None else now
    _purge(now)
    state, code = parse_pasted(pasted)
    if state is None:
        raise GoogleError(422, "Falta el parámetro state: pega la dirección completa, no solo el código")
    ent = _pending.get(state)
    if not ent or ent[0] != cuenta:
        raise GoogleError(409, "Esta renovación ha caducado o no es de esta cuenta: pulsa Renovar otra vez")
    _pending.pop(state, None)  # un solo uso
    try:
        gcal.canjear(code, cuenta)
    except gcal.Error as e:
        raise GoogleError(502, str(e))
    return {"ok": True, "cuenta": cuenta}
