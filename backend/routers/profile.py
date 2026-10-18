from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from backend import auth, crud, i18n
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
    return templates.TemplateResponse(
        "profile.html", {"request": request, "current": current_user, "auth_enabled": auth.AUTH_ENABLED}
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
    return HTMLResponse(flash_html("success", _t("✓ Profil mis à jour.")))


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
    language: str = Form(...),
    number_format: str = Form(...),
    db: Session = Depends(get_db),
):
    # Langue de l'interface et format des nombres/dates (backend/i18n.py).
    # Enregistrés sur le compte, et aussi en cookie : sans authentification, ou
    # sur la page de connexion, c'est le cookie qui décide. HX-Refresh recharge
    # la page pour que toute l'interface passe dans la nouvelle langue.
    if language not in i18n.LANGUAGES or number_format not in i18n.FORMATS:
        return Response(status_code=400)

    current_user = auth.get_current_user(request)
    if auth.AUTH_ENABLED and current_user is not None:
        user = db.get(type(current_user), current_user.id)
        if user is not None:
            user.language = language
            user.number_format = number_format
            db.commit()

    response = Response(status_code=200, headers={"HX-Refresh": "true"})
    one_year = 365 * 24 * 3600
    response.set_cookie("twiga_lang", language, max_age=one_year, samesite="lax")
    response.set_cookie("twiga_fmt", number_format, max_age=one_year, samesite="lax")
    return response
