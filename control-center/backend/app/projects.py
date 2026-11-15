"""Projects: capa visual sobre lo que ya existe.

- Lista de repos y su configuración: data/config/github.json (la misma que usan el programador y bin/crear-repo.sh).
- Estado local: git de solo lectura en repos/<nombre> (rama, últimos commits, cuánto lleva staging por delante).
  Ojo: repos/ es el espacio de trabajo del programador (cada encargo hace reset --hard), no se toca.
- GitHub: las mismas llamadas de collectors/github.py (`gh` del PC), con caché de 10 minutos.
- Ejecuciones del programador: los encargos de Jarvis/Encargos (cola, en curso y hechos).
"""
import json
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException

from .config import ROOT, get_settings
from .security import current_principal

sys.path.insert(0, str(ROOT / "collectors"))
router = APIRouter(prefix="/api/v1/projects", dependencies=[Depends(current_principal)])
TTL = 600
_gh_cache: dict[str, tuple[float, dict]] = {}
_gh_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


def repos_config() -> dict:
    import github as gh
    return gh.repos()


def gh_owner() -> str:
    import github as gh
    return gh.owner()


def git(repo: str, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(ROOT / "repos" / repo), *args], capture_output=True, text=True, timeout=15)
    return r.stdout.strip() if r.returncode == 0 else ""


def main_branch(repo: str) -> str:
    for b in ("main", "master"):
        if git(repo, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{b}") or git(repo, "rev-parse", "--verify", "--quiet", b):
            return b
    return "main"


def log(repo: str, ref: str, n: int) -> list[dict]:
    out = git(repo, "log", ref, f"-n{n}", "--pretty=format:%h%x09%an%x09%aI%x09%s")
    res = []
    for line in out.splitlines():
        h, a, d, s = (line.split("\t", 3) + ["", "", "", ""])[:4]
        res.append({"hash": h, "author": a, "date": d, "subject": s[:120]})
    return res


def local(repo: str) -> dict:
    if not (ROOT / "repos" / repo / ".git").exists():
        return {"clonada": False}
    main = main_branch(repo)
    ref_main = f"origin/{main}" if git(repo, "rev-parse", "--verify", "--quiet", f"origin/{main}") else main
    has_staging = bool(git(repo, "rev-parse", "--verify", "--quiet", "staging"))
    ahead = behind = None
    if has_staging:
        counts = git(repo, "rev-list", "--left-right", "--count", f"{ref_main}...staging").split()
        if len(counts) == 2:
            behind, ahead = int(counts[0]), int(counts[1])
    last = log(repo, "staging" if has_staging else ref_main, 1)
    return {"clonada": True, "rama_actual": git(repo, "branch", "--show-current"), "principal": main,
            "staging": has_staging, "staging_por_delante": ahead, "staging_por_detras": behind,
            "ultimo_commit": last[0] if last else None}


def github(repo: str, refresh: bool = False) -> dict:
    hit = _gh_cache.get(repo)
    if hit and not refresh and time.time() - hit[0] < TTL:
        return hit[1]
    with _locks_guard:
        lock = _gh_locks.setdefault(repo, threading.Lock())
    with lock:  # una sola consulta a GitHub por repo aunque lleguen varias peticiones a la vez
        hit = _gh_cache.get(repo)
        if hit and time.time() - hit[0] < (1 if refresh else TTL):
            return hit[1]
        return _github_fetch(repo)


def _github_fetch(repo: str) -> dict:
    import github as gh
    try:
        owner = gh.owner()
        if not owner:
            raise RuntimeError("Falta la cuenta de GitHub (Ajustes → GitHub)")
        issues = gh._gh(f"repos/{owner}/{repo}/issues?state=open&per_page=50")
        st = gh._gh(f"repos/{owner}/{repo}/pulls?state=open&head={owner}:staging")
        data = {"prs": [{"titulo": i["title"][:120], "url": i["html_url"], "numero": i["number"]} for i in issues if "pull_request" in i],
                "issues": [{"titulo": i["title"][:120], "url": i["html_url"], "numero": i["number"],
                            "etiquetas": [lbl["name"] for lbl in i.get("labels", [])]} for i in issues if "pull_request" not in i],
                "pr_staging": st[0]["html_url"] if st else None, "error": None}
    except Exception as e:  # noqa: BLE001  (sin red, sin gh o repo inaccesible)
        data = {"prs": [], "issues": [], "pr_staging": None, "error": str(e)[:200]}
    _gh_cache[repo] = (time.time(), data)
    return data


def encargos(repo: str | None = None) -> list[dict]:
    from .approvals import _item
    root = get_settings().vault / "Jarvis/Encargos"
    out = []
    for st in ("cola", "en-curso", "hechos"):
        d = root / st
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.md"), reverse=True):
            it = _item(root, f, st)
            if repo is None or it["meta"].get("repo") == repo:
                out.append(it)
    return out


@router.get("")
def projects(refresh: bool = False):
    cfg = repos_config()
    enc = encargos()
    with ThreadPoolExecutor(max_workers=5) as ex:
        ghs = dict(zip(cfg, ex.map(lambda n: github(n, refresh), cfg)))
    out = []
    for name, c in cfg.items():
        gh = ghs[name]
        out.append({"nombre": name, "area": c.get("area"), "modelo": c.get("modelo"), "minutos": c.get("minutos"),
                    "subagentes": c.get("subagentes"), "local": local(name), "github": gh,
                    "encargos": sum(1 for e in enc if e["meta"].get("repo") == name),
                    "encargos_pendientes": sum(1 for e in enc if e["meta"].get("repo") == name and e["estado"] != "hechos")})
    return out


@router.get("/{name}")
def project(name: str):
    cfg = repos_config()
    if not NAME_RE.match(name) or name not in cfg:
        raise HTTPException(404, "Repo no encontrada")
    loc = local(name)
    commits = {}
    if loc.get("clonada"):
        main = loc["principal"]
        ref_main = f"origin/{main}" if git(name, "rev-parse", "--verify", "--quiet", f"origin/{main}") else main
        commits[main] = log(name, ref_main, 15)
        if loc["staging"]:
            commits["staging"] = log(name, "staging", 15)
    return {"nombre": name, "config": cfg[name], "owner": gh_owner(), "local": loc, "commits": commits, "github": github(name),
            "encargos": encargos(name)}
