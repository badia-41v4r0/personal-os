import pytest


@pytest.fixture()
def vault(settings):
    v = settings.vault
    (v / "Jarvis/Areas").mkdir(parents=True)
    (v / "Jarvis/Sistema").mkdir(parents=True)
    (v / ".obsidian").mkdir()
    (v / ".obsidian/app.json").write_text("{}")
    (v / "Jarvis/Panel.md").write_text("# Panel\n[[Tareas]]")
    (v / "Jarvis/Tareas.md").write_text("# Tareas\n- [ ] algo #uni\nVer [[Gym]] y [[Jarvis/Areas/Gym|el gym]]")
    (v / "Jarvis/Areas/Gym.md").write_text("# Gym\nsentadilla")
    (v / "Jarvis/Sistema/estado.json").write_text("{}")
    (settings.vault.parent / "fuera.md").write_text("secreto")
    return v


def test_arbol_oculta_carpetas_ocultas(client, auth, vault):
    names = [i["name"] for i in client.get("/api/v1/memory/tree").json()["items"]]
    assert "Jarvis" in names and ".obsidian" not in names


@pytest.mark.parametrize("bad", ["../fuera.md", "Jarvis/../../fuera.md", ".obsidian/app.json", "/etc/passwd", "Jarvis/\x00x"])
def test_rutas_prohibidas(client, auth, vault, bad):
    assert client.get("/api/v1/memory/file", params={"path": bad}).status_code in (403, 404)


def test_enlace_simbolico_que_sale(client, auth, vault):
    (vault / "Jarvis/link.md").symlink_to(vault.parent / "fuera.md")
    assert client.get("/api/v1/memory/file", params={"path": "Jarvis/link.md"}).status_code == 403


def test_leer_y_editable(client, auth, vault):
    p = client.get("/api/v1/memory/file", params={"path": "Jarvis/Panel.md"}).json()
    assert p["editable"] is False and "build.py" in p["note"]
    g = client.get("/api/v1/memory/file", params={"path": "Jarvis/Areas/Gym.md"}).json()
    assert g["editable"] is True and "copia" in g["note"]
    t = client.get("/api/v1/memory/file", params={"path": "Jarvis/Tareas.md"}).json()
    assert t["editable"] is False and "base de datos" in t["note"]  # las tareas viven en la base: la nota es una copia
    assert client.get("/api/v1/memory/file", params={"path": "Jarvis/Sistema/estado.json"}).json()["editable"] is False


def test_guardar_con_control_de_concurrencia(client, auth, vault):
    t = client.get("/api/v1/memory/file", params={"path": "Jarvis/Areas/Gym.md"}).json()
    r = client.put("/api/v1/memory/file", json={"path": "Jarvis/Areas/Gym.md", "content": "nuevo", "base_sha": t["sha"]}, headers=auth)
    assert r.status_code == 200 and (vault / "Jarvis/Areas/Gym.md").read_text() == "nuevo"
    # Con el hash viejo: conflicto (alguien lo cambió entretanto)
    r2 = client.put("/api/v1/memory/file", json={"path": "Jarvis/Areas/Gym.md", "content": "otro", "base_sha": t["sha"]}, headers=auth)
    assert r2.status_code == 409 and (vault / "Jarvis/Areas/Gym.md").read_text() == "nuevo"
    assert not list((vault / "Jarvis").glob(".cc-*"))  # sin temporales


def test_no_se_editan_generados_ni_sin_csrf(client, auth, vault):
    p = client.get("/api/v1/memory/file", params={"path": "Jarvis/Panel.md"}).json()
    r = client.put("/api/v1/memory/file", json={"path": "Jarvis/Panel.md", "content": "x", "base_sha": p["sha"]}, headers=auth)
    assert r.status_code == 403 and (vault / "Jarvis/Panel.md").read_text().startswith("# Panel")
    t = client.get("/api/v1/memory/file", params={"path": "Jarvis/Tareas.md"}).json()
    assert client.put("/api/v1/memory/file", json={"path": "Jarvis/Tareas.md", "content": "x", "base_sha": t["sha"]}, headers=auth).status_code == 403
    r = client.put("/api/v1/memory/file", json={"path": "Jarvis/Tareas.md", "content": "x", "base_sha": "x"},
                   headers={"Origin": auth["Origin"]})
    assert r.status_code == 403
    audit = client.get("/api/v1/audit").json()
    assert any(a["action"] == "memory.save" and a["outcome"] == "denied" for a in audit)


def test_nota_nueva(client, auth, vault):
    r = client.put("/api/v1/memory/file", json={"path": "Jarvis/Areas/Nueva.md", "content": "hola"}, headers=auth)
    assert r.status_code == 200
    r = client.put("/api/v1/memory/file", json={"path": "Jarvis/Areas/Nueva.md", "content": "pisar"}, headers=auth)
    assert r.status_code == 409


def test_busqueda_resolver_y_backlinks(client, auth, vault):
    hits = client.get("/api/v1/memory/search", params={"q": "sentadilla"}).json()
    assert hits[0]["path"] == "Jarvis/Areas/Gym.md"
    assert client.get("/api/v1/memory/search", params={"q": "secreto"}).json() == []  # fuera de la vault
    assert client.get("/api/v1/memory/resolve", params={"name": "Gym"}).json()["path"] == "Jarvis/Areas/Gym.md"
    assert client.get("/api/v1/memory/resolve", params={"name": "Jarvis/Areas/Gym"}).json()["path"] == "Jarvis/Areas/Gym.md"
    bl = [b["path"] for b in client.get("/api/v1/memory/backlinks", params={"path": "Jarvis/Areas/Gym.md"}).json()]
    assert bl == ["Jarvis/Tareas.md"]
    assert client.get("/api/v1/memory/recent").json()[0]["path"].endswith(".md")


def test_imagenes(client, auth, vault):
    (vault / "Jarvis/x.svg").write_text("<svg><script>alert(1)</script></svg>")
    r = client.get("/api/v1/memory/raw", params={"path": "Jarvis/x.svg"})
    assert r.status_code == 200 and "sandbox" in r.headers["content-security-policy"]
    assert client.get("/api/v1/memory/raw", params={"path": "Jarvis/Tareas.md"}).status_code == 404
