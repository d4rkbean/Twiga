from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    # Appliquée à TOUTE réponse, y compris /static/ et /login : contrairement
    # à AuthMiddleware, ces en-têtes n'ont aucune raison de dépendre de
    # AUTH_ENABLED ni d'un quelconque chemin public.
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for name, value in _HEADERS.items():
            response.headers.setdefault(name, value)
        return response
