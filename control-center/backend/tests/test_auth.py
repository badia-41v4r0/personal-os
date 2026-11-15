from tests.conftest import ORIGIN, PW


def test_health_publica(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["database"] == "ok"
    assert r.json()["host_agent"] == "down"  # en pruebas no hay socket


def test_sin_sesion_401(client):
    for path in ("/api/v1/auth/me", "/api/v1/events", "/api/v1/system/metrics", "/api/v1/sessions/main/messages"):
        assert client.get(path).status_code == 401, path


def test_login_ok_y_cookie(client):
    r = client.post("/api/v1/auth/login", json={"username": "ana", "password": PW}, headers={"Origin": ORIGIN})
    assert r.status_code == 200
    sc = r.headers["set-cookie"].lower()
    assert "httponly" in sc and "samesite=strict" in sc
    assert client.get("/api/v1/auth/me").json()["username"] == "ana"


def test_login_origen_ajeno(client):
    r = client.post("/api/v1/auth/login", json={"username": "ana", "password": PW},
                    headers={"Origin": "https://malo.example"})
    assert r.status_code == 403


def test_login_bloqueo_tras_fallos(client):
    for _ in range(5):
        r = client.post("/api/v1/auth/login", json={"username": "ana", "password": "mal"}, headers={"Origin": ORIGIN})
        assert r.status_code == 401
    # Bloqueado: ni con la contraseña buena
    r = client.post("/api/v1/auth/login", json={"username": "ana", "password": PW}, headers={"Origin": ORIGIN})
    assert r.status_code == 401


def test_usuario_inexistente(client):
    r = client.post("/api/v1/auth/login", json={"username": "nadie", "password": PW}, headers={"Origin": ORIGIN})
    assert r.status_code == 401


def test_csrf_obligatorio(client, auth):
    assert client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN}).status_code == 403
    assert client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": "falso"}).status_code == 403
    assert client.post("/api/v1/auth/logout", headers={**auth, "Origin": "https://malo.example"}).status_code == 403
    assert client.post("/api/v1/auth/logout", headers=auth).status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401


def test_auditoria(client, auth):
    rows = client.get("/api/v1/audit").json()
    assert any(r["action"] == "auth.login" and r["outcome"] == "ok" for r in rows)


def test_cabeceras_seguridad(client):
    r = client.get("/api/v1/health")
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"
