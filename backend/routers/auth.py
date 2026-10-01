import time

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from backend import auth, crud
from backend.database import get_db
from backend.templating import templates
from backend.i18n import gettext as _t

router = APIRouter(tags=["auth"])

# Anti brute-force minimal : état en mémoire du process, comme
# routers/export.py (_restore_progress) — appli mono-utilisateur, un seul
# worker uvicorn (voir CLAUDE.md), donc pas besoin d'un stockage partagé
# (Redis...) pour que ça tienne. Verrouille par IP ET par identifiant
# tenté : verrouiller seulement par IP bloquerait toute la maisonnée
# derrière une même box internet dès qu'un seul membre se trompe trop de
# fois ; verrouiller seulement par identifiant permettrait à un attaquant
# de tester en boucle sur un compte connu depuis des IP différentes.
_MAX_ATTEMPTS = 5
_LOCKOUT_SECONDS = 15 * 60
_failed_attempts: dict[tuple[str, str], list[float]] = {}


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _is_locked_out(key: tuple[str, str]) -> bool:
    now = time.monotonic()
    attempts = [t for t in _failed_attempts.get(key, []) if now - t < _LOCKOUT_SECONDS]
    _failed_attempts[key] = attempts
    return len(attempts) >= _MAX_ATTEMPTS


def _record_failed_attempt(key: tuple[str, str]) -> None:
    _failed_attempts.setdefault(key, []).append(time.monotonic())


def _clear_failed_attempts(key: tuple[str, str]) -> None:
    _failed_attempts.pop(key, None)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    if not auth.AUTH_ENABLED:
        return RedirectResponse(url="/")
    if auth.authenticate_request(db, request.cookies.get(auth.SESSION_COOKIE_NAME)):
        return RedirectResponse(url="/dashboard")
    return templates.TemplateResponse("login.html", {"request": request})


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
            _t('<p class="text-sm text-danger">Trop de tentatives. Réessaie dans quelques minutes.</p>'),
            status_code=429,
        )

    user = auth.verify_password(db, username, password)
    if user is None:
        _record_failed_attempt(key)
        return HTMLResponse(
            _t('<p class="text-sm text-danger">Nom d\'utilisateur ou mot de passe incorrect.</p>'),
            status_code=401,
        )
    _clear_failed_attempts(key)
    crud.touch_last_login(db, user.id)
    response = HTMLResponse(status_code=200)
    response.headers["HX-Redirect"] = "/dashboard"
    response.set_cookie(
        auth.SESSION_COOKIE_NAME,
        auth.create_session_token(user),
        max_age=auth.SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return response


@router.post("/logout")
def logout():
    if not auth.AUTH_ENABLED:
        return RedirectResponse(url="/")
    response = HTMLResponse(status_code=200)
    response.headers["HX-Redirect"] = "/login"
    response.delete_cookie(auth.SESSION_COOKIE_NAME)
    return response
