import asyncio
import base64
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pywebpush import WebPushException

from app import db as dbm
from app.core import notifications as n
from app.models import Notification, PushSubscription

APPLE = "https://web.push.apple.com/QGabc"
KEYS = {"p256dh": "B" * 87, "auth": "a" * 22}


@pytest.fixture()
def enviados(monkeypatch):
    calls = []

    def fake(info, data, **kw):
        calls.append({"info": info, "data": json.loads(data), **kw})
    monkeypatch.setattr("pywebpush.webpush", fake)
    monkeypatch.setattr(n, "is_quiet", lambda now=None: False)
    return calls


def sub(client, auth, endpoint=APPLE):
    return client.post("/api/v1/push/subscriptions", json={"endpoint": endpoint, "keys": KEYS, "label": "iPhone"}, headers=auth)


def test_clave_publica_estable_y_privada_protegida(client, auth, settings):
    a = client.get("/api/v1/push/config").json()["public_key"]
    assert a == client.get("/api/v1/push/config").json()["public_key"] and len(a) == 87
    assert (settings.data_dir / "vapid.pem").stat().st_mode & 0o077 == 0


@pytest.mark.parametrize("url", ["http://web.push.apple.com/x", "https://169.254.169.254/x", "https://evil.com/push.apple.com",
                                 "https://push.apple.com.evil.com/x", "https://web.push.apple.com:8443/x"])
def test_rechaza_endpoints_que_no_son_de_push(client, auth, url):
    assert sub(client, auth, url).status_code == 422


def test_suscribir_es_idempotente(client, auth):
    assert sub(client, auth).status_code == 200 and sub(client, auth).status_code == 200
    assert len(client.get("/api/v1/push/config").json()["subscriptions"]) == 1


class SesionFalsa:
    """Sustituye solo la salida HTTP: la firma y el cifrado de pywebpush se ejecutan de verdad."""

    def __init__(self):
        self.peticiones = []

    def post(self, url, data=None, headers=None, timeout=None):
        self.peticiones.append({"url": url, "data": data, "headers": headers})
        return SimpleNamespace(status_code=201, text="", reason="Created", headers={})


@pytest.mark.parametrize("origen", ["https://equipo.tailnet-ejemplo.ts.net:10000", "https://panel.example", "http://127.0.0.1:8770"])
def test_envio_real_firma_y_cifra(client, auth, settings, monkeypatch, origen):
    """Sin simular webpush: así se detecta que py_vapid rechace la identidad del servidor."""
    from dataclasses import replace

    import pywebpush
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization

    from app import config
    config.set_settings(replace(settings, allowed_origins=(origen,)))
    priv = ec.generate_private_key(ec.SECP256R1())
    pub = priv.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()  # noqa: E731
    sesion = SesionFalsa()
    real = pywebpush.webpush
    monkeypatch.setattr("pywebpush.webpush", lambda *a, **k: real(*a, requests_session=sesion, **k))
    with dbm.session_scope() as s:
        s.add(PushSubscription(endpoint=APPLE, p256dh=b64(pub), auth=b64(b"0123456789abcdef"), label="iPhone"))
    aviso = n.crear("action", "Título", "Cuerpo con ñ")
    assert n._entregar(aviso) == 1
    p = sesion.peticiones[0]
    assert p["url"] == APPLE and p["headers"]["authorization"].startswith("vapid t=") and "k=" in p["headers"]["authorization"]
    token = p["headers"]["authorization"].split("t=")[1].split(",")[0]
    claims = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
    assert claims["aud"] == "https://web.push.apple.com"
    assert ":10000" not in claims["sub"]
    assert b"Cuerpo" not in p["data"]  # va cifrado


def test_el_endpoint_completo_no_se_expone(client, auth):
    sub(client, auth)
    assert "QGabc" not in client.get("/api/v1/push/config").text


def test_prueba_entrega_y_queda_en_bandeja(client, auth, enviados):
    sub(client, auth)
    r = client.post("/api/v1/push/test", headers=auth)
    assert r.json()["pushed"] == 1
    assert enviados[0]["data"]["url"] == "/avisos/" and enviados[0]["headers"]["Urgency"] == "high"
    bandeja = client.get("/api/v1/notifications").json()
    assert bandeja[0]["pushed"] == 1 and client.get("/api/v1/notifications/count").json()["unread"] == 1
    assert client.get("/api/v1/push/config").json()["subscriptions"][0]["last_ok_at"]


def test_leer_avisos(client, auth, enviados):
    a = n.crear("info", "uno")
    n.crear("info", "dos")
    client.post(f"/api/v1/notifications/{a['id']}/read", headers=auth)
    assert client.get("/api/v1/notifications/count").json()["unread"] == 1
    client.post("/api/v1/notifications/read-all", headers=auth)
    assert client.get("/api/v1/notifications/count").json()["unread"] == 0


def test_dispositivo_que_ya_no_existe_se_borra(client, auth, monkeypatch):
    sub(client, auth)

    def gone(*a, **k):
        raise WebPushException("gone", response=SimpleNamespace(status_code=410, text=""))
    monkeypatch.setattr("pywebpush.webpush", gone)
    client.post("/api/v1/push/test", headers=auth)
    assert client.get("/api/v1/push/config").json()["subscriptions"] == []


def test_fallo_de_red_no_pierde_el_aviso(client, auth, monkeypatch):
    sub(client, auth)

    def caida(*a, **k):
        raise OSError("sin red")
    monkeypatch.setattr("pywebpush.webpush", caida)
    assert client.post("/api/v1/push/test", headers=auth).json()["pushed"] == 0
    assert client.get("/api/v1/notifications").json()[0]["title"] == "Prueba de avisos"
    assert "sin red" in client.get("/api/v1/push/config").json()["subscriptions"][0]["last_error"]


def test_silencio_nocturno_solo_para_info(client, auth, monkeypatch, enviados):
    sub(client, auth)
    monkeypatch.setattr(n, "is_quiet", lambda now=None: True)
    assert asyncio.run(n.enviar("info", "de noche"))["pushed"] == 0
    assert asyncio.run(n.enviar("critical", "urgente"))["pushed"] == 1
    assert asyncio.run(n.enviar("silent", "callado"))["pushed"] == 0


@pytest.mark.parametrize("h,m,quiet", [(22, 59, False), (23, 0, True), (3, 0, True), (7, 29, True), (7, 30, False), (12, 0, False)])
def test_horas_de_silencio(h, m, quiet):
    assert n.is_quiet(datetime(2026, 11, 4, h, m, tzinfo=n.TZ)) is quiet


def test_spool_convierte_y_limpia(client, auth, settings, enviados):
    d = settings.data_dir / "avisos"
    d.mkdir(parents=True)
    (d / "1.json").write_text(json.dumps({"text": "Título\nDetalle", "level": "critical", "url": "/monitor/"}))
    (d / "2.json").write_text("no es json")
    (d / "3.json").write_text(json.dumps({"text": "externa", "url": "https://evil.example/"}))
    (d / ".tmp.abc").write_text("a medias")
    assert asyncio.run(n.ingest_spool()) == 2
    assert sorted(p.name for p in d.iterdir()) == [".tmp.abc"]
    rows = {x["title"]: x for x in client.get("/api/v1/notifications").json()}
    assert rows["Título"]["level"] == "critical" and rows["Título"]["body"] == "Detalle" and rows["Título"]["url"] == "/monitor/"
    assert rows["externa"]["url"] == "/avisos/"


def test_prueba_diaria_una_vez_al_dia_y_solo_la_primera_semana(client, auth, enviados):
    sub(client, auth)
    hoy = datetime.now(timezone.utc).astimezone(n.TZ).replace(hour=13)
    assert asyncio.run(n.daily_test(hoy)) is True
    assert asyncio.run(n.daily_test(hoy)) is False
    assert asyncio.run(n.daily_test(hoy.replace(hour=9) + timedelta(days=1))) is False
    assert asyncio.run(n.daily_test(hoy + timedelta(days=8))) is False


def test_retencion_conserva_lo_no_leido(client):
    with dbm.session_scope() as s:
        s.add(Notification(title="vieja leida", read_at=dbm.utcnow() - timedelta(days=100)))
        s.add(Notification(title="vieja sin leer", ts=dbm.utcnow() - timedelta(days=100)))
    with dbm.session_scope() as s:
        n.prune(s)
    with dbm.session_scope() as s:
        assert [x.title for x in s.query(Notification)] == ["vieja sin leer"]


def test_suscripcion_auditada(client, auth):
    sub(client, auth)
    assert any(a["action"] == "push.subscribe" for a in client.get("/api/v1/audit").json())
