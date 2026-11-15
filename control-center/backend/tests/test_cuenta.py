"""Usuario inicial admin/admin: obliga a cambiarlo antes de usar el panel. Cambio de usuario y contraseña en Ajustes."""
import json

from app import db
from app.cli import crear_admin_inicial
from app.models import User
from tests.conftest import ORIGIN, PW


def _login(client, u, p):
    r = client.post("/api/v1/auth/login", json={"username": u, "password": p}, headers={"Origin": ORIGIN})
    return r, ({"Origin": ORIGIN, "X-CSRF-Token": r.json()["csrf_token"]} if r.status_code == 200 else None)


def _solo_admin(settings):
    with db.session_scope() as s:
        for u in s.query(User).all():
            s.delete(u)
    crear_admin_inicial()


def test_admin_admin_obliga_a_cambiar(client, settings):
    _solo_admin(settings)
    r, h = _login(client, "admin", "admin")
    assert r.status_code == 200
    me = client.get("/api/v1/auth/me").json()
    assert me["username"] == "admin" and me["must_change_password"] is True
    assert client.get("/api/v1/instancia").status_code == 403  # nada más hasta cambiarla
    assert client.post("/api/v1/auth/cuenta", headers=h, json={"actual": "admin"}).status_code == 422  # sin contraseña nueva no vale
    assert client.post("/api/v1/auth/cuenta", headers=h, json={"actual": "admin", "nueva": "corta"}).status_code == 422
    assert client.post("/api/v1/auth/cuenta", headers=h, json={"actual": "admin", "nueva": "admin"}).status_code == 422
    r = client.post("/api/v1/auth/cuenta", headers=h, json={"actual": "admin", "usuario": "ana", "nueva": "una frase bastante larga"})
    assert r.status_code == 200 and r.json()["username"] == "ana"
    assert client.get("/api/v1/instancia").status_code == 200
    assert _login(client, "admin", "admin")[0].status_code == 401
    assert _login(client, "ana", "una frase bastante larga")[0].status_code == 200


def test_crear_admin_no_toca_usuarios_existentes(settings):
    crear_admin_inicial()  # ya hay un usuario (el de las pruebas)
    with db.session_scope() as s:
        assert s.query(User).filter_by(username="admin").count() == 0


def test_cambio_pide_la_actual_y_cierra_otras_sesiones(client, auth):
    otra = client.__class__(client.app, base_url="http://127.0.0.1:8770")
    assert otra.post("/api/v1/auth/login", json={"username": "ana", "password": PW}, headers={"Origin": ORIGIN}).status_code == 200
    assert client.post("/api/v1/auth/cuenta", headers=auth, json={"actual": "mal", "nueva": "otra frase bastante larga"}).status_code == 403
    r = client.post("/api/v1/auth/cuenta", headers=auth, json={"actual": PW, "nueva": "otra frase bastante larga"})
    assert r.status_code == 200
    assert otra.get("/api/v1/auth/me").status_code == 401  # la otra sesión ya no vale
    assert client.get("/api/v1/auth/me").status_code == 200  # la propia sigue


def test_usuario_no_valido_o_repetido(client, auth):
    assert client.post("/api/v1/auth/cuenta", headers=auth, json={"actual": PW, "usuario": "A B"}).status_code == 422


def test_nombre_del_asistente(client, auth, config_instancia):
    import ajustes
    assert ajustes.asistente() == "Jarvis" and client.get("/api/v1/instancia").json()["asistente"] == "Jarvis"
    assert client.put("/api/v1/instancia/config/perfil", headers=auth, json={"nombre": "Ana", "asistente": "Friday"}).status_code == 200
    assert client.get("/api/v1/instancia").json()["asistente"] == "Friday"
    assert ajustes.render("Eres {{asistente}}, de {{nombre}}") == "Eres Friday, de Ana"
    inicio = next(m for m in client.get("/api/v1/instancia").json()["modulos"] if m["id"] == "inicio")
    assert inicio["descripcion"].startswith("Friday,")
    assert client.put("/api/v1/instancia/config/perfil", headers=auth, json={"asistente": "x" * 41}).status_code == 422


def test_ninguna_instruccion_dice_jarvis_a_fuego():
    from app.config import ROOT
    import re
    for f in (ROOT / "control-center/agents").rglob("*.md"):
        assert not re.search(r"\bJarvis\b(?![/-])", f.read_text(encoding="utf-8")), f.name
