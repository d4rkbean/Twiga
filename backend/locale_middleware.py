from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from backend import i18n, preferences


class LocaleMiddleware(BaseHTTPMiddleware):
    # Fixe la langue et le format de la requête (voir backend/i18n.py). À
    # ajouter AVANT AuthMiddleware dans main.py : Starlette exécute les
    # middlewares dans l'ordre inverse de leur ajout, donc celle-ci passe
    # APRÈS l'authentification et peut lire request.state.user. Sur les
    # chemins publics (/login), il n'y a pas d'utilisateur : le cookie décide.
    async def dispatch(self, request: Request, call_next):
        user = getattr(request.state, "user", None)
        language, number_format = i18n.resolve_locale(user, request.cookies)
        i18n.set_locale(language, number_format)
        request.state.language = language
        # Display preferences (interface variant, theme, density) resolve the
        # same way: account, then cookie, then default.
        ui_variant, theme, density = preferences.resolve(user, request.cookies)
        preferences.set_current(ui_variant, theme, density)
        request.state.ui_variant = ui_variant
        request.state.theme = theme
        request.state.density = density
        return await call_next(request)
