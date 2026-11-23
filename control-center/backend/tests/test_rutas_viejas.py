"""Las direcciones antiguas del panel (marcadores, avisos ya enviados) llevan a las nuevas."""
import pytest

from app.rutas_viejas import nueva


@pytest.mark.parametrize("viejo, query, esperado", [
    ("/tasks/", "t=approvals", "/bandeja/"),
    ("/tasks/", "t=requests", "/bandeja/?t=solicitudes"),
    ("/tasks/", "t=queues", "/ajustes/colas/"),
    ("/tasks/", "t=tasks", "/tareas/"),
    ("/tasks/", "", "/tareas/"),
    ("/gym/", "tab=history&w=abc", "/entrenamiento/?tab=history&w=abc"),
    ("/gym", "", "/entrenamiento/"),
    ("/memory/hechos/", "", "/conocimiento/sobre-ti/"),
    ("/memory/", "p=Jarvis%2FTareas.md", "/conocimiento/?p=Jarvis%2FTareas.md"),
    ("/settings/modulos/", "", "/ajustes/modulos/"),
    ("/settings/", "", "/ajustes/"),
    ("/virtual-computers/", "v=123", "/ajustes/ordenadores/?v=123"),
    ("/avisos/", "", "/bandeja/"),
    ("/chat/", "s=xyz", "/conversaciones/?s=xyz"),
])
def test_mapa(viejo, query, esperado):
    assert nueva(viejo, query) == esperado


@pytest.mark.parametrize("ruta", ["/", "/entrenamiento/", "/ajustes/sistema/", "/bandeja/", "/agenda/", "/gymnasio/"])
def test_las_nuevas_no_se_tocan(ruta):
    assert nueva(ruta) is None


def test_el_servidor_redirige(client):
    r = client.get("/tasks/?t=approvals", follow_redirects=False)
    assert r.status_code == 308 and r.headers["location"] == "/bandeja/"
    assert client.get("/api/v1/tasks", follow_redirects=False).status_code != 308  # la API no se redirige
