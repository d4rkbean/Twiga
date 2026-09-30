from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from backend import crud
from backend.database import get_db
from backend.models import Account, Category, PendingCheck
from backend.templating import templates
from imports.common import parse_decimal_amount

router = APIRouter(prefix="/checks", tags=["checks"])


def _list_context(db: Session) -> dict:
    return {
        "outstanding_checks": crud.get_outstanding_pending_checks(db),
        "matched_checks": crud.get_matched_pending_checks(db),
    }


def _form_context(db: Session) -> dict:
    return {
        "parent_categories": crud.get_top_level_categories(db),
        "accounts": crud.list_accounts(db),
        "payment_methods": crud.get_payment_methods_dict(db),
    }


@router.get("", response_class=HTMLResponse)
def checks_page(request: Request, db: Session = Depends(get_db)):
    context = {"request": request, **_list_context(db), **_form_context(db)}
    return templates.TemplateResponse("checks/index.html", context)


@router.get("/list", response_class=HTMLResponse)
def checks_list(request: Request, db: Session = Depends(get_db)):
    context = {"request": request, **_list_context(db), **_form_context(db)}
    return templates.TemplateResponse("checks/_content.html", context)


@router.post("/create", response_class=HTMLResponse)
def create_check(
    request: Request,
    check_number: str = Form(""),
    payment_method: str = Form(""),
    amount: str = Form(...),
    issued_date: date = Form(...),
    category_id: str = Form(...),
    account_id: str = Form(...),
    recipient: str = Form(""),
    db: Session = Depends(get_db),
):
    category = db.get(Category, int(category_id)) if category_id else None
    if category is None:
        raise HTTPException(status_code=404, detail="Catégorie introuvable")
    account = db.get(Account, int(account_id)) if account_id else None
    if account is None:
        raise HTTPException(status_code=404, detail="Compte introuvable")

    # Une ancre de rapprochement est obligatoire (voir crud.match_pending_checks) :
    # soit un numéro de chèque, soit un moyen de paiement valide (Wero,
    # PayPal...) pour les autres paiements — jamais aucun des deux, sinon le
    # rapprochement automatique n'aurait rien de fiable sur quoi s'ancrer.
    valid_payment_method = payment_method if payment_method in crud.get_payment_methods_dict(db) else None
    if check_number.strip() or valid_payment_method:
        crud.create_pending_check(
            db,
            check_number=check_number or None,
            payment_method=valid_payment_method,
            amount=parse_decimal_amount(amount),
            issued_date=issued_date,
            category=category,
            account=account,
            recipient=recipient or None,
        )
    context = {"request": request, **_list_context(db), **_form_context(db)}
    return templates.TemplateResponse("checks/_content.html", context)


@router.post("/{check_id}/delete", response_class=HTMLResponse)
def delete_check(request: Request, check_id: int, db: Session = Depends(get_db)):
    pending_check = db.get(PendingCheck, check_id)
    if pending_check is None:
        raise HTTPException(status_code=404, detail="Chèque introuvable")
    crud.delete_pending_check(db, pending_check)
    context = {"request": request, **_list_context(db), **_form_context(db)}
    return templates.TemplateResponse("checks/_content.html", context)
