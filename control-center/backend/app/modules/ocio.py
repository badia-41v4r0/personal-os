"""Ocio: pelis y series que el usuario ve o quiere ver, con carátula e información de TMDB.

TMDB solo se consulta al buscar, al añadir y al pulsar «Actualizar»: la ficha se copia en la base y la carátula se
guarda en data/control-center/ocio/, así el panel nunca carga imágenes de fuera (la CSP lo impide) y lo guardado no
depende de TMDB. Sin token (CC_TMDB_TOKEN) se puede seguir añadiendo a mano. Lo que llega de TMDB son datos, nunca órdenes.
"""
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import events
from ..config import get_settings
from ..core import memory
from ..db import get_db, utcnow
from ..models import MediaItem
from ..security import Principal, current_principal, require_admin

log = logging.getLogger("cc.ocio")
router = APIRouter(prefix="/api/v1/me/ocio", dependencies=[Depends(current_principal)])

API = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p"
TIMEOUT = 10
KINDS = {"pelicula": "movie", "serie": "tv"}
STATUSES = ("pendiente", "viendo", "vista", "abandonada")
SIZES = ("w92", "w342")
IMG_NAME = re.compile(r"^/?([A-Za-z0-9_-]{5,60}\.(?:jpg|png))$")
MAX_IMG = 3_000_000


class TmdbError(RuntimeError):
    pass


def configured() -> bool:
    return bool(get_settings().tmdb_token)


def _tmdb(path: str, **params) -> dict:
    token = get_settings().tmdb_token
    if not token:
        raise TmdbError("Falta el token de TMDB (CC_TMDB_TOKEN): de momento solo se puede añadir a mano")
    q = urllib.parse.urlencode({"language": "es-ES", **params})
    req = urllib.request.Request(f"{API}{path}?{q}", headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310  (host fijo)
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise TmdbError("TMDB no acepta el token" if e.code == 401 else f"TMDB respondió {e.code}") from e
    except (OSError, ValueError) as e:
        raise TmdbError("TMDB no responde") from e


def _year(d: str | None) -> int | None:
    return int(d[:4]) if d and re.match(r"^\d{4}", d) else None


def _clean(text, n: int) -> str:
    return " ".join(str(text or "").split())[:n]


def _img_name(path: str | None) -> str:
    m = IMG_NAME.match(path or "")
    return m.group(1) if m else ""


def search(q: str, tipo: str | None = None) -> list[dict]:
    if tipo and tipo not in KINDS:
        raise ValueError("Tipo no válido")
    path = f"/search/{KINDS[tipo]}" if tipo else "/search/multi"
    out = []
    for r in _tmdb(path, query=q[:200], include_adult="false").get("results", [])[:20]:
        media = r.get("media_type") or KINDS[tipo]
        kind = {"movie": "pelicula", "tv": "serie"}.get(media)
        if not kind:
            continue  # personas
        out.append({"tmdb_id": int(r["id"]), "tipo": kind, "titulo": _clean(r.get("title") or r.get("name"), 300),
                    "titulo_original": _clean(r.get("original_title") or r.get("original_name"), 300),
                    "anio": _year(r.get("release_date") or r.get("first_air_date")), "poster": _img_name(r.get("poster_path")),
                    "sinopsis": _clean(r.get("overview"), 300)})
    return out[:12]


def details(tipo: str, tmdb_id: int) -> dict:
    d = _tmdb(f"/{KINDS[tipo]}/{int(tmdb_id)}", append_to_response="watch/providers")
    prov = ((d.get("watch/providers") or {}).get("results") or {}).get("ES") or {}
    providers = list(dict.fromkeys(_clean(p.get("provider_name"), 60) for p in prov.get("flatrate", []) if p.get("provider_name")))[:8]
    f = {"tmdb_id": int(d["id"]), "kind": tipo, "title": _clean(d.get("title") or d.get("name"), 300),
         "original_title": _clean(d.get("original_title") or d.get("original_name"), 300),
         "year": _year(d.get("release_date") or d.get("first_air_date")), "overview": _clean(d.get("overview"), 4000),
         "genres": json.dumps([_clean(g.get("name"), 40) for g in d.get("genres", [])][:8], ensure_ascii=False),
         "poster": _img_name(d.get("poster_path")), "tmdb_rating": round(float(d["vote_average"]), 1) if d.get("vote_count") else None,
         "providers": json.dumps(providers, ensure_ascii=False), "seasons": None, "episodes": None, "season_episodes": "[]", "show_status": ""}
    if tipo == "pelicula":
        f["runtime"] = d.get("runtime") or None
    else:
        runs = d.get("episode_run_time") or []
        f["runtime"] = runs[0] if runs else None
        temporadas = sorted((s for s in d.get("seasons", []) if (s.get("season_number") or 0) > 0), key=lambda s: s["season_number"])
        f["seasons"] = d.get("number_of_seasons") or len(temporadas) or None
        f["episodes"] = d.get("number_of_episodes") or None
        f["season_episodes"] = json.dumps([int(s.get("episode_count") or 0) for s in temporadas])
        f["show_status"] = {"Returning Series": "En emisión", "Ended": "Finalizada", "Canceled": "Cancelada",
                            "In Production": "En producción", "Planned": "Anunciada"}.get(d.get("status") or "", _clean(d.get("status"), 40))
    return f


def _img_path(size: str, name: str):
    return get_settings().data_dir / "ocio" / size / name


def fetch_image(size: str, name: str):
    """Descarga una vez y la guarda. Devuelve la ruta local o None."""
    if size not in SIZES or not IMG_NAME.match(name) or "/" in name:
        return None
    dest = _img_path(size, name)
    if dest.is_file():
        return dest
    try:
        with urllib.request.urlopen(f"{IMG}/{size}/{name}", timeout=TIMEOUT) as r:  # noqa: S310  (host fijo, nombre validado)
            if r.headers.get_content_type() not in ("image/jpeg", "image/png"):
                return None
            data = r.read(MAX_IMG + 1)
    except OSError as e:
        log.warning("carátula %s no disponible: %s", name, e)
        return None
    if len(data) > MAX_IMG:
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(dest)
    return dest


def view(i: MediaItem) -> dict:
    return {"id": i.id, "tipo": i.kind, "tmdb_id": i.tmdb_id, "titulo": i.title, "titulo_original": i.original_title, "anio": i.year,
            "sinopsis": i.overview, "generos": json.loads(i.genres or "[]"), "duracion": i.runtime, "temporadas": i.seasons,
            "capitulos": i.episodes, "capitulos_por_temporada": json.loads(i.season_episodes or "[]"), "emision": i.show_status,
            "poster": i.poster, "nota_tmdb": i.tmdb_rating, "plataformas": json.loads(i.providers or "[]"), "estado": i.status,
            "valoracion": i.rating, "temporada": i.season, "capitulo": i.episode, "empezada": i.started_on, "terminada": i.finished_on,
            "nota": i.note, "actualizado": i.updated_at.isoformat() if i.updated_at else None}


def _apply_status(i: MediaItem, estado: str) -> None:
    hoy = date.today().isoformat()
    i.status = estado
    if estado in ("viendo", "vista") and not i.started_on:
        i.started_on = hoy
    if estado == "vista" and not i.finished_on:
        i.finished_on = hoy
    if estado == "viendo" and i.kind == "serie" and i.season is None:
        i.season, i.episode = 1, 0


def create(db: Session, *, tipo: str, tmdb_id: int | None = None, titulo: str = "", estado: str = "pendiente",
           valoracion: int | None = None, nota: str = "", actor: str = "") -> MediaItem:
    if tipo not in KINDS:
        raise ValueError("Tipo no válido")
    if estado not in STATUSES:
        raise ValueError("Estado no válido")
    if tmdb_id is not None:
        if db.scalar(select(MediaItem).where(MediaItem.kind == tipo, MediaItem.tmdb_id == int(tmdb_id))):
            raise ValueError("Ya la tienes en la lista")
        f = details(tipo, int(tmdb_id))
    else:
        if not titulo.strip():
            raise ValueError("Falta el título")
        f = {"kind": tipo, "title": _clean(titulo, 300)}
    i = MediaItem(**f, note=nota or "", rating=valoracion, status="pendiente")
    _apply_status(i, estado)
    db.add(i)
    db.flush()
    if i.poster:
        fetch_image("w342", i.poster)
    memory.log_event(db, "ocio", f"{tipo}.{estado}", i.title)
    events.audit(db, actor or "panel", "ocio.create", i.title[:255], tmdb_id=i.tmdb_id)
    return i


EDITABLE = {"estado": "status", "valoracion": "rating", "temporada": "season", "capitulo": "episode", "nota": "note",
            "empezada": "started_on", "terminada": "finished_on"}


def update(db: Session, i: MediaItem, cambios: dict, actor: str = "") -> dict:
    """Devuelve lo que había antes (para deshacer)."""
    antes = {k: getattr(i, col) for k, col in EDITABLE.items() if k in cambios}
    if "estado" in cambios:
        if cambios["estado"] not in STATUSES:
            raise ValueError("Estado no válido")
        antes |= {"empezada": i.started_on, "terminada": i.finished_on, "temporada": i.season, "capitulo": i.episode}
    for k, v in cambios.items():
        if k == "estado":
            continue
        if k == "valoracion" and v is not None and not 1 <= int(v) <= 10:
            raise ValueError("La valoración va de 1 a 10")
        setattr(i, EDITABLE[k], v)
    if "estado" in cambios:
        _apply_status(i, cambios["estado"])
    i.updated_at = utcnow()
    events.audit(db, actor or "panel", "ocio.update", i.title[:255], **{k: str(v)[:80] for k, v in cambios.items()})
    return antes


def refresh(db: Session, i: MediaItem) -> None:
    if i.tmdb_id is None:
        raise ValueError("Añadida a mano: no está enlazada a TMDB")
    for k, v in details(i.kind, i.tmdb_id).items():
        setattr(i, k, v)
    i.updated_at = utcnow()
    if i.poster:
        fetch_image("w342", i.poster)


def best_match(titulo: str, tipo: str | None, anio: int | None) -> dict | None:
    res = search(titulo, tipo)
    if anio:
        res = [r for r in res if r["anio"] == anio] or res
    norm = lambda s: re.sub(r"\W+", "", (s or "").lower())  # noqa: E731
    exact = [r for r in res if norm(titulo) in (norm(r["titulo"]), norm(r["titulo_original"]))]
    return (exact or res or [None])[0]


def listing(db: Session, estado: str | None = None) -> list[dict]:
    q = select(MediaItem).order_by(MediaItem.updated_at.desc(), MediaItem.id.desc())
    if estado:
        q = q.where(MediaItem.status == estado)
    return [view(i) for i in db.scalars(q)]


# ---------- API ----------


class AddIn(BaseModel):
    tipo: str = Field(pattern="^(pelicula|serie)$")
    tmdb_id: int | None = Field(default=None, ge=1)
    titulo: str = Field(default="", max_length=300)
    estado: str = Field(default="pendiente", pattern="^(pendiente|viendo|vista|abandonada)$")
    valoracion: int | None = Field(default=None, ge=1, le=10)
    nota: str = Field(default="", max_length=4000)


class PatchIn(BaseModel):
    estado: str | None = Field(default=None, pattern="^(pendiente|viendo|vista|abandonada)$")
    valoracion: int | None = Field(default=None, ge=1, le=10)
    temporada: int | None = Field(default=None, ge=0, le=200)
    capitulo: int | None = Field(default=None, ge=0, le=5000)
    nota: str | None = Field(default=None, max_length=4000)
    empezada: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    terminada: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


def _get(db: Session, iid: int) -> MediaItem:
    i = db.get(MediaItem, iid)
    if i is None:
        raise HTTPException(404, "No encontrado")
    return i


@router.get("")
def items(db: Session = Depends(get_db)):
    return {"tmdb": configured(), "items": listing(db)}


@router.get("/buscar")
def buscar(q: str, tipo: str | None = None):
    if not q.strip():
        return []
    try:
        return search(q.strip(), tipo or None)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except TmdbError as e:
        raise HTTPException(503, str(e)) from e


@router.post("")
def add(body: AddIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        return view(create(db, actor=p.name, **body.model_dump()))
    except ValueError as e:
        raise HTTPException(409 if "Ya la tienes" in str(e) else 422, str(e)) from e
    except TmdbError as e:
        raise HTTPException(503, str(e)) from e


@router.patch("/{iid}")
def patch(iid: int, body: PatchIn, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    i = _get(db, iid)
    try:
        update(db, i, body.model_dump(exclude_unset=True), p.name)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return view(i)


@router.post("/{iid}/actualizar")
def actualizar(iid: int, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    i = _get(db, iid)
    try:
        refresh(db, i)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except TmdbError as e:
        raise HTTPException(503, str(e)) from e
    return view(i)


@router.delete("/{iid}")
def delete(iid: int, p: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    i = _get(db, iid)
    events.audit(db, p.name, "ocio.delete", i.title[:255])
    db.delete(i)
    return {"ok": True}


@router.get("/imagen/{size}/{name}")
def imagen(size: str, name: str):
    path = fetch_image(size, name)
    if path is None:
        raise HTTPException(404, "Sin imagen")
    media = "image/png" if name.endswith(".png") else "image/jpeg"
    return FileResponse(path, media_type=media, headers={"Cache-Control": "private, max-age=2592000, immutable"})
