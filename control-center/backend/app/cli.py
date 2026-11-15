"""Administración local (en el PC): crear usuario o cambiar su contraseña.

  uv run python -m app.cli set-password <usuario>          (pregunta la contraseña)
  uv run python -m app.cli set-password <usuario> --random   (genera una y la guarda en secrets/, permisos 600)
"""
import getpass
import os
import secrets
import sys

from sqlalchemy import select

from .config import ROOT
from .db import session_scope
from .events import audit
from .models import AuthSession, User
from .security import hash_password


def set_password(username: str, random_pw: bool = False) -> None:
    if random_pw:
        pw = "-".join(secrets.token_urlsafe(6) for _ in range(4))
        out = ROOT / "secrets/control-center-password.txt"
        old = os.umask(0o077)
        try:
            out.write_text(f"{username}\n{pw}\n")
        finally:
            os.umask(old)
        out.chmod(0o600)
        print(f"Contraseña guardada en {out} (solo tú puedes leerla).")
    else:
        pw = getpass.getpass("Contraseña nueva (mín. 12): ")
        if pw != getpass.getpass("Repite: "):
            sys.exit("No coinciden")
    h = hash_password(pw)
    with session_scope() as db:
        u = db.scalar(select(User).where(User.username == username))
        if u is None:
            db.add(User(username=username, password_hash=h, role="admin"))
            audit(db, "cli", "user.create", target=username)
        else:
            u.password_hash, u.failed_logins, u.locked_until = h, 0, None
            # Cerrar todas sus sesiones abiertas
            for s in db.scalars(select(AuthSession).where(AuthSession.user_id == u.id)):
                db.delete(s)
            audit(db, "cli", "user.password", target=username)
    print("Hecho.")


if __name__ == "__main__":
    if len(sys.argv) in (3, 4) and sys.argv[1] == "set-password":
        set_password(sys.argv[2], random_pw=sys.argv[3:] == ["--random"])
    else:
        sys.exit(__doc__)
