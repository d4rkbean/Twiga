from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from markupsafe import escape
from sqlalchemy.orm import Session

from backend import auth, crud
from backend.database import get_db
from backend.templating import templates

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
        return HTMLResponse('<p class="text-sm text-danger py-2">Authentification désactivée.</p>', status_code=400)

    error = crud.update_user_profile(db, current_user.id, display_name, username)
    if error:
        # error peut embarquer le nom d'utilisateur SAISI (voir
        # crud.update_user_profile) : contrairement aux routes qui passent
        # par templates.TemplateResponse (auto-échappement Jinja), cette
        # réponse est un HTMLResponse construit à la main -> échappement
        # manuel obligatoire, sinon un nom d'utilisateur contenant du HTML
        # s'exécuterait tel quel dans la page (XSS).
        return HTMLResponse(f'<p class="text-sm text-danger py-2">{escape(error)}</p>', status_code=400)
    return HTMLResponse('<p class="text-sm text-success py-2">✓ Profil mis à jour.</p>')


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
