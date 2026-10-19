from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from starlette.requests import Request

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from backend.models import User

AUTH_ENABLED = os.environ.get("AUTH_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")

SESSION_COOKIE_NAME = "finance_session"
SESSION_MAX_AGE = 30 * 24 * 60 * 60  # 30 jours

# Secret de signature des cookies de session : un seul secret partagé par
# TOUTES les sessions de TOUS les utilisateurs (contrairement à l'ancienne
# authentification à mot de passe unique, où il était dérivé du mot de
# passe lui-même — impossible désormais, chaque utilisateur a le sien).
# Amorcé ici avec une valeur aléatoire de secours (utile seulement si
# AUTH_ENABLED mais que load_session_secret() n'a pas encore tourné, ex. un
# import de ce module hors du cycle de vie normal de l'application, comme
# dans les tests) ; load_session_secret() (appelée une fois au démarrage,
# voir main.py) lui substitue la valeur persistée en base (app_state.
# session_secret), générée aléatoirement au tout premier démarrage.
SESSION_SECRET = secrets.token_hex(32)
_serializer = URLSafeTimedSerializer(SESSION_SECRET, salt="finance-dashboard-auth")


def _apply_session_secret(session_secret: str) -> None:
    global SESSION_SECRET, _serializer
    SESSION_SECRET = session_secret
    _serializer = URLSafeTimedSerializer(SESSION_SECRET, salt="finance-dashboard-auth")


def load_session_secret(db: "Session") -> None:
    # Appelée une fois au démarrage de l'application (voir main.py). Import
    # différé de crud pour éviter tout cycle d'import au chargement du
    # module.
    if not AUTH_ENABLED:
        return
    from backend import crud

    state = crud.get_or_create_app_state(db)
    if state.session_secret:
        _apply_session_secret(state.session_secret)
    else:
        # Premier démarrage : génère et persiste, pour que TOUS les workers/
        # redémarrages ultérieurs signent avec le même secret (sinon les
        # sessions ouvertes ailleurs deviendraient invalides à chaque
        # redémarrage).
        new_secret = secrets.token_hex(32)
        crud.set_session_secret(db, new_secret)
        _apply_session_secret(new_secret)


def _password_fingerprint(hashed_password: str) -> str:
    # Empreinte courte du hash bcrypt courant de l'utilisateur, embarquée
    # dans le jeton de session à la connexion et revérifiée à chaque requête
    # (voir authenticate_request) : change dès que le mot de passe change
    # (reset admin ou changement volontaire), ce qui invalide automatiquement
    # les sessions signées avec l'ancien mot de passe — sans avoir besoin
    # d'une colonne "session_version" séparée, hors du schéma users demandé.
    return hashlib.sha256(hashed_password.encode("utf-8")).hexdigest()[:16]


def verify_password(db: "Session", username: str, password: str) -> "User | None":
    import bcrypt

    from backend import crud

    user = crud.get_user_by_username(db, username)
    if user is None or not user.is_active:
        return None
    if not bcrypt.checkpw(password.encode("utf-8"), user.hashed_password.encode("utf-8")):
        return None
    return user


def create_session_token(user: "User", sid: str | None = None) -> str:
    # Signed cookie value. `sid` is the secret session id whose SHA-256 is kept in
    # user_sessions (see open_session); without it the token is the stateless
    # format issued before that table existed ("legacy"), which authenticate_session
    # converts into a session the first time it is presented.
    payload = {"user_id": user.id, "pwv": _password_fingerprint(user.hashed_password)}
    if sid is not None:
        payload["sid"] = sid
    return _serializer.dumps(payload)


def session_id_of_token(token: str | None) -> str | None:
    # The secret session id carried by a (valid) token, to sign it again with a new
    # password fingerprint without changing the session.
    decoded = _decode_session_token(token)
    return decoded[0].get("sid") if decoded else None


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def open_session(db: "Session", user: "User", user_agent: str | None) -> str:
    # Called at sign-in: records the device in user_sessions and returns the cookie
    # value. Also the moment expired sessions are cleaned up.
    from backend.models import UserSession
    from backend.sessions import purge_expired_sessions

    purge_expired_sessions(db)
    sid = secrets.token_urlsafe(32)
    now = datetime.utcnow()
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=_hash(sid),
            user_agent=(user_agent or "")[:255],
            created_at=now,
            last_seen_at=now,
        )
    )
    db.commit()
    db.refresh(user)
    return create_session_token(user, sid)


def _decode_session_token(token: str | None) -> tuple[dict, datetime] | None:
    # (payload, moment it was signed, naive UTC) or None when forged or too old.
    if not token:
        return None
    try:
        payload, signed_at = _serializer.loads(token, max_age=SESSION_MAX_AGE, return_timestamp=True)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(payload, dict):
        return None
    return payload, signed_at.astimezone(timezone.utc).replace(tzinfo=None)


class _Resolved:
    # What a token stands for: the user, the session row it belongs to (None for a
    # legacy token not converted yet), and for that case the data to convert it.
    def __init__(self, user, session, legacy_hash=None, signed_at=None):
        self.user = user
        self.session = session
        self.legacy_hash = legacy_hash
        self.signed_at = signed_at


def _resolve(db: "Session", token: str | None) -> "_Resolved | None":
    # Complete check, read-only: valid signature, active user, password unchanged since
    # sign-in (fingerprint), and, for a token with a session id, a live session row of
    # THAT user. The role is read from the database each time (never frozen in the
    # token): a role change takes effect on the next request.
    decoded = _decode_session_token(token)
    if decoded is None:
        return None
    payload, signed_at = decoded
    from sqlalchemy import select

    from backend import crud
    from backend.models import UserSession
    from backend.sessions import SESSION_LIFETIME

    user = crud.get_user(db, payload.get("user_id"))
    if user is None or not user.is_active:
        return None
    if _password_fingerprint(user.hashed_password) != payload.get("pwv"):
        return None

    oldest = datetime.utcnow() - SESSION_LIFETIME
    sid = payload.get("sid")
    if sid is not None:
        row = db.scalar(select(UserSession).where(UserSession.token_hash == _hash(str(sid))))
        if row is None or row.user_id != user.id or row.revoked_at is not None or row.created_at < oldest:
            return None
        return _Resolved(user, row)

    # Token issued before the sessions table: accepted once, then converted.
    legacy_hash = _hash(token)
    row = db.scalar(select(UserSession).where(UserSession.legacy_hash == legacy_hash))
    if row is not None:
        if row.user_id != user.id or row.revoked_at is not None or row.created_at < oldest:
            return None
        return _Resolved(user, row)
    return _Resolved(user, None, legacy_hash, signed_at)


def authenticate_request(db: "Session", token: str | None) -> "User | None":
    # Read-only check (login page): who is this cookie, if anyone.
    resolved = _resolve(db, token)
    return resolved.user if resolved else None


def authenticate_session(
    db: "Session", token: str | None, user_agent: str | None
) -> "tuple[User | None, int | None, str | None]":
    # Complete check called by AuthMiddleware on EVERY request. Returns (user,
    # session row id, new cookie value or None):
    #  - a closed or unknown session gives (None, None, None): signed out;
    #  - a legacy token is converted into a session row and a new cookie is returned;
    #  - the last activity is written at most once per minute.
    resolved = _resolve(db, token)
    if resolved is None:
        return None, None, None
    from sqlalchemy import update
    from sqlalchemy.exc import IntegrityError

    from backend.models import UserSession
    from backend.sessions import TOUCH_INTERVAL

    user = resolved.user
    new_token = None
    session = resolved.session
    now = datetime.utcnow()
    if session is None:
        sid = secrets.token_urlsafe(32)
        session = UserSession(
            user_id=user.id,
            token_hash=_hash(sid),
            legacy_hash=resolved.legacy_hash,
            user_agent=(user_agent or "")[:255],
            created_at=min(resolved.signed_at, now),
            last_seen_at=now,
        )
        db.add(session)
        try:
            db.commit()
        except IntegrityError:
            # Another request carrying the same old token converted it first: join it.
            db.rollback()
            again = _resolve(db, token)
            if again is None or again.session is None:
                return None, None, None
            user, session = again.user, again.session
        else:
            new_token = create_session_token(user, sid)
    session_id = session.id
    result = db.execute(
        update(UserSession)
        .where(UserSession.id == session_id, UserSession.last_seen_at < now - TOUCH_INTERVAL)
        .values(last_seen_at=now)
    )
    if result.rowcount:
        db.commit()
    # Committing expired the instances: reload the user so it can be read after the
    # database session is closed.
    db.refresh(user)
    return user, session_id, new_token


def get_current_user(request: Request) -> "User | None":
    # Posé par AuthMiddleware (request.state.user) pour toute requête
    # authentifiée. None si AUTH_ENABLED=false (middleware jamais passée
    # par là) — les routes qui en dépendent doivent gérer ce cas (voir
    # backend/main.py, change_password).
    return getattr(request.state, "user", None)


# --- Politique de rôles ---
#
# viewer  : lecture seule partout (dashboard, rapports, opérations...), quel
#           que soit le chemin.
# editor  : en plus de la lecture, peut écrire sur les opérations
#           (catégoriser, modifier), la catégorisation en masse (backlog),
#           les budgets et les projets — exactement ce qui est listé comme
#           relevant de son rôle. Tout le reste (comptes, catégories, modes
#           de paiement, règles, abonnements récurrents, chèques en
#           attente, import, export/restore, paramètres, gestion des
#           utilisateurs) reste réservé à l'admin par défaut, prudence
#           délibérée plutôt qu'une extension non demandée de ses droits.
# admin   : accès complet, sans restriction.
#
# /settings/change-password, /profile/update, /profile/tour-seen, /profile/screen-tour-seen et /logout restent accessibles
# à N'IMPORTE QUEL rôle authentifié (changer son propre mot de passe/profil,
# se déconnecter) : ce sont des actions sur soi-même, pas sur les données de
# l'application. GET /profile n'a pas besoin d'être listé ici : déjà
# autorisé pour tout rôle par la règle GET/HEAD générale ci-dessous (pas un
# préfixe admin-only).
_SELF_SERVICE_PATHS = {"/settings/change-password", "/profile/update", "/profile/tour-seen", "/profile/screen-tour-seen", "/profile/preferences", "/profile/sessions/close", "/profile/sessions/close-others", "/logout"}

# Préfixes réservés à l'admin même en LECTURE (pas seulement en écriture) :
# assistant d'import et gestion des utilisateurs n'ont pas d'intérêt à être
# consultés par un rôle qui ne peut de toute façon rien y faire.
_ADMIN_ONLY_PREFIXES = ("/imports", "/users")

_EDITOR_WRITE_PREFIXES = ("/transactions", "/backlog", "/budgets", "/projects", "/cap")


def check_role_access(role: str, method: str, path: str) -> bool:
    if role == "admin":
        return True
    if path in _SELF_SERVICE_PATHS:
        return True
    if any(path.startswith(prefix) for prefix in _ADMIN_ONLY_PREFIXES):
        return False
    if method in ("GET", "HEAD"):
        return True
    if role != "editor":
        return False  # viewer : aucune écriture nulle part
    if method == "DELETE" or "delete" in path:
        return False  # suppression toujours réservée à l'admin
    if path.startswith("/settings") or path == "/export/restore":
        return False
    return any(path.startswith(prefix) for prefix in _EDITOR_WRITE_PREFIXES)
