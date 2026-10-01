from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from backend import auth
from backend.database import SessionLocal
from backend.i18n import gettext as _t

_PUBLIC_PATHS = {"/login", "/health"}
_PUBLIC_PREFIXES = ("/static/",)


class AuthMiddleware(BaseHTTPMiddleware):
    # Vérifie elle-même le cookie de session signé (voir backend/auth.py,
    # via itsdangerous) au lieu de dépendre de request.session /
    # SessionMiddleware : cette middleware n'a besoin d'aucune autre
    # middleware installée avant elle.
    async def dispatch(self, request: Request, call_next):
        if not auth.AUTH_ENABLED:
            return await call_next(request)

        path = request.url.path
        if path in _PUBLIC_PATHS or path.startswith(_PUBLIC_PREFIXES):
            return await call_next(request)

        token = request.cookies.get(auth.SESSION_COOKIE_NAME)

        # Une seule Session pour toute la requête (fermée avant call_next,
        # pas de risque de la garder ouverte pendant tout le traitement de
        # la route — chaque route ouvre de toute façon la sienne via
        # Depends(get_db)).
        db = SessionLocal()
        try:
            user = auth.authenticate_request(db, token)
        finally:
            db.close()

        if user is None:
            return self._unauthenticated_response(request)

        if not auth.check_role_access(user.role, request.method, path):
            return self._forbidden_response(request)

        # Utilisateur courant exposé aux routes/templates sans re-décoder le
        # cookie ni retaper la Session (voir backend/routers/auth.py,
        # get_current_user, qui lit ceci).
        request.state.user = user
        return await call_next(request)

    @staticmethod
    def _unauthenticated_response(request: Request) -> Response:
        # Une requête HTMX qui expire en session ne doit pas afficher la
        # page de login à l'intérieur du fragment ciblé par le swap : on
        # demande à htmx une redirection complète de la page via l'en-tête
        # HX-Redirect plutôt qu'une redirection HTTP classique (que le
        # XHR sous-jacent suivrait silencieusement et injecterait comme
        # contenu swappé).
        if request.headers.get("HX-Request") == "true":
            return Response(status_code=200, headers={"HX-Redirect": "/login"})
        return RedirectResponse(url="/login", status_code=303)

    @staticmethod
    def _forbidden_response(request: Request) -> Response:
        message = _t("Action réservée à un rôle supérieur.")
        if request.headers.get("HX-Request") == "true":
            return Response(
                content=f'<p class="text-sm text-danger py-2">🔒 {message}</p>',
                status_code=403,
                media_type="text/html",
            )
        return Response(content=message, status_code=403)
