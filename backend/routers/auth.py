import os
import time

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from backend import answers, auth, crud, sessions
from backend.templating import user_display_name, user_initials, user_role_label
from backend.database import get_db
from backend.templating import flash_html, templates
from backend.i18n import gettext as _t

router = APIRouter(tags=["auth"])

# Anti brute-force minimal : état en mémoire du process, comme
# routers/export.py (_restore_progress) — appli mono-utilisateur, un seul
# worker uvicorn (voir le guide du projet), donc pas besoin d'un stockage partagé
# (Redis...) pour que ça tienne. Verrouille par IP ET par identifiant
# tenté : verrouiller seulement par IP bloquerait toute la maisonnée
# derrière une même box internet dès qu'un seul membre se trompe trop de
# fois ; verrouiller seulement par identifiant permettrait à un attaquant
# de tester en boucle sur un compte connu depuis des IP différentes.
_MAX_ATTEMPTS = 5
_LOCKOUT_SECONDS = 15 * 60
# Every address together, per username: an attacker spreading the attempts on
# a known account over many addresses is stopped as well. A success from one
# address does not clear this counter.
_MAX_ATTEMPTS_PER_USERNAME = 20
# Bounded memory: expired entries are dropped, then the oldest ones.
_MAX_TRACKED = 10_000
_failed_attempts: dict[tuple[str, str], list[float]] = {}
_failed_by_username: dict[str, list[float]] = {}

# Reverse proxies whose X-Forwarded-For is believed (comma-separated
# addresses). Empty: the address of the direct connection, as before.
TRUSTED_PROXIES = {value.strip() for value in os.environ.get("TRUSTED_PROXIES", "").split(",") if value.strip()}


def _client_ip(request: Request) -> str:
    direct = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if direct not in TRUSTED_PROXIES or not forwarded:
        return direct
    # The last address not added by one of our own proxies is the client.
    hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
    for hop in reversed(hops):
        if hop not in TRUSTED_PROXIES:
            return hop
    return hops[0] if hops else direct


def _recent(store: dict, key, now: float) -> list[float]:
    attempts = [t for t in store.get(key, []) if now - t < _LOCKOUT_SECONDS]
    if attempts:
        store[key] = attempts
    else:
        store.pop(key, None)
    return attempts


def _add(store: dict, key, now: float) -> None:
    attempts = _recent(store, key, now)
    store.pop(key, None)
    if len(store) >= _MAX_TRACKED:
        for stale in [k for k, times in store.items() if now - times[-1] >= _LOCKOUT_SECONDS]:
            del store[stale]
        while len(store) >= _MAX_TRACKED:
            del store[next(iter(store))]  # least recently failed first
    store[key] = attempts + [now]


def _is_locked_out(key: tuple[str, str]) -> bool:
    now = time.monotonic()
    return (
        len(_recent(_failed_attempts, key, now)) >= _MAX_ATTEMPTS
        or len(_recent(_failed_by_username, key[1], now)) >= _MAX_ATTEMPTS_PER_USERNAME
    )


def _record_failed_attempt(key: tuple[str, str]) -> None:
    now = time.monotonic()
    _add(_failed_attempts, key, now)
    _add(_failed_by_username, key[1], now)


def _clear_failed_attempts(key: tuple[str, str]) -> None:
    _failed_attempts.pop(key, None)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    if not auth.AUTH_ENABLED:
        return RedirectResponse(url="/")
    if auth.authenticate_request(db, request.cookies.get(auth.SESSION_COOKIE_NAME)):
        return RedirectResponse(url="/dashboard")
    # "Afficher les comptes sur la page de connexion" (Paramètres, off by default): only
    # when the administrator turned it on does this public page name the household.
    show_accounts = crud.get_or_create_app_state(db).show_login_accounts
    accounts = (
        [
            {
                "username": user.username,
                "name": user_display_name(user),
                "initials": user_initials(user),
                "role": user_role_label(user.role),
            }
            for user in crud.list_users(db)
            if user.is_active
        ]
        if show_accounts
        else []
    )
    context = {
        "request": request,
        "login_accounts": accounts,
        "login_title": answers.login_title(bool(accounts)),
    }
    return templates.TemplateResponse("login.html", context)


@router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    if not auth.AUTH_ENABLED:
        return RedirectResponse(url="/")

    key = (_client_ip(request), username.strip().lower())
    if _is_locked_out(key):
        return HTMLResponse(
            flash_html("error", _t("Trop de tentatives. Réessaie dans quelques minutes.")),
            status_code=429,
        )

    user = auth.verify_password(db, username, password)
    if user is None:
        _record_failed_attempt(key)
        return HTMLResponse(
            flash_html("error", _t("Nom d'utilisateur ou mot de passe incorrect.")),
            status_code=401,
        )
    _clear_failed_attempts(key)
    crud.touch_last_login(db, user.id)
    response = HTMLResponse(status_code=200)
    response.headers["HX-Redirect"] = "/dashboard"
    response.set_cookie(
        auth.SESSION_COOKIE_NAME,
        auth.open_session(db, user, request.headers.get("user-agent")),
        max_age=auth.SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return response


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    if not auth.AUTH_ENABLED:
        return RedirectResponse(url="/")
    # Only this device's session is closed; the others stay open.
    current_user = auth.get_current_user(request)
    session_id = getattr(request.state, "session_id", None)
    if current_user is not None and session_id is not None:
        sessions.close_session(db, current_user.id, session_id)
    response = HTMLResponse(status_code=200)
    response.headers["HX-Redirect"] = "/login"
    response.delete_cookie(auth.SESSION_COOKIE_NAME)
    return response
