"""Google Calendar para Jarvis (solo librería estándar).

Límites de seguridad (en el código, no en el prompt):
- Lee todos los calendarios visibles; solo escribe en el principal.
- Nunca añade invitados ni envía avisos (sendUpdates=none).
- Solo modifica o borra eventos creados por Jarvis (marcados con jarvis=1).

Uso:
  python3 gcal.py auth [--cuenta secundaria]             # en el PC (abre el navegador); secundaria = solo Gmail de otra cuenta
  python3 gcal.py agenda [--dias N]                       # eventos de hoy (y N días más)
  python3 gcal.py crear --titulo T --inicio 2026-10-02T17:00 --fin 2026-10-02T18:00 [--descripcion D] [--lugar L]
  python3 gcal.py crear --titulo T --dia 2026-10-02       # evento de día completo
  python3 gcal.py mover --id ID --inicio ... --fin ...
  python3 gcal.py borrar --id ID
"""
import argparse
import http.server
import json
import os
import secrets
import ssl
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import ajustes

TZ = ZoneInfo(os.environ.get("POS_TZ", "Europe/Madrid"))
DIR = Path(os.environ.get("GCAL_DIR", Path(__file__).resolve().parent.parent / "secrets"))
CLIENT = DIR / "gcal-client.json"
TOKEN = DIR / "gcal-token.json"
TOKEN_2 = DIR / "gmail-secundaria-token.json"  # otra cuenta de Google (p. ej. la de la universidad o el trabajo): solo Gmail
# Un solo token para calendario y correo (correo.py): así se renueva una vez cada 7 días.
# gmail.compose permitiría enviar, pero correo.py solo llama a drafts.create.
SCOPES = ("https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/calendar.calendarlist.readonly "
          "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.compose")
GMAIL_SCOPES = "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.compose"
# El correo de cada cuenta (config correo.json) solo sirve para preseleccionarla al autorizar
_CORREO = ajustes.leer("correo").get("cuentas") or {}
CUENTAS = {"personal": (TOKEN, SCOPES, (_CORREO.get("gmail") or {}).get("email", "")),
           "secundaria": (TOKEN_2, GMAIL_SCOPES, (_CORREO.get("secundaria") or {}).get("email", ""))}
API = "https://www.googleapis.com/calendar/v3"
MARCA = {"private": {"jarvis": "1"}}


class Error(Exception):
    pass


class Caducado(Error):
    """El refresh token ya no vale: hay que volver a autorizar (gcal.py auth)."""


def _abrir(req, intentos: int = 4):
    """urlopen con reintentos ante cortes de red y errores 5xx (p. ej. SSL EOF al despertar la red)."""
    for i in range(intentos):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            if e.code < 500 or i == intentos - 1:
                raise
        except (urllib.error.URLError, ssl.SSLError, ConnectionError, TimeoutError):
            if i == intentos - 1:
                raise
        time.sleep(3 * (i + 1))


def _post(url: str, data: dict) -> dict:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), method="POST")
    return json.loads(_abrir(req)[1])


def _client() -> dict:
    if not CLIENT.exists():
        raise Error("Google Calendar no está configurado (falta gcal-client.json).")
    c = json.loads(CLIENT.read_text())
    return c.get("installed") or c.get("web")


def _access_token(token: Path | None = None) -> str:
    token = token or TOKEN
    if not token.exists():
        raise Error(f"Google no está autorizado (falta {token.name}).")
    c, t = _client(), json.loads(token.read_text())
    try:
        r = _post(c["token_uri"], {"client_id": c["client_id"], "client_secret": c["client_secret"],
                                   "refresh_token": t["refresh_token"], "grant_type": "refresh_token"})
    except urllib.error.HTTPError as e:
        cuerpo = e.read().decode()
        if "invalid_grant" in cuerpo:
            raise Caducado("El permiso de Google ha caducado: renuévalo en el PC con python3 collectors/gcal.py auth.")
        raise Error(f"Google respondió {e.code} al renovar el acceso: {cuerpo[:150]}")
    return r["access_token"]


def _api(method: str, path: str, token: str, params: dict | None = None, body: dict | None = None):
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        estado, cuerpo = _abrir(req)
        return json.loads(cuerpo) if estado != 204 and cuerpo else None
    except urllib.error.HTTPError as e:
        raise Error(f"Google respondió {e.code}: {e.read().decode()[:200]}")


# ---------- Autorización (solo en el PC) ----------

PUERTO = int(os.environ.get("POS_OAUTH_PORT", "8765"))
REDIRECT = f"http://127.0.0.1:{PUERTO}"


def url_autorizacion(cuenta: str, estado: str) -> str:
    """URL de consentimiento de Google para `cuenta`. El redirect es el de bucle local (cliente de escritorio)."""
    _, scopes, email = CUENTAS[cuenta]
    c = _client()
    return c["auth_uri"] + "?" + urllib.parse.urlencode({
        "client_id": c["client_id"], "redirect_uri": REDIRECT, "response_type": "code", "scope": scopes,
        "access_type": "offline", "prompt": "consent", "state": estado, "login_hint": email})


def canjear(code: str, cuenta: str) -> Path:
    """Cambia el `code` por el refresh token y lo guarda (600). Lanza Error si Google no lo devuelve."""
    token = CUENTAS[cuenta][0]
    c = _client()
    try:
        r = _post(c["token_uri"], {"code": code, "client_id": c["client_id"], "client_secret": c["client_secret"],
                                   "redirect_uri": REDIRECT, "grant_type": "authorization_code"})
    except urllib.error.HTTPError as e:
        raise Error(f"Google rechazó el código ({e.code}): puede haber caducado o usarse ya.")
    if "refresh_token" not in r:
        raise Error("Google no devolvió refresh_token. Revoca el acceso en tu cuenta y repite.")
    token.write_text(json.dumps({"refresh_token": r["refresh_token"]}))
    token.chmod(0o600)
    return token


def auth(abrir: bool = False, espera_h: float | None = None, cuenta: str = "personal") -> bool:
    """Autoriza en el navegador. Con abrir=True abre la pestaña sola (bin/renovar-google.sh).
    cuenta: personal (calendario + Gmail) o secundaria (solo Gmail)."""
    estado, puerto = secrets.token_urlsafe(16), PUERTO
    url = url_autorizacion(cuenta, estado)
    recibido = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if q.get("state", [""])[0] == estado and "code" in q:
                recibido["code"] = q["code"][0]
                msg = f"Listo. {ajustes.asistente()} ya tiene acceso a tu calendario y a tu correo (leer y borradores). Puedes cerrar esta pestaña."
            else:
                msg = "Algo no ha ido bien. Vuelve a intentarlo."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(msg.encode())

        def log_message(self, *a):
            pass

    print("Abre esta URL en el navegador e inicia sesión con tu cuenta de Google:\n\n" + url + "\n")
    srv = http.server.HTTPServer(("127.0.0.1", puerto), H)
    if abrir:
        # Sin esperar a xdg-open: si Chromium no estaba abierto, xdg-open no vuelve hasta que se cierra
        # el navegador y el servidor no atendía la respuesta de Google (la pestaña se quedaba cargando).
        # Con systemd-run el navegador va en su propia unidad y no muere si se para jarvis-google.
        import shutil
        import subprocess
        orden = ["xdg-open", url]
        if shutil.which("systemd-run"):
            orden = ["systemd-run", "--user", "--quiet", "--collect",
                     *[f"--setenv={k}={os.environ[k]}" for k in ("WAYLAND_DISPLAY", "DISPLAY", "XDG_RUNTIME_DIR",
                                                                 "DBUS_SESSION_BUS_ADDRESS") if k in os.environ],
                     *orden]
        subprocess.Popen(orden, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    limite = time.time() + espera_h * 3600 if espera_h else None
    srv.timeout = 60
    while "code" not in recibido:
        if limite and time.time() > limite:
            srv.server_close()
            return False
        srv.handle_request()
    srv.server_close()
    token = canjear(recibido["code"], cuenta)
    print("Autorizado. Token guardado en", token)
    return True


# ---------- Lectura ----------

def agenda(dias: int = 0, hoy: date | None = None) -> list[dict]:
    hoy = hoy or datetime.now(TZ).date()
    token = _access_token()
    ini = datetime.combine(hoy, datetime.min.time(), TZ)
    fin = ini + timedelta(days=dias + 1)
    cals = _api("GET", "/users/me/calendarList", token, {"minAccessRole": "reader"})["items"]
    eventos = []
    for cal in cals:
        if not cal.get("selected") and not cal.get("primary"):
            continue
        res = _api("GET", f"/calendars/{urllib.parse.quote(cal['id'])}/events", token, {
            "timeMin": ini.isoformat(), "timeMax": fin.isoformat(), "singleEvents": "true",
            "orderBy": "startTime", "maxResults": 100})
        for e in res.get("items", []):
            if e.get("status") == "cancelled":
                continue
            s, f = e["start"], e["end"]
            todo_el_dia = "date" in s
            eventos.append({
                "id": e["id"], "calendario": cal.get("summaryOverride") or cal.get("summary"),
                "titulo": e.get("summary", "(sin título)"), "lugar": e.get("location", ""),
                "dia": s.get("date") or datetime.fromisoformat(s["dateTime"]).astimezone(TZ).date().isoformat(),
                # último día que ocupa (en Google el final de los de día completo es exclusivo)
                "hasta": (date.fromisoformat(f["date"]) - timedelta(days=1)).isoformat() if todo_el_dia
                         else datetime.fromisoformat(f["dateTime"]).astimezone(TZ).date().isoformat(),
                "inicio": None if todo_el_dia else datetime.fromisoformat(s["dateTime"]).astimezone(TZ).strftime("%H:%M"),
                "fin": None if todo_el_dia else datetime.fromisoformat(f["dateTime"]).astimezone(TZ).strftime("%H:%M"),
                "de_jarvis": e.get("extendedProperties", {}).get("private", {}).get("jarvis") == "1",
            })
    eventos = [e for e in eventos if e["hasta"] >= hoy.isoformat()]  # descarta los que ya terminaron
    eventos.sort(key=lambda e: (e["dia"], e["inicio"] or ""))
    return eventos


# ---------- Escritura (solo calendario principal, sin invitados) ----------

def _cuando(args) -> dict:
    if args.dia:
        d = date.fromisoformat(args.dia)
        return {"start": {"date": d.isoformat()}, "end": {"date": (d + timedelta(days=1)).isoformat()}}
    if not (args.inicio and args.fin):
        raise Error("Indica --dia, o --inicio y --fin (AAAA-MM-DDTHH:MM).")
    i, f = (datetime.fromisoformat(x).replace(tzinfo=TZ) for x in (args.inicio, args.fin))
    if f <= i:
        raise Error("El fin debe ser posterior al inicio.")
    return {"start": {"dateTime": i.isoformat(), "timeZone": TZ.key},
            "end": {"dateTime": f.isoformat(), "timeZone": TZ.key}}


def _evento_propio(token: str, eid: str) -> dict:
    e = _api("GET", f"/calendars/primary/events/{urllib.parse.quote(eid)}", token)
    if e.get("extendedProperties", {}).get("private", {}).get("jarvis") != "1":
        raise Error(f"Ese evento no lo creó {ajustes.asistente()}: no puedo modificarlo ni borrarlo.")
    return e


def crear(args):
    token = _access_token()
    body = {"summary": args.titulo, "description": args.descripcion or "", "location": args.lugar or "",
            "extendedProperties": MARCA, "attendees": [], **_cuando(args)}
    e = _api("POST", "/calendars/primary/events", token, {"sendUpdates": "none"}, body)
    print(json.dumps({"ok": True, "id": e["id"], "titulo": e["summary"], "enlace": e.get("htmlLink")}, ensure_ascii=False))


def mover(args):
    token = _access_token()
    e = _evento_propio(token, args.id)
    e.update(_cuando(args))
    e["attendees"] = []
    _api("PUT", f"/calendars/primary/events/{urllib.parse.quote(args.id)}", token, {"sendUpdates": "none"}, e)
    print(json.dumps({"ok": True, "id": args.id}, ensure_ascii=False))


def borrar(args):
    token = _access_token()
    _evento_propio(token, args.id)
    _api("DELETE", f"/calendars/primary/events/{urllib.parse.quote(args.id)}", token, {"sendUpdates": "none"})
    print(json.dumps({"ok": True, "id": args.id, "borrado": True}, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description=f"Google Calendar para {ajustes.asistente()}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    au = sub.add_parser("auth")
    au.add_argument("--abrir", action="store_true", help="abre la pestaña en el navegador")
    au.add_argument("--espera", type=float, help="horas máximas esperando a que aceptes")
    au.add_argument("--cuenta", choices=["personal", "secundaria"], default="personal")
    a = sub.add_parser("agenda")
    a.add_argument("--dias", type=int, default=0)
    for nombre in ("crear", "mover"):
        p = sub.add_parser(nombre)
        if nombre == "crear":
            p.add_argument("--titulo", required=True)
            p.add_argument("--descripcion")
            p.add_argument("--lugar")
        else:
            p.add_argument("--id", required=True)
        p.add_argument("--dia")
        p.add_argument("--inicio")
        p.add_argument("--fin")
    b = sub.add_parser("borrar")
    b.add_argument("--id", required=True)
    args = ap.parse_args()
    try:
        if args.cmd == "auth":
            sys.exit(0 if auth(args.abrir, args.espera, args.cuenta) else 2)
        elif args.cmd == "agenda":
            print(json.dumps(agenda(args.dias), ensure_ascii=False, indent=1))
        else:
            {"crear": crear, "mover": mover, "borrar": borrar}[args.cmd](args)
    except (Error, urllib.error.URLError) as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
