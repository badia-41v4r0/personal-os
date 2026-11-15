from datetime import timedelta

import pytest

from app import monitor
from app.db import session_scope, utcnow
from app.models import Alert, Event, MetricSample


def metrics(cpu=10, mem=40, disk=50, temp=60, gpu_t=40):
    return {"cpu": {"pct": cpu}, "memory": {"pct": mem}, "swap": {"pct": 5}, "temperatures": {"k10temp": temp},
            "gpu": [{"util_pct": 1, "vram_used_mb": 1000, "vram_total_mb": 6000, "temp_c": gpu_t}],
            "disks": [{"mount": "/", "pct": disk}], "net": {"bytes_sent": 0, "bytes_recv": 0}}


def snap(**kw):
    s = {"host_agent": True, "metrics": metrics(**{k: v for k, v in kw.items() if k in ("cpu", "mem", "disk", "temp", "gpu_t")}),
         "services": [{"Id": "jarvis-collect.service", "scope": "user", "ActiveState": "inactive", "Result": "success"},
                      {"Id": "docker.service", "scope": "system", "ActiveState": "active"}],
         "containers": [{"Names": "jarvis", "State": "running", "Status": "Up"}], "tmux": True}
    s.update({k: v for k, v in kw.items() if k in ("services", "containers", "tmux", "host_agent")})
    return s


def keys(f):
    return {x.key for x in f}


def test_todo_bien_sin_alertas():
    assert monitor.evaluate(snap(), [{"cpu": 10, "mem": 40}] * 5) == []


def test_cpu_solo_si_es_sostenida():
    assert "cpu:alta" not in keys(monitor.evaluate(snap(cpu=95), [{"cpu": 95, "mem": 1}] * 4 + [{"cpu": 50, "mem": 1}]))
    assert "cpu:alta" in keys(monitor.evaluate(snap(cpu=95), [{"cpu": 95, "mem": 1}] * 5))


def test_disco_temperatura_y_servicios():
    f = monitor.evaluate(snap(disk=98, temp=95, gpu_t=88,
                              services=[{"Id": "jarvis-collect.service", "scope": "user", "ActiveState": "failed", "Result": "exit-code"},
                                        {"Id": "docker.service", "scope": "system", "ActiveState": "inactive"}],
                              containers=[{"Names": "jarvis", "State": "exited", "Status": "Exited (1)"}]), [])
    sev = {x.key: x.severity for x in f}
    assert sev["disco:/"] == "critical" and sev["temp:k10temp"] == "warning" and sev["temp:gpu"] == "warning"
    assert sev["unidad:jarvis-collect.service"] == "critical" and sev["unidad:docker.service"] == "critical"
    assert sev["contenedor:jarvis"] == "critical"


def test_servicio_en_curso_no_es_fallo():
    s = snap(services=[{"Id": "jarvis-google.service", "scope": "user", "ActiveState": "activating", "Result": "success"}])
    assert monitor.evaluate(s, []) == []


def test_host_agent_caido():
    assert keys(monitor.evaluate({"host_agent": False}, [])) == {"hostagent:down"}


@pytest.mark.asyncio
async def test_abrir_resolver_y_avisar_una_vez(settings, monkeypatch):
    sent = []

    async def fake_notify(t):
        sent.append(t)
        return True

    monkeypatch.setattr(monitor, "notify", fake_notify)
    crit = [monitor.Finding("jarvis:tmux", "critical", "Sesión caída")]
    await monitor.apply(crit)
    await monitor.apply(crit)  # sigue abierta: no se duplica ni se vuelve a avisar
    with session_scope() as db:
        assert db.query(Alert).filter_by(status="open").count() == 1
    assert len(sent) == 1
    await monitor.apply([])  # se resuelve sola
    await monitor.apply(crit)  # vuelve a caer en menos de 6 h: alerta nueva, sin aviso repetido
    assert len(sent) == 1
    with session_scope() as db:
        assert db.query(Alert).count() == 2
        assert {e.type for e in db.query(Event)} >= {"alert.raised", "alert.resolved"}


def test_historial_y_retencion(client, auth, settings):
    now = utcnow()
    with session_scope() as db:
        db.add(MetricSample(ts=now - timedelta(days=20), cpu=1, mem=1, swap=0, disk=1))
        for i in range(5):
            db.add(MetricSample(ts=now - timedelta(minutes=5 - i), cpu=10 * i, mem=50, swap=0, disk=40,
                                net_sent=1024 * 60 * i, net_recv=0))
        db.add(Event(type="chat.updated", ts=now - timedelta(days=3), payload={}))
        monitor.prune(db)
    with session_scope() as db:
        assert db.query(MetricSample).count() == 5
        assert db.query(Event).filter_by(type="chat.updated").count() == 0
    h = client.get("/api/v1/system/metrics/history?range=1h").json()
    assert len(h["points"]) == 5 and h["points"][-1]["cpu"] == 40
    assert h["points"][1]["net_up"] == pytest.approx(1.0, rel=0.05)  # 60 KB en 60 s = 1 KB/s
    assert client.get("/api/v1/system/metrics/history?range=99y").status_code == 422


def test_alertas_api(client, auth, settings):
    with session_scope() as db:
        db.add(Alert(key="x", severity="warning", title="Prueba"))
    a = client.get("/api/v1/alerts").json()
    assert a[0]["title"] == "Prueba"
    assert client.post(f"/api/v1/alerts/{a[0]['id']}/resolve", headers=auth).json()["ok"]
    assert client.get("/api/v1/alerts").json() == []
