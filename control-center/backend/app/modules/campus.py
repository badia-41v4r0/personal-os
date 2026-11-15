"""Campus virtual del usuario (config estudios.json → plataforma): a qué webs puede salir el ordenador del tutor.

plataforma = {"nombre": "Moodle de mi uni", "url": "https://campus.ejemplo.edu/", "tipo": "canvas|moodle|blackboard|otra",
              "centro": "Universidad de Ejemplo", "dominios": ["ejemplo.edu", …]}
Los dominios los propone el agente de onboarding al ver adónde redirige el inicio de sesión (SSO, CDN) y el usuario
los aprueba; aquí se añade el de la propia URL y, en Canvas, sus CDN conocidos.
"""
import re
import sys
from urllib.parse import urlparse

from ..config import ROOT

sys.path.insert(0, str(ROOT / "collectors"))
import ajustes  # noqa: E402

CDN = {"canvas": ("instructure.com", "canvas-user-content.com", "instructure-uploads.s3.amazonaws.com", "inscloudgate.net",
                  "du11hjcvx0uqb.cloudfront.net"),
       "moodle": (), "blackboard": ("blackboard.com", "bbcollab.com"), "otra": ()}
DOMINIO_RE = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def plataforma() -> dict:
    p = ajustes.leer("estudios").get("plataforma") or {}
    return p if isinstance(p, dict) else {}


def url() -> str:
    u = str(plataforma().get("url") or "").strip()
    return u if u.startswith("https://") else ""


def dominios() -> list[str]:
    p = plataforma()
    out = {str(d).lower().strip(".") for d in p.get("dominios") or []}
    host = (urlparse(url()).hostname or "").lower()
    if host:
        out.add(host)
        partes = host.split(".")
        if len(partes) > 2:
            out.add(".".join(partes[-2:]))  # campus.uni.edu → uni.edu (el SSO suele estar en otro subdominio)
    out.update(CDN.get(str(p.get("tipo") or "otra"), ()))
    return sorted(d for d in out if DOMINIO_RE.match(d))[:40]
