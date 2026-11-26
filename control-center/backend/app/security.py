"""Autenticación propia (aunque el acceso sea solo por Tailscale), CSRF y comprobación de origen.

- Contraseña con Argon2id. Bloqueo temporal tras varios fallos.
- Cookie de sesión opaca (HttpOnly, Secure, SameSite=Strict); en la base solo su SHA-256.
- CSRF: token por sesión que el frontend manda en la cabecera X-CSRF-Token en toda petición con efecto,
  además de comprobar Origin. El WebSocket también comprueba Origin.
"""
import hashlib
import hmac
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, WebSocket
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import get_settings
from .db import session_scope, utcnow
from .models import AuthSession, User

COOKIE = "cc_session"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_ph = PasswordHasher()
# Hash de relleno para que un usuario inexistente tarde lo mismo que una contraseña errónea
_DUMMY = _ph.hash(secrets.token_hex(16))


def hash_password(pw: str) -> str:
    if len(pw) < 12:
        raise ValueError("La contraseña debe tener al menos 12 caracteres")
    return _ph.hash(pw)


USUARIO_INICIAL = ("admin", "admin")


def hash_inicial() -> str:
    """Solo para el usuario de la instalación: admin/admin, que el panel obliga a cambiar al entrar."""
    return _ph.hash(USUARIO_INICIAL[1])


# Lo único que puede hacer quien aún tiene que cambiar la contraseña
RUTAS_SIN_CAMBIO = {"/api/v1/auth/me", "/api/v1/auth/logout", "/api/v1/auth/cuenta"}


def verify_password(h: str, pw: str) -> bool:
    try:
        return _ph.verify(h, pw)
    except (VerifyMismatchError, InvalidHashError):
        return False


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def authenticate(db: Session, username: str, password: str) -> User | None:
    s = get_settings()
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        verify_password(_DUMMY, password)
        return None
    now = utcnow()
    if user.locked_until and user.locked_until > now:
        return None
    if not verify_password(user.password_hash, password):
        user.failed_logins += 1
        if user.failed_logins >= s.login_max_fails:
            user.locked_until = now + timedelta(minutes=s.login_lock_minutes)
            user.failed_logins = 0
        return None
    user.failed_logins, user.locked_until = 0, None
    return user


def create_session(db: Session, user: User, ua: str, ip: str) -> tuple[str, AuthSession]:
    token = secrets.token_urlsafe(32)
    sess = AuthSession(user_id=user.id, token_hash=_sha(token), csrf_token=secrets.token_urlsafe(32),
                       expires_at=utcnow() + timedelta(hours=get_settings().session_hours),
                       user_agent=ua[:255], ip=ip[:64])
    db.add(sess)
    db.flush()
    return token, sess


def lookup_session(db: Session, token: str | None) -> AuthSession | None:
    if not token:
        return None
    sess = db.scalar(select(AuthSession).where(AuthSession.token_hash == _sha(token)))
    if sess is None or sess.expires_at <= utcnow():
        return None
    # last_seen solo cada 5 min: evita una escritura (y un cerrojo de SQLite) en cada petición
    if utcnow() - sess.last_seen > timedelta(minutes=5):
        sess.last_seen = utcnow()
        db.commit()
    return sess


def origin_ok(origin: str | None) -> bool:
    """Origen exacto; `esquema://host:*` para admitir ese host en cualquier puerto; o `esquema://*.dominio` para
    admitir un solo subdominio de ese dominio (p. ej. los túneles temporales `https://*.trycloudflare.com`)."""
    if not origin:
        return False
    origin = origin.rstrip("/")
    for ok in get_settings().allowed_origins:
        if ok == origin:
            return True
        if "://*." in ok:
            esquema, dominio = ok.split("://*.", 1)
            prefijo = esquema + "://"
            if origin.startswith(prefijo) and origin.endswith("." + dominio):
                sub = origin[len(prefijo):-len(dominio) - 1]
                if sub and all(c.isalnum() or c == "-" for c in sub):
                    return True
        if ok.endswith(":*"):
            base = ok[:-2]
            if origin == base or (origin.startswith(base + ":") and origin[len(base) + 1:].isdigit()):
                return True
    return False


def client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


class Principal:
    def __init__(self, user: User, sess: AuthSession):
        self.user, self.session = user, sess

    @property
    def name(self) -> str:
        return self.user.username


VP_HEADER, VP_USER, VP_CSRF = "x-pos-vista-previa", "x-pos-usuario", "x-pos-csrf"


def adoptar_sesion_vista_previa(db: Session, headers, token: str | None) -> AuthSession | None:
    """Solo en una vista previa del Constructor: el panel real ya comprobó la sesión del usuario y la pasa con el token
    de la vista previa. Si la copia de la base no la tiene (se abrió después de copiarla), se crea aquí igual que la real
    (mismo token y mismo CSRF), así el usuario no tiene que volver a entrar ni pierde la sesión del panel real."""
    s = get_settings()
    if not (s.vista_previa and s.vista_previa_token and token):
        return None
    if not hmac.compare_digest(headers.get(VP_HEADER, ""), s.vista_previa_token):
        return None
    user = db.scalar(select(User).where(User.username == headers.get(VP_USER, "")))
    if user is None:
        return None
    sess = AuthSession(user_id=user.id, token_hash=_sha(token), csrf_token=headers.get(VP_CSRF, "") or secrets.token_urlsafe(32),
                       expires_at=utcnow() + timedelta(hours=s.session_hours), user_agent="vista previa", ip="127.0.0.1")
    db.add(sess)
    try:
        db.commit()
    except IntegrityError:  # al abrir la página llegan varias peticiones a la vez: otra ya la ha creado
        db.rollback()
        return lookup_session(db, token)
    return sess


def current_principal(request: Request) -> Principal:
    """Conexión breve: se comprueba la sesión y se suelta antes de que el endpoint haga su trabajo."""
    with session_scope() as db:
        sess = lookup_session(db, request.cookies.get(COOKIE)) or adoptar_sesion_vista_previa(db, request.headers, request.cookies.get(COOKIE))
        if sess is None:
            raise HTTPException(401, "No autenticado")
        if request.method not in SAFE_METHODS:
            if not origin_ok(request.headers.get("origin")):
                raise HTTPException(403, "Origen no permitido")
            sent = request.headers.get(CSRF_HEADER, "")
            if not hmac.compare_digest(sent, sess.csrf_token):
                raise HTTPException(403, "Token CSRF inválido")
        user = db.get(User, sess.user_id)
        if user.must_change_password and request.url.path not in RUTAS_SIN_CAMBIO:
            raise HTTPException(403, "Antes de seguir, cambia el usuario y la contraseña de la instalación")
        return Principal(user, sess)


def require_admin(p: Principal = Depends(current_principal)) -> Principal:
    if p.user.role != "admin":
        raise HTTPException(403, "Hace falta rol admin")
    return p


WS_RECHECK_SECONDS = 30


def actor_name(token: str | None) -> str:
    """Nombre del usuario de una petición, para la auditoría del Host Agent."""
    with session_scope() as db:
        sess = lookup_session(db, token)
        user = db.get(User, sess.user_id) if sess else None
        return user.username if user else "anónimo"


def session_alive(token: str | None) -> bool:
    """Para conexiones largas: la sesión pudo cerrarse o caducar después de abrirlas."""
    with session_scope() as db:
        return lookup_session(db, token) is not None


def websocket_principal(ws: WebSocket, db: Session) -> Principal | None:
    """Para WebSocket: exige Origin permitido y cookie de sesión válida."""
    if not origin_ok(ws.headers.get("origin")):
        return None
    sess = lookup_session(db, ws.cookies.get(COOKIE)) or adoptar_sesion_vista_previa(db, ws.headers, ws.cookies.get(COOKIE))
    if sess is None:
        return None
    return Principal(db.get(User, sess.user_id), sess)
