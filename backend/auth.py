from __future__ import annotations

import hashlib
import os
import secrets
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


def create_session_token(user: "User") -> str:
    return _serializer.dumps({"user_id": user.id, "pwv": _password_fingerprint(user.hashed_password)})


def _decode_session_token(token: str | None) -> dict | None:
    if not token:
        return None
    try:
        return _serializer.loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def authenticate_request(db: "Session", token: str | None) -> "User | None":
    # Vérification complète appelée par AuthMiddleware à CHAQUE requête :
    # jeton valide ET utilisateur toujours actif ET mot de passe inchangé
    # depuis la connexion (empreinte). Une DB déjà consultée pour is_active
    # rend le rôle TOUJOURS lu à jour (pas figé dans le jeton) : un
    # changement de rôle par un admin prend effet à la requête suivante,
    # sans obliger l'utilisateur concerné à se reconnecter.
    payload = _decode_session_token(token)
    if payload is None:
        return None
    from backend import crud

    user = crud.get_user(db, payload.get("user_id"))
    if user is None or not user.is_active:
        return None
    if _password_fingerprint(user.hashed_password) != payload.get("pwv"):
        return None
    return user


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
# /settings/change-password, /profile/update, /profile/tour-seen et /logout restent accessibles
# à N'IMPORTE QUEL rôle authentifié (changer son propre mot de passe/profil,
# se déconnecter) : ce sont des actions sur soi-même, pas sur les données de
# l'application. GET /profile n'a pas besoin d'être listé ici : déjà
# autorisé pour tout rôle par la règle GET/HEAD générale ci-dessous (pas un
# préfixe admin-only).
_SELF_SERVICE_PATHS = {"/settings/change-password", "/profile/update", "/profile/tour-seen", "/logout"}

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
