import os
from decimal import Decimal
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from backend import auth, budget_month, crud
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
from backend.templating import flash_html, templates, user_display_name
from backend.i18n import current_language, gettext as _t, ngettext

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


def _household_label(users: list) -> str:
    """"Foyer d'Alex et Sam": the first names of the household, with the
    French elision ("d'Alex" but "de Sam")."""
    names = [user_display_name(user) for user in users if user.is_active]
    if not names:
        return ""
    joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " " + _t("et") + " " + names[-1]
    if current_language() == "fr":
        return (_t("Foyer d'%(names)s") if joined[:1].lower() in "aeiouyhàâéèêîô" else _t("Foyer de %(names)s")) % {
            "names": joined
        }
    return _t("Foyer de %(names)s") % {"names": joined}


@app.get("/settings", response_class=HTMLResponse)
def settings(request: Request, db: Session = Depends(get_db)):
    cap_settings = crud.get_cap_settings(db)
    users = crud.list_users(db)
    rules = crud.get_rules_with_usage(db)
    balances = crud.get_account_balances(db)
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "auth_enabled": auth.AUTH_ENABLED,
            "cap_settings": cap_settings,
            "income_sources": crud.INCOME_SOURCES,
            "accounts": crud.list_accounts(db),
            "last_backup_at": crud.get_or_create_app_state(db).last_backup_at,
            "household_label": _household_label(users),
            "users": users,
            "account_balances": balances,
            "accounts_total": sum((balance for _account, balance in balances), Decimal("0")),
            "categories": crud.get_categories_tree(db),
            "rules": rules[:6],
            "recurring_count": crud.get_recurring_patterns_overview(db)["recurring_active_count"],
            "pending_checks_count": len(crud.get_outstanding_pending_checks(db)),
        },
    )


@app.post("/settings/budget-start-day", response_class=HTMLResponse)
def save_budget_start_day(budget_start_day: int = Form(...), db: Session = Depends(get_db)):
    """"Début du mois budgétaire" (Préférences): the day the budget month
    starts on. Saved as soon as it is picked."""
    if budget_start_day not in budget_month.BUDGET_START_DAYS:
        raise HTTPException(status_code=400, detail=_t("Jour de début invalide."))
    crud.get_cap_settings(db).budget_start_day = budget_start_day
    db.commit()
    return HTMLResponse(content=flash_html("success", _t("Réglage enregistré")))


@app.post("/settings/delete-all-transactions", response_class=HTMLResponse)
def delete_all_transactions(
    request: Request, confirm: str = Form(""), db: Session = Depends(get_db)
):
    """"Zone sensible": deletes every transaction. Administrator only, and
    only after the second confirmation of the screen (the `confirm` field is
    sent by its "Oui, tout supprimer" button alone)."""
    current_user = auth.get_current_user(request)
    if auth.AUTH_ENABLED and (current_user is None or current_user.role != "admin"):
        raise HTTPException(status_code=403, detail=_t("Réservé à l'administrateur."))
    if confirm != "yes":
        raise HTTPException(status_code=400, detail=_t("Confirmation manquante."))
    count = crud.delete_all_transactions(db)
    message = ngettext("%(n)s opération supprimée", "%(n)s opérations supprimées", count) % {"n": count}
    return HTMLResponse(content=flash_html("success", message))


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
    return HTMLResponse(content=flash_html("success", _t("Réglage enregistré")))


@app.post("/settings/detect-payment-methods", response_class=HTMLResponse)
def detect_payment_methods(db: Session = Depends(get_db)):
    updated_count = crud.detect_missing_payment_methods(db)
    message = ngettext("%(n)s transaction mise à jour", "%(n)s transactions mises à jour", updated_count) % {
        "n": updated_count
    }
    return HTMLResponse(content=flash_html("success", message))


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
    def error(message: str) -> str:
        return flash_html("error", message)

    current_user = auth.get_current_user(request)
    if not auth.AUTH_ENABLED or current_user is None:
        return HTMLResponse(error(_t("Authentification désactivée.")), status_code=400)
    if auth.verify_password(db, current_user.username, current_password) is None:
        return HTMLResponse(error(_t("Mot de passe actuel incorrect.")), status_code=401)
    if new_password != confirm_password:
        return HTMLResponse(error(_t("Les nouveaux mots de passe ne correspondent pas.")), status_code=400)
    if len(new_password) < 8:
        return HTMLResponse(error(_t("Le nouveau mot de passe doit faire au moins 8 caractères.")), status_code=400)

    crud.set_user_password(db, current_user.id, new_password)
    db.refresh(current_user)

    # Le jeton de session embarque une empreinte du mot de passe (voir
    # backend/auth.py, authenticate_request) : changer le mot de passe
    # invalide donc le cookie actuel, on en réémet un nouveau tout de suite
    # pour ne pas déconnecter l'utilisateur qui vient de changer le sien.
    response = HTMLResponse(flash_html("success", _t("Mot de passe modifié.")))
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
