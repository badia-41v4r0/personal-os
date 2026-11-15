from app import agenda


def test_agenda_tolera_fallos(client, auth, monkeypatch, settings):
    agenda._cache.clear()
    import gcal

    class Caducado(Exception):
        pass

    def boom(d):
        raise Caducado("invalid_grant")

    monkeypatch.setattr(gcal, "agenda", boom)
    monkeypatch.setattr(agenda, "correo", lambda: {"gmail": {"error": "sin red"}})
    monkeypatch.setattr(agenda, "uni_semana", lambda: {"bloques": ["FP"], "entregas": [], "eventos": [], "objetivos": []})
    monkeypatch.setattr(agenda, "tareas_hoy", lambda: {"hoy": [], "proximas": [], "sin_fecha": [], "hechas_hoy": []})
    r = client.get("/api/v1/agenda").json()
    assert "caducado" in r["calendario"]["error"] and r["calendario"]["eventos"] == []
    assert r["correo"]["gmail"]["error"] == "sin red"
    assert r["uni"]["bloques"] == ["FP"]


def test_agenda_cache(client, auth, monkeypatch):
    agenda._cache.clear()
    n = {"c": 0}

    def cal(d):
        n["c"] += 1
        return {"eventos": [], "error": None}

    monkeypatch.setattr(agenda, "calendario", cal)
    monkeypatch.setattr(agenda, "correo", lambda: {})
    monkeypatch.setattr(agenda, "uni_semana", lambda: {})
    monkeypatch.setattr(agenda, "tareas_hoy", lambda: {})
    client.get("/api/v1/agenda")
    client.get("/api/v1/agenda")
    assert n["c"] == 1
    client.get("/api/v1/agenda?refresh=true")
    assert n["c"] == 2


def test_tareas_reales_se_leen(client, auth):
    r = client.get("/api/v1/tasks")
    assert r.status_code == 200 and "pendientes" in r.json()
