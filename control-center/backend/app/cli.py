"""Administración local (en el PC): crear usuario o cambiar su contraseña.

  uv run python -m app.cli set-password <usuario>          (pregunta la contraseña)
  uv run python -m app.cli set-password <usuario> --random   (genera una y la guarda en secrets/, permisos 600)
  uv run python -m app.cli crear-admin                     (admin/admin si no hay usuarios; obliga a cambiarlo al entrar)
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


def crear_admin_inicial() -> None:
    """Usuario de la instalación: admin/admin, que el panel obliga a cambiar en el primer inicio de sesión.
    Solo si aún no hay ningún usuario: nunca toca uno existente."""
    from .security import USUARIO_INICIAL, hash_inicial
    with session_scope() as db:
        if db.scalar(select(User).limit(1)):
            print("Ya hay usuarios: no se crea el inicial.")
            return
        db.add(User(username=USUARIO_INICIAL[0], password_hash=hash_inicial(), role="admin", must_change_password=True))
        audit(db, "cli", "user.create", target=USUARIO_INICIAL[0], inicial=True)
    print("Usuario inicial: admin / admin (el panel pedirá cambiarlo al entrar).")


if __name__ == "__main__":
    if len(sys.argv) in (3, 4) and sys.argv[1] == "set-password":
        set_password(sys.argv[2], random_pw=sys.argv[3:] == ["--random"])
    elif sys.argv[1:] == ["crear-admin"]:
        crear_admin_inicial()
    else:
        sys.exit(__doc__)
