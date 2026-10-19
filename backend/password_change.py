"""Accounts still using the well-known default password ("changeme").

The first admin account gets AUTH_PASSWORD, "changeme" unless it was changed in
.env. As long as an account signs in with that password, every page sends it
to the password change (Mon profil, the same form and route as usual) and the
other actions are refused; signing out, the static files and the change itself
stay open. Nothing blocks the start of the application and nobody is signed
out: the account only has to pick a new password.

Whether an account uses the default password is checked with bcrypt once per
password hash (the result is kept in memory), not on every request.
"""

from __future__ import annotations

import logging
import os

import bcrypt
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse, Response

from backend import i18n
from backend.database import SessionLocal, get_db
from backend.i18n import gettext as _t

logger = logging.getLogger("twiga.security")

DEFAULT_PASSWORDS = ("changeme",)
CHANGE_PATH = "/profile/password"

# Reachable while the password has not been changed: the change screen and its
# form, signing out, and what any page needs (static files, language, tour).
_OPEN_PATHS = {
    CHANGE_PATH,
    "/settings/change-password",
    "/logout",
    "/login",
    "/health",
    "/profile/preferences",
    "/profile/tour-seen",
    "/profile/screen-tour-seen",
}
_OPEN_PREFIXES = ("/static/",)

_MAX_CACHED = 1000
_checked: dict[str, bool] = {}


def uses_default_password(hashed_password: str) -> bool:
    if hashed_password not in _checked:
        if len(_checked) >= _MAX_CACHED:
            _checked.clear()
        _checked[hashed_password] = any(
            bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8")) for password in DEFAULT_PASSWORDS
        )
    return _checked[hashed_password]


def warn_about_default_passwords() -> None:
    """Startup: a log line when AUTH_PASSWORD or an account is still "changeme"."""
    from backend import auth, crud

    if not auth.AUTH_ENABLED:
        return
    if (os.environ.get("AUTH_PASSWORD") or DEFAULT_PASSWORDS[0]) in DEFAULT_PASSWORDS:
        logger.warning(
            "AUTH_PASSWORD is the default value 'changeme': set another one in .env before the first start"
        )
    db = SessionLocal()
    try:
        names = [user.username for user in crud.list_users(db) if user.is_active and uses_default_password(user.hashed_password)]
    finally:
        db.close()
    if names:
        logger.warning(
            "These accounts still use the default password and will be asked to change it at sign-in: %s",
            ", ".join(names),
        )


class PasswordChangeMiddleware(BaseHTTPMiddleware):
    # Added before AuthMiddleware in main.py, so it runs after it and reads
    # request.state.user. Without authentication there is no user: nothing to do.
    async def dispatch(self, request: Request, call_next):
        user = getattr(request.state, "user", None)
        path = request.url.path
        if user is None or path.startswith(_OPEN_PREFIXES):
            return await call_next(request)
        if not await run_in_threadpool(uses_default_password, user.hashed_password):
            return await call_next(request)

        if path in _OPEN_PATHS:
            response = await call_next(request)
            if path == "/settings/change-password" and response.status_code == 200:
                # Changed: back to the application.
                response.headers["HX-Redirect"] = "/dashboard"
            return response

        if request.method in ("GET", "HEAD"):
            if request.headers.get("HX-Request") == "true":
                # A fragment the page loads by itself (sidebar balance...): left out.
                return Response(status_code=204)
            return RedirectResponse(url=CHANGE_PATH, status_code=303)
        # An HTMX fragment or a form: a message where the answer would go
        # (redirecting a fragment could reload a page that asks for it again).
        i18n.set_locale(*i18n.resolve_locale(user, request.cookies))
        message = _t("Change d'abord ton mot de passe dans Mon profil.")
        return Response(
            f'<p class="text-sm text-danger py-2">{message}</p>',
            status_code=403,
            media_type="text/html",
        )


router = APIRouter(tags=["profile"])


@router.get(CHANGE_PATH, response_class=HTMLResponse)
def password_change_page(request: Request, db: Session = Depends(get_db)):
    """Mon profil with a notice above it: the password still has to be changed."""
    from backend.routers.profile import profile_page
    from backend.templating import templates

    page = profile_page(request, db)
    context = getattr(page, "context", None)
    if context is None:
        return page  # no signed-in user (authentication off): the usual redirect
    return templates.TemplateResponse("profile_password_required.html", context)
