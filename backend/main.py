import os
from decimal import Decimal
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from backend import auth, crud
from backend.auth_middleware import AuthMiddleware
from backend.locale_middleware import LocaleMiddleware
from backend.database import SessionLocal, get_db
from backend.security_headers import SecurityHeadersMiddleware
from backend.routers import (
    accounts,
    auth as auth_router,
    backlog,
    budgets,
    cap,
    categories,
    checks,
    dashboard,
    export,
    imports,
    payment_methods,
    profile,
    projects,
    receipts,
    recurring,
    reports,
    rules,
    search,
    transactions,
    users as users_router,
)
from backend.templating import templates
from backend.i18n import gettext as _t, ngettext

BASE_DIR = Path(__file__).resolve().parent.parent

app = FastAPI(title="Twiga")

# Starlette exécute les middlewares dans l'ordre INVERSE de add_middleware
# (le dernier ajouté est le plus externe) : SecurityHeadersMiddleware doit
# donc être ajoutée APRÈS AuthMiddleware pour s'appliquer aussi aux réponses
# de redirection/401 générées par celle-ci, pas seulement aux réponses des
# routes.
# LocaleMiddleware d'abord : elle doit s'exécuter APRÈS AuthMiddleware (ordre
# inverse de l'ajout) pour lire request.state.user.
app.add_middleware(LocaleMiddleware)
if auth.AUTH_ENABLED:
    # AuthMiddleware gère elle-même son cookie de session signé (voir
    # backend/auth.py) : pas besoin de SessionMiddleware ni de se soucier
    # d'un quelconque ordre d'empilement entre deux middlewares.
    app.add_middleware(AuthMiddleware)
app.add_middleware(SecurityHeadersMiddleware)


@app.on_event("startup")
def load_session_secret() -> None:
    # Charge (ou génère au tout premier démarrage) le secret partagé de
    # signature des cookies de session — voir backend/auth.py. entrypoint.sh
    # lance "alembic upgrade head" avant uvicorn : la table/colonne existe
    # déjà à ce stade, ainsi que le compte admin semé par la migration.
    db = SessionLocal()
    try:
        auth.load_session_secret(db)
    finally:
        db.close()


@app.get("/static/sw.js")
def service_worker():
    # Route dédiée (avant le mount StaticFiles) pour ajouter Service-Worker-
    # Allowed : sans cet en-tête, un service worker servi depuis /static/
    # ne peut par défaut contrôler que ce sous-dossier, pas la racine "/"
    # (start_url du manifest) — ce qui empêcherait l'installation de la PWA.
    return FileResponse(
        BASE_DIR / "frontend" / "static" / "sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )


app.mount("/static", StaticFiles(directory=BASE_DIR / "frontend" / "static"), name="static")

app.include_router(auth_router.router)
app.include_router(transactions.router)
app.include_router(backlog.router)
app.include_router(categories.router)
app.include_router(accounts.router)
app.include_router(payment_methods.router)
app.include_router(budgets.router)
app.include_router(cap.router)
app.include_router(projects.router)
app.include_router(receipts.router)
app.include_router(imports.router)
app.include_router(rules.router)
app.include_router(dashboard.router)
app.include_router(export.router)
app.include_router(search.router)
app.include_router(recurring.router)
app.include_router(checks.router)
app.include_router(reports.router)
app.include_router(users_router.router)
app.include_router(profile.router)


@app.get("/")
def root():
    return RedirectResponse(url="/transactions/inbox")


# Guide de style vivant : rend les composants canoniques de
# design-system.css en vrai HTML, pas en captures. Volontairement absent en
# production — la variable n'est pas dans .env par défaut, donc la route
# renvoie 404 tant qu'on ne l'active pas explicitement.
SHOW_DESIGN_SYSTEM = os.environ.get("SHOW_DESIGN_SYSTEM", "false").lower() == "true"


@app.get("/design-system", response_class=HTMLResponse)
def design_system(request: Request):
    if not SHOW_DESIGN_SYSTEM:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse("design_system.html", {"request": request})


@app.get("/settings", response_class=HTMLResponse)
def settings(request: Request, db: Session = Depends(get_db)):
    cap_settings = crud.get_cap_settings(db)
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "auth_enabled": auth.AUTH_ENABLED,
            "cap_settings": cap_settings,
            "income_sources": crud.INCOME_SOURCES,
            "accounts": crud.list_accounts(db),
        },
    )


@app.post("/settings/cap-income-source", response_class=HTMLResponse)
def save_cap_income_source(
    income_source: str = Form(...),
    income_account_id: str = Form(""),
    income_fixed_amount: str = Form(""),
    db: Session = Depends(get_db),
):
    """D'où viennent les ressources du mois — voir models.CapSettings.

    Ce réglage ne pilote QUE le pré-remplissage du rituel, jamais le calcul :
    le suivi se réfère toujours au montant saisi dans le Cap.
    """
    settings_row = crud.get_cap_settings(db)
    if income_source in crud.INCOME_SOURCE_CODES:
        settings_row.income_source = income_source
    settings_row.income_account_id = int(income_account_id) if income_account_id else None
    try:
        settings_row.income_fixed_amount = (
            Decimal(income_fixed_amount) if income_fixed_amount.strip() else None
        )
    except (ArithmeticError, ValueError):
        settings_row.income_fixed_amount = None
    db.commit()
    return HTMLResponse(content=_t('<p class="text-sm text-success py-2">✓ Réglage enregistré</p>'))


@app.post("/settings/detect-payment-methods", response_class=HTMLResponse)
def detect_payment_methods(db: Session = Depends(get_db)):
    updated_count = crud.detect_missing_payment_methods(db)
    return HTMLResponse(
        content=(
            '<p class="text-sm text-success py-2">'
            + ngettext(
                "✓ %(n)s transaction mise à jour</p>", "✓ %(n)s transactions mises à jour</p>", updated_count
            )
            % {"n": updated_count}
        )
    )


@app.post("/settings/change-password", response_class=HTMLResponse)
def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    # Change le mot de passe de l'utilisateur CONNECTÉ (n'importe quel rôle
    # peut changer le sien — voir auth._SELF_SERVICE_PATHS) ; réinitialiser
    # le mot de passe d'un AUTRE utilisateur passe par Paramètres >
    # Utilisateurs (admin uniquement, voir backend/routers/users.py).
    error = '<p class="text-sm text-danger py-2">{}</p>'
    current_user = auth.get_current_user(request)
    if not auth.AUTH_ENABLED or current_user is None:
        return HTMLResponse(error.format(_t("Authentification désactivée.")), status_code=400)
    if auth.verify_password(db, current_user.username, current_password) is None:
        return HTMLResponse(error.format(_t("Mot de passe actuel incorrect.")), status_code=401)
    if new_password != confirm_password:
        return HTMLResponse(error.format(_t("Les nouveaux mots de passe ne correspondent pas.")), status_code=400)
    if len(new_password) < 8:
        return HTMLResponse(error.format(_t("Le nouveau mot de passe doit faire au moins 8 caractères.")), status_code=400)

    crud.set_user_password(db, current_user.id, new_password)
    db.refresh(current_user)

    # Le jeton de session embarque une empreinte du mot de passe (voir
    # backend/auth.py, authenticate_request) : changer le mot de passe
    # invalide donc le cookie actuel, on en réémet un nouveau tout de suite
    # pour ne pas déconnecter l'utilisateur qui vient de changer le sien.
    response = HTMLResponse(_t('<p class="text-sm text-success py-2">✓ Mot de passe modifié.</p>'))
    response.set_cookie(
        auth.SESSION_COOKIE_NAME,
        auth.create_session_token(current_user),
        max_age=auth.SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return response


@app.get("/health")
def health():
    return {"status": "ok"}
