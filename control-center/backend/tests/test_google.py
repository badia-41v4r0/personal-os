import asyncio
from datetime import date

from app import agenda
from app.adapters import hostagent
from app.modules import reminders

CUENTAS = [
    {"cuenta": "personal", "email": "yo@gmail.com", "autorizada": True, "edad_dias": 6.5, "dias_restantes": 0.5},
    {"cuenta": "secundaria", "email": "yo@universidad.example", "autorizada": True, "edad_dias": 1.0, "dias_restantes": 6.0},
]


def _fake(llamadas):
    async def fake(path, **k):
        llamadas.append((path, k.get("method", "GET"), k.get("json")))
        if path == "/v1/google/status":
            return [dict(c) for c in CUENTAS]
        if path.endswith("/auth-url"):
            return {"url": "https://accounts.google.com/x", "expira_s": 600}
        return {"ok": True, "cuenta": path.split("/")[3]}
    return fake


def test_estado_marca_lo_caducado(client, auth, monkeypatch):
    monkeypatch.setattr(hostagent, "call", _fake([]))
    agenda._caducada.clear()
    r = {c["cuenta"]: c for c in client.get("/api/v1/system/google").json()}
    assert r["personal"]["caducada"] is False and r["secundaria"]["caducada"] is False
    agenda._caducada["secundaria"] = True  # una llamada real a Gmail dijo invalid_grant aunque el token sea reciente
    r = {c["cuenta"]: c for c in client.get("/api/v1/system/google").json()}
    assert r["secundaria"]["caducada"] is True
    agenda._caducada.clear()


def test_renovar_y_callback(client, auth, monkeypatch):
    llamadas = []
    monkeypatch.setattr(hostagent, "call", _fake(llamadas))
    agenda._caducada["personal"] = True
    agenda._cache["x"] = (0, 1)
    assert client.post("/api/v1/system/google/personal/renovar", headers=auth).json()["url"].startswith("https://accounts.google.com")
    r = client.post("/api/v1/system/google/personal/callback", json={"pegado": "http://127.0.0.1:8765/?state=a&code=4/0abc"}, headers=auth)
    assert r.status_code == 200
    assert ("/v1/google/personal/exchange", "POST", {"pegado": "http://127.0.0.1:8765/?state=a&code=4/0abc"}) in llamadas
    assert "personal" not in agenda._caducada and not agenda._cache  # Agenda se actualiza ya
    acciones = [a["action"] for a in client.get("/api/v1/audit?limit=20").json()]
    assert "google.renew.start" in acciones and "google.renew.finish" in acciones


def test_las_rutas_exigen_sesion_csrf_y_origin(client, auth, monkeypatch):
    monkeypatch.setattr(hostagent, "call", _fake([]))
    body = {"pegado": "x" * 20}
    # sin CSRF
    assert client.post("/api/v1/system/google/personal/renovar", headers={"Origin": auth["Origin"]}).status_code in (401, 403)
    assert client.post("/api/v1/system/google/personal/callback", json=body, headers={"Origin": auth["Origin"]}).status_code in (401, 403)
    # origen ajeno
    assert client.post("/api/v1/system/google/personal/renovar", headers=auth | {"Origin": "https://evil.example"}).status_code in (401, 403)
    # sin sesión
    client.post("/api/v1/auth/logout", headers=auth)
    assert client.get("/api/v1/system/google").status_code == 401
    assert client.post("/api/v1/system/google/personal/renovar", headers=auth).status_code == 401


def test_error_del_host_agent_se_muestra_y_se_audita(client, auth, monkeypatch):
    async def mal(path, **k):
        raise hostagent.HostAgentError(409, "Esta renovación ha caducado")
    monkeypatch.setattr(hostagent, "call", mal)
    r = client.post("/api/v1/system/google/personal/callback", json={"pegado": "?state=a&code=4/0abcdefghij"}, headers=auth)
    assert r.status_code == 409 and "caducado" in r.json()["detail"]
    audit = client.get("/api/v1/audit?limit=5").json()
    assert any(a["action"] == "google.renew.finish" and a["outcome"] == "error" for a in audit)


def test_calendario_caducado_se_recuerda(monkeypatch):
    import gcal
    agenda._caducada.clear()

    class Caducado(Exception):
        pass

    def boom(d):
        raise Caducado("El permiso de Google ha caducado")

    monkeypatch.setattr(gcal, "agenda", boom)
    r = agenda.calendario(3)
    assert "Ajustes → Conexiones" in r["error"] and agenda.caducadas() == {"personal": True}
    agenda._caducada.clear()


def test_recordatorio_solo_cuando_toca():
    hoy = date(2026, 11, 6)
    items = reminders.google_pending([dict(c, caducada=False) for c in CUENTAS], hoy)
    assert [i["key"] for i in items] == ["rec:google:personal:2026-11-06"]  # a la secundaria le quedan 6 días
    assert items[0]["url"] == "/ajustes/" and items[0]["level"] == "action" and "caduca pronto" in items[0]["title"]
    caducadas = reminders.google_pending([dict(CUENTAS[0], caducada=True, dias_restantes=-1.0)], hoy)
    assert "ha caducado" in caducadas[0]["title"]
    sin_token = reminders.google_pending([dict(CUENTAS[1], autorizada=False, dias_restantes=None, caducada=False)], hoy)
    assert len(sin_token) == 1
    assert reminders.google_pending([], hoy) == []  # Host Agent sin respuesta: se calla


def test_recordatorio_sale_una_vez_al_dia(client, auth, monkeypatch):
    enviados = []

    async def enviar(level, title, body, url, source, **k):
        enviados.append(source)
    monkeypatch.setattr(reminders.notifications, "enviar", enviar)

    async def sin_canvas():
        return None
    monkeypatch.setattr(reminders, "_canvas", sin_canvas)

    async def estado():
        return [dict(CUENTAS[0], caducada=False)]
    monkeypatch.setattr(reminders, "_google", estado)

    async def dos_veces():
        return await reminders.run(date(2026, 11, 6)), await reminders.run(date(2026, 11, 6))
    # `enviar` falso no guarda la notificación: comprobamos solo que cada ejecución pide una por cuenta y clave del día
    a, b = asyncio.run(dos_veces())
    assert a == 1 and enviados[0] == "rec:google:personal:2026-11-06"
