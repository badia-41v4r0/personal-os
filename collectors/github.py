"""GitHub: actividad de las últimas 24 h y PRs/issues abiertos (usa el `gh` autenticado del PC)."""
import json
import subprocess
from datetime import datetime, timedelta, timezone

import ajustes


def owner() -> str:
    """Cuenta u organización de GitHub de la instancia (config github.json)."""
    return str(ajustes.leer("github").get("owner") or "")


def repos() -> dict[str, dict]:
    """repo -> configuración (área, modelo y minutos del programador). bin/crear-repo.sh añade ahí las nuevas."""
    r = ajustes.leer("github").get("repos") or {}
    return r if isinstance(r, dict) else {}


def _gh(path: str):
    r = subprocess.run(["gh", "api", "-X", "GET", path], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:200])
    return json.loads(r.stdout)


def recoger(horas: int = 24) -> list[dict]:
    desde = (datetime.now(timezone.utc) - timedelta(hours=horas)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    OWNER = owner()
    if not OWNER:
        return out
    for repo, conf in repos().items():
        item = {"repo": repo, "area": conf.get("area", "personal")}
        try:
            commits = _gh(f"repos/{OWNER}/{repo}/commits?since={desde}&per_page=20")
            item["commits"] = [c["commit"]["message"].splitlines()[0][:80] for c in commits]
            issues = _gh(f"repos/{OWNER}/{repo}/issues?state=open&per_page=50")
            item["prs"] = [i["title"][:80] for i in issues if "pull_request" in i]
            item["issues"] = [i["title"][:80] for i in issues if "pull_request" not in i]
            st = _gh(f"repos/{OWNER}/{repo}/pulls?state=open&head={OWNER}:staging")
            item["pr_staging"] = st[0]["html_url"] if st else None
        except Exception as e:  # sin red o repo inaccesible: se indica y se sigue
            item["error"] = str(e)
        out.append(item)
    return out


if __name__ == "__main__":
    print(json.dumps(recoger(), ensure_ascii=False, indent=1))
