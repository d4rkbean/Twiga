from __future__ import annotations

import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}

# Only sent over HTTPS: browsers ignore it over plain HTTP, and sending it
# would otherwise lock a host name to HTTPS for a year.
_HSTS = "max-age=31536000"

# COOKIE_SECURE: "auto" (default) marks the cookies Secure when the request
# arrived over HTTPS (directly, or through a reverse proxy that sets
# X-Forwarded-Proto: https); "true" always (HTTPS only, the session is lost over
# plain HTTP); "false" never.
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "auto").strip().lower()


def is_https(request: Request) -> bool:
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    return request.url.scheme == "https" or forwarded == "https"


def cookies_secure(request: Request) -> bool:
    if COOKIE_SECURE in ("true", "1", "yes", "on"):
        return True
    if COOKIE_SECURE in ("false", "0", "no", "off"):
        return False
    return is_https(request)


def _with_secure(cookie: bytes) -> bytes:
    attributes = [part.strip().lower() for part in cookie.split(b";")[1:]]
    return cookie if b"secure" in attributes else cookie + b"; Secure"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    # Appliquée à TOUTE réponse, y compris /static/ et /login : contrairement
    # à AuthMiddleware, ces en-têtes n'ont aucune raison de dépendre de
    # AUTH_ENABLED ni d'un quelconque chemin public.
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for name, value in _HEADERS.items():
            response.headers.setdefault(name, value)
        if is_https(request):
            response.headers.setdefault("Strict-Transport-Security", _HSTS)
        if cookies_secure(request):
            # Every cookie set by the routes or the other middlewares (session,
            # language...) keeps HttpOnly and SameSite and gains Secure.
            response.raw_headers[:] = [
                (name, _with_secure(value) if name == b"set-cookie" else value)
                for name, value in response.raw_headers
            ]
        return response
