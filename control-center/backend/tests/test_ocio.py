import dataclasses
from datetime import date

import pytest

from app import config
from app import db as dbm
from app.core import actions
from app.models import MediaItem
from app.modules import ocio

SEARCH = {"results": [
    {"id": 1396, "media_type": "tv", "name": "Breaking Bad", "original_name": "Breaking Bad", "first_air_date": "2008-01-20",
     "poster_path": "/ggFHVNu6YYI5L9pCfOacjizRGt.jpg", "overview": "Un profesor de química…"},
    {"id": 99, "media_type": "person", "name": "Alguien"},
    {"id": 559969, "media_type": "movie", "title": "El Camino: Una película de Breaking Bad", "original_title": "El Camino",
     "release_date": "2019-10-11", "poster_path": None, "overview": ""},
]}
TV = {"id": 1396, "name": "Breaking Bad", "original_name": "Breaking Bad", "first_air_date": "2008-01-20", "overview": "Sinopsis",
      "genres": [{"name": "Drama"}, {"name": "Crimen"}], "poster_path": "/ggFHVNu6YYI5L9pCfOacjizRGt.jpg", "vote_average": 8.912, "vote_count": 15000,
      "episode_run_time": [47], "number_of_seasons": 5, "number_of_episodes": 62, "status": "Ended",
      "seasons": [{"season_number": 0, "episode_count": 9}, {"season_number": 1, "episode_count": 7}, {"season_number": 2, "episode_count": 13}],
      "watch/providers": {"results": {"ES": {"flatrate": [{"provider_name": "Netflix"}]}, "US": {"flatrate": [{"provider_name": "AMC+"}]}}}}
MOVIE = {"id": 27205, "title": "Origen", "original_title": "Inception", "release_date": "2010-07-15", "overview": "Sueños",
         "genres": [{"name": "Acción"}], "poster_path": "/abcdefghijk.jpg", "vote_average": 8.4, "vote_count": 10, "runtime": 148}


@pytest.fixture()
def tmdb(settings, monkeypatch):
    config.set_settings(dataclasses.replace(settings, tmdb_token="t" * 40))
    calls = []

    def fake(path, **params):
        calls.append((path, params))
        if path.startswith("/search"):
            return SEARCH
        return {"/tv/1396": TV, "/movie/27205": MOVIE}[path]
    monkeypatch.setattr(ocio, "_tmdb", fake)
    imgs = []
    monkeypatch.setattr(ocio, "fetch_image", lambda size, name: imgs.append((size, name)))
    return calls, imgs


def test_buscar_quita_personas(client, auth, tmdb):
    r = client.get("/api/v1/me/ocio/buscar", params={"q": "breaking"}).json()
    assert [(x["tipo"], x["tmdb_id"], x["anio"]) for x in r] == [("serie", 1396, 2008), ("pelicula", 559969, 2019)]
    assert r[0]["poster"] == "ggFHVNu6YYI5L9pCfOacjizRGt.jpg" and r[1]["poster"] == ""


def test_anadir_serie_copia_la_ficha(client, auth, tmdb):
    _, imgs = tmdb
    r = client.post("/api/v1/me/ocio", json={"tipo": "serie", "tmdb_id": 1396}, headers=auth).json()
    assert r["titulo"] == "Breaking Bad" and r["anio"] == 2008 and r["generos"] == ["Drama", "Crimen"]
    assert r["temporadas"] == 5 and r["capitulos_por_temporada"] == [7, 13] and r["emision"] == "Finalizada"
    assert r["plataformas"] == ["Netflix"] and r["nota_tmdb"] == 8.9 and r["duracion"] == 47 and r["estado"] == "pendiente"
    assert imgs == [("w342", "ggFHVNu6YYI5L9pCfOacjizRGt.jpg")]
    assert client.post("/api/v1/me/ocio", json={"tipo": "serie", "tmdb_id": 1396}, headers=auth).status_code == 409
    assert client.get("/api/v1/me/ocio").json()["tmdb"] is True


def test_estados_ponen_fechas_y_progreso(client, auth, tmdb):
    i = client.post("/api/v1/me/ocio", json={"tipo": "serie", "tmdb_id": 1396}, headers=auth).json()["id"]
    r = client.patch(f"/api/v1/me/ocio/{i}", json={"estado": "viendo"}, headers=auth).json()
    hoy = date.today().isoformat()
    assert r["empezada"] == hoy and (r["temporada"], r["capitulo"]) == (1, 0) and r["terminada"] is None
    r = client.patch(f"/api/v1/me/ocio/{i}", json={"temporada": 2, "capitulo": 3}, headers=auth).json()
    assert (r["temporada"], r["capitulo"]) == (2, 3)
    r = client.patch(f"/api/v1/me/ocio/{i}", json={"estado": "vista", "valoracion": 9}, headers=auth).json()
    assert r["terminada"] == hoy and r["valoracion"] == 9
    assert client.patch(f"/api/v1/me/ocio/{i}", json={"valoracion": 11}, headers=auth).status_code == 422
    assert client.patch(f"/api/v1/me/ocio/{i}", json={"estado": "raro"}, headers=auth).status_code == 422


def test_sin_token_se_anade_a_mano(client, auth):
    assert client.get("/api/v1/me/ocio").json() == {"tmdb": False, "items": []}
    assert client.get("/api/v1/me/ocio/buscar", params={"q": "x"}).status_code == 503
    r = client.post("/api/v1/me/ocio", json={"tipo": "pelicula", "titulo": "Una rara", "estado": "vista"}, headers=auth).json()
    assert r["titulo"] == "Una rara" and r["tmdb_id"] is None and r["terminada"] == date.today().isoformat()
    assert client.post(f"/api/v1/me/ocio/{r['id']}/actualizar", headers=auth).status_code == 422
    assert client.post("/api/v1/me/ocio", json={"tipo": "pelicula"}, headers=auth).status_code == 422
    client.delete(f"/api/v1/me/ocio/{r['id']}", headers=auth)
    assert client.get("/api/v1/me/ocio").json()["items"] == []


def test_actualizar_respeta_lo_tuyo(client, auth, tmdb):
    i = client.post("/api/v1/me/ocio", json={"tipo": "pelicula", "tmdb_id": 27205, "estado": "vista", "valoracion": 8, "nota": "Brutal"}, headers=auth).json()["id"]
    MOVIE["runtime"] = 150
    try:
        r = client.post(f"/api/v1/me/ocio/{i}/actualizar", headers=auth).json()
    finally:
        MOVIE["runtime"] = 148
    assert r["duracion"] == 150 and (r["valoracion"], r["nota"], r["estado"]) == (8, "Brutal", "vista")


def test_imagen_valida_el_nombre(client, auth, settings):
    for mal in ("..%2F..%2Fsecrets.env", "x.gif", "abc.jpg"):
        assert client.get(f"/api/v1/me/ocio/imagen/w342/{mal}").status_code == 404
    assert client.get("/api/v1/me/ocio/imagen/original/abcdefghijk.jpg").status_code == 404
    f = settings.data_dir / "ocio" / "w342" / "abcdefghijk.jpg"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"\xff\xd8jpeg")
    r = client.get("/api/v1/me/ocio/imagen/w342/abcdefghijk.jpg")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and "max-age" in r.headers["cache-control"]


def test_jarvis_anade_por_titulo_y_deshace(client, tmdb):
    r = actions.request("ocio.add", {"titulo": "Breaking Bad", "estado": "viendo"}, actor="jarvis", reason="prueba")
    assert r["status"] == "done"
    with dbm.session_scope() as s:
        m = s.query(MediaItem).one()
        assert (m.tmdb_id, m.kind, m.status, m.season) == (1396, "serie", "viendo", 1)
    actions.undo(r["id"], "usuario")
    with dbm.session_scope() as s:
        assert s.query(MediaItem).count() == 0


def test_jarvis_elige_por_anio(tmdb):
    assert ocio.best_match("El Camino", None, 2019)["tmdb_id"] == 559969
    assert ocio.best_match("Breaking Bad", "serie", None)["tmdb_id"] == 1396


def test_jarvis_actualiza_y_deshace(client, auth, tmdb):
    i = client.post("/api/v1/me/ocio", json={"tipo": "serie", "tmdb_id": 1396, "estado": "viendo"}, headers=auth).json()["id"]
    r = actions.request("ocio.update", {"titulo": "breaking bad", "capitulo": 5, "valoracion": 9}, actor="jarvis", reason="prueba")
    assert r["status"] == "done"
    with dbm.session_scope() as s:
        assert (s.get(MediaItem, i).episode, s.get(MediaItem, i).rating) == (5, 9)
    actions.undo(r["id"], "usuario")
    with dbm.session_scope() as s:
        assert (s.get(MediaItem, i).episode, s.get(MediaItem, i).rating) == (0, None)


def test_sin_tmdb_jarvis_necesita_el_tipo(client):
    r = actions.request("ocio.add", {"titulo": "Algo"}, actor="jarvis", reason="prueba")
    assert r["status"] == "failed"
    r = actions.request("ocio.add", {"titulo": "Algo", "tipo": "pelicula"}, actor="jarvis", reason="prueba")
    assert r["status"] == "done"
