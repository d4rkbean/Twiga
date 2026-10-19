from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from backend import answers, auth, crud, i18n, preferences
from backend.database import get_db
from backend.templating import flash_html, templates
from backend.i18n import gettext as _t

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_class=HTMLResponse)
def profile_page(request: Request, db: Session = Depends(get_db)):
    current_user = auth.get_current_user(request)
    if not auth.AUTH_ENABLED or current_user is None:
        # Rien à afficher/éditer sans utilisateur connecté (authentification
        # désactivée) : l'ancien menu ⚙️ Paramètres reste le seul point
        # d'entrée dans ce cas, voir _sidebar.html/_header.html.
        return RedirectResponse(url="/settings")
    # The other way previews the display on a miniature of the real screen: the total
    # balance and the latest operations. Classic ignores these keys.
    recent, _total = crud.list_transactions(db, page_size=5)
    return templates.TemplateResponse(
        "profile.html",
        {
            "request": request,
            "current": current_user,
            "auth_enabled": auth.AUTH_ENABLED,
            "preview_balance": crud.get_total_balance(db),
            "preview_recent": recent,
            "words": answers.profile_words(),
            "answer": answers.profile_answer(preferences.current_theme(), preferences.current_density(), False),
        },
    )


@router.post("/update", response_class=HTMLResponse)
def update_profile(
    request: Request,
    display_name: str = Form(""),
    username: str = Form(...),
    db: Session = Depends(get_db),
):
    # Auto-service : chaque utilisateur ne modifie que SON PROPRE profil
    # (nom affiché, nom d'utilisateur) — jamais son rôle, réservé à l'admin
    # via Paramètres > Utilisateurs (backend/routers/users.py).
    current_user = auth.get_current_user(request)
    if not auth.AUTH_ENABLED or current_user is None:
        return HTMLResponse(flash_html("error", _t("Authentification désactivée.")), status_code=400)

    error = crud.update_user_profile(db, current_user.id, display_name, username)
    if error:
        # error may embed the username the user TYPED (see
        # crud.update_user_profile): it goes through the _flash.html fragment,
        # whose Jinja autoescape keeps any HTML in it inert (no XSS).
        return HTMLResponse(flash_html("error", error), status_code=400)
    return HTMLResponse(flash_html("success", _t("Profil mis à jour.")))


@router.post("/tour-seen", status_code=204)
def mark_tour_seen(request: Request, db: Session = Depends(get_db)):
    # Appelé par tour.js à la fin ou à l'abandon de la visite guidée : le
    # compte ne la reverra plus à la connexion (elle reste relançable à la
    # main depuis Aide). Sans authentification, rien à mémoriser côté
    # serveur : tour.js retombe sur localStorage.
    current_user = auth.get_current_user(request)
    if auth.AUTH_ENABLED and current_user is not None:
        user = db.get(type(current_user), current_user.id)
        if user is not None and user.tour_seen_at is None:
            user.tour_seen_at = datetime.utcnow()
            db.commit()
    return Response(status_code=204)


@router.post("/preferences")
def update_preferences(
    request: Request,
    language: str | None = Form(None),
    number_format: str | None = Form(None),
    ui_variant: str | None = Form(None),
    theme: str | None = Form(None),
    density: str | None = Form(None),
    db: Session = Depends(get_db),
):
    # Preferences of the current user: language and number/date format
    # (backend/i18n.py), interface variant, theme and density
    # (backend/preferences.py). Every field is optional, only the ones sent are
    # written, so each form posts just its own fields. Written on the account
    # AND in a cookie: without authentication, or on the login page, the cookie
    # decides. A language or format change answers HX-Refresh so the whole
    # interface is rendered again; display changes (theme, density...) are
    # applied by the page itself and only get a discreet confirmation.
    if (language is not None and language not in i18n.LANGUAGES) or (
        number_format is not None and number_format not in i18n.FORMATS
    ):
        return Response(status_code=400)
    if (
        (ui_variant is not None and ui_variant not in preferences.valid_ui_variants())
        or (theme is not None and theme not in preferences.THEMES)
        or (density is not None and density not in preferences.DENSITIES)
    ):
        return Response(status_code=400)
    sent = {
        "language": language,
        "number_format": number_format,
        "ui_variant": ui_variant,
        "theme": theme,
        "density": density,
    }
    sent = {name: value for name, value in sent.items() if value is not None}
    if not sent:
        return Response(status_code=400)

    # The account is always the CURRENT user's: the request carries no user id,
    # so nobody can change another user's preferences.
    current_user = auth.get_current_user(request)
    if auth.AUTH_ENABLED and current_user is not None:
        user = db.get(type(current_user), current_user.id)
        if user is not None:
            for name, value in sent.items():
                setattr(user, name, value)
            db.commit()

    # Switching the interface variant changes the whole shell (navigation,
    # menus, tour), so the page is rendered again, like for the language. The
    # display form posts all its fields on every change: only a variant that
    # differs from the one rendering this request counts.
    variant_changed = "ui_variant" in sent and sent["ui_variant"] != getattr(request.state, "ui_variant", None)
    if "language" in sent or "number_format" in sent or variant_changed:
        response = Response(status_code=200, headers={"HX-Refresh": "true"})
    else:
        response = HTMLResponse(flash_html("success", _t("Réglage enregistré")))
    one_year = 365 * 24 * 3600
    cookie_names = {
        "language": "twiga_lang",
        "number_format": "twiga_fmt",
        "ui_variant": preferences.UI_COOKIE,
        "theme": preferences.THEME_COOKIE,
        "density": preferences.DENSITY_COOKIE,
    }
    for name, value in sent.items():
        response.set_cookie(cookie_names[name], value, max_age=one_year, samesite="lax")
    return response
