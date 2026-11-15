import pytest

from app import projects
from app.adapters import hostagent

H = "a" * 64
PROP = {"nombre": "resumidor", "huella": H, "valida": True, "tipo": "agente", "descripcion": "Resume", "modelo": "sonnet",
        "herramientas": ["Read", "Bash"], "sustituye": False, "destino": "agent/.claude/agents/resumidor.md",
        "archivos": {"AGENTE.md": "---\nname: resumidor\n---\nResume"}}


@pytest.fixture()
def ha(monkeypatch):
    state = {"pend": [dict(PROP)], "calls": []}

    async def call(path, params=None, method="GET", json=None, timeout=15):
        state["calls"].append((method, path, json))
        if path == "/v1/proposals":
            return state["pend"]
        if path.endswith("/approve"):
            if json["hash"] != H:
                raise hostagent.HostAgentError(409, "❌ La propuesta ha cambiado desde que la revisaste: no se ha instalado nada.")
            state["pend"] = []
            return {"ok": True, "output": "✅ Instalado"}
        if path.endswith("/reject"):
            state["pend"] = []
            return {"ok": True}
        raise AssertionError(path)

    monkeypatch.setattr(hostagent, "call", call)
    return state


def test_pendientes_con_impacto(client, auth, ha):
    r = client.get("/api/v1/approvals").json()
    p = r["pendientes"][0]
    assert p["solicitado_por"] == "Jarvis" and "Bash" in p["impacto"] and "agent/.claude/agents/resumidor.md" in p["impacto"]


def test_aprobar_con_la_huella_vista(client, auth, ha):
    r = client.post("/api/v1/approvals/proposals/resumidor/approve", json={"hash": "b" * 64}, headers=auth)
    assert r.status_code == 409 and "ha cambiado" in r.json()["detail"]
    r = client.post("/api/v1/approvals/proposals/resumidor/approve", json={"hash": H}, headers=auth)
    assert r.status_code == 200
    hist = client.get("/api/v1/approvals").json()["historial"]
    assert [h["status"] for h in hist] == ["done", "error"] and hist[0]["decided_by"] == "ana"
    assert any(a["action"] == "approval.approve" for a in client.get("/api/v1/audit").json())


def test_rechazar_y_validaciones(client, auth, ha):
    assert client.post("/api/v1/approvals/proposals/resumidor/approve", json={"hash": "x"}, headers=auth).status_code == 422
    assert client.post("/api/v1/approvals/proposals/resumidor/reject", json={"motivo": "no"}, headers=auth).status_code == 200
    assert client.get("/api/v1/approvals").json()["historial"][0]["status"] == "rejected"
    assert client.post("/api/v1/approvals/proposals/otra/approve", json={"hash": H}, headers=auth).status_code == 404


def test_aprobar_requiere_csrf(client, auth, ha):
    assert client.post("/api/v1/approvals/proposals/resumidor/approve", json={"hash": H}, headers={"Origin": auth["Origin"]}).status_code == 403


def test_colas_y_solicitudes(client, auth, settings):
    j = settings.vault / "Jarvis"
    for d in ("Encargos/cola", "Encargos/hechos", "Ayudante/hechos/t1", "Propuestas"):
        (j / d).mkdir(parents=True, exist_ok=True)
    (j / "Encargos/cola/20261031-1-x.md").write_text("---\nrepo: MiRepo\ntipo: plan\ntitulo: Planificar\n---\nHaz un plan")
    (j / "Encargos/hechos/20261001-1-y.md").write_text("---\nrepo: MiRepo\ntitulo: Hecho\n---\nX\n\n## Resultado\n- Commits: 2")
    (j / "Ayudante/hechos/t1/tarea.md").write_text("---\ntitulo: Buscar ofertas\n---\nBusca")
    (j / "Ayudante/hechos/t1/resultado.md").write_text("3 ofertas")
    (j / "Propuestas/solicitudes.md").write_text("# S\n- ✅ (hecho el 12/10) 2026-10-11 · Ayudante\n- 2026-10-18 · Leer Canvas\n")
    q = {x["id"]: x for x in client.get("/api/v1/queues").json()}
    assert q["encargos"]["pendientes"] == 1 and q["encargos"]["items"][0]["titulo"] == "Planificar"
    assert q["encargos"]["items"][1]["resultado"].startswith("- Commits: 2")
    assert q["ayudante"]["items"][0]["resultado"] == "3 ofertas"
    r = client.get("/api/v1/requests").json()
    assert [x["texto"] for x in r["pendientes"]] == ["Leer Canvas"] and r["hechas"][0]["resuelta"] == "hecho el 12/10"


def test_proyectos(client, auth, monkeypatch):
    monkeypatch.setattr(projects, "repos_config", lambda: {"Demo": {"modelo": "sonnet", "minutos": 45, "area": "empresa"}})
    monkeypatch.setattr(projects, "local", lambda r: {"clonada": True, "principal": "main", "staging": False})
    monkeypatch.setattr(projects, "github", lambda r, refresh=False: {"prs": [], "issues": [{"titulo": "Bug", "url": "u", "numero": 1, "etiquetas": []}], "pr_staging": None, "error": None})
    monkeypatch.setattr(projects, "log", lambda r, ref, n: [{"hash": "abc", "author": "a", "date": "d", "subject": "s"}])
    r = client.get("/api/v1/projects").json()
    assert r[0]["nombre"] == "Demo" and r[0]["github"]["issues"][0]["titulo"] == "Bug"
    assert client.get("/api/v1/projects/Demo").json()["commits"]["main"][0]["hash"] == "abc"
    assert client.get("/api/v1/projects/..%2Fetc").status_code == 404
    assert client.get("/api/v1/projects/NoExiste").status_code == 404
