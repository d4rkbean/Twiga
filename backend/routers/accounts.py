from decimal import Decimal

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from backend import crud
from backend.database import get_db
from backend.models import Account
from backend.templating import templates
from imports.common import ImportParseError, parse_decimal_amount

router = APIRouter(prefix="/accounts", tags=["accounts"])


def _parse_balance(raw: str) -> Decimal:
    try:
        return parse_decimal_amount(raw)
    except ImportParseError:
        return Decimal("0.00")


def _content_context(db: Session) -> dict:
    return {"items": crud.get_accounts_overview(db)}


@router.get("", response_class=HTMLResponse)
def accounts_page(request: Request, db: Session = Depends(get_db)):
    context = {
        "request": request,
        "suspicious": crud.get_suspicious_transactions(db),
        **_content_context(db),
    }
    return templates.TemplateResponse("accounts/index.html", context)


@router.get("/suspicious", response_class=HTMLResponse)
def suspicious_content(request: Request, db: Session = Depends(get_db)):
    context = {"request": request, "suspicious": crud.get_suspicious_transactions(db)}
    return templates.TemplateResponse("accounts/_suspicious.html", context)


@router.get("/content", response_class=HTMLResponse)
def accounts_content(request: Request, db: Session = Depends(get_db)):
    context = {"request": request, **_content_context(db)}
    return templates.TemplateResponse("accounts/_content.html", context)


@router.post("/create", response_class=HTMLResponse)
def create_account(
    request: Request,
    name: str = Form(...),
    type: str = Form("autre"),
    initial_balance: str = Form("0"),
    currency: str = Form("EUR"),
    color: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    if name.strip():
        crud.create_account(
            db,
            name=name.strip(),
            type=type,
            initial_balance=_parse_balance(initial_balance),
            currency=currency.strip().upper() or "EUR",
            color=color.strip() or None,
            notes=notes.strip() or None,
        )
    context = {"request": request, **_content_context(db)}
    return templates.TemplateResponse("accounts/_content.html", context)


@router.get("/{account_id}/row", response_class=HTMLResponse)
def account_row(request: Request, account_id: int, db: Session = Depends(get_db)):
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Compte introuvable")
    item = next((i for i in crud.get_accounts_overview(db) if i["account"].id == account_id), None)
    context = {"request": request, "item": item}
    return templates.TemplateResponse("accounts/_row.html", context)


@router.get("/{account_id}/edit", response_class=HTMLResponse)
def edit_account_form(request: Request, account_id: int, db: Session = Depends(get_db)):
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Compte introuvable")
    context = {"request": request, "account": account}
    return templates.TemplateResponse("accounts/_row_edit.html", context)


@router.post("/{account_id}/update", response_class=HTMLResponse)
def update_account(
    request: Request,
    account_id: int,
    name: str = Form(...),
    type: str = Form("autre"),
    initial_balance: str = Form("0"),
    color: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Compte introuvable")
    if name.strip():
        crud.update_account(
            db,
            account,
            name=name.strip(),
            type=type,
            initial_balance=_parse_balance(initial_balance),
            color=color.strip() or None,
            notes=notes.strip() or None,
        )
    context = {"request": request, **_content_context(db)}
    return templates.TemplateResponse("accounts/_content.html", context)


@router.get("/{account_id}/delete-confirm", response_class=HTMLResponse)
def delete_confirm(request: Request, account_id: int, db: Session = Depends(get_db)):
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Compte introuvable")
    transaction_count = crud.get_account_transaction_count(db, account_id)
    context = {"request": request, "account": account, "transaction_count": transaction_count}
    return templates.TemplateResponse("accounts/_delete_confirm.html", context)


@router.post("/{account_id}/delete", response_class=HTMLResponse)
def delete_account(request: Request, account_id: int, db: Session = Depends(get_db)):
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Compte introuvable")

    if crud.get_account_transaction_count(db, account_id) == 0:
        crud.delete_account(db, account)

    context = {"request": request, **_content_context(db)}
    return templates.TemplateResponse("accounts/_content.html", context)


def _detect_transfers_context(db: Session) -> dict:
    pairs = crud.detect_transfer_matches(db)
    items = []
    for tx_a, tx_b in pairs:
        negative, positive = (tx_a, tx_b) if tx_a.amount < 0 else (tx_b, tx_a)
        items.append({"negative": negative, "positive": positive})
    return {"pairs": items}


@router.get("/detect-transfers", response_class=HTMLResponse)
def detect_transfers_page(request: Request, db: Session = Depends(get_db)):
    context = {"request": request, **_detect_transfers_context(db)}
    return templates.TemplateResponse("accounts/_detect_transfers.html", context)


@router.get("/detect-transfers/content", response_class=HTMLResponse)
def detect_transfers_content(request: Request, db: Session = Depends(get_db)):
    context = {"request": request, **_detect_transfers_context(db)}
    return templates.TemplateResponse("accounts/_detect_transfers_content.html", context)


@router.post("/detect-transfers/confirm", response_class=HTMLResponse)
def confirm_transfer(
    request: Request,
    tx_a_id: int = Form(...),
    tx_b_id: int = Form(...),
    db: Session = Depends(get_db),
):
    crud.confirm_transfer_pair_by_ids(db, tx_a_id, tx_b_id)
    context = {"request": request, **_detect_transfers_context(db)}
    return templates.TemplateResponse("accounts/_detect_transfers_content.html", context)


@router.post("/detect-transfers/confirm-all", response_class=HTMLResponse)
def confirm_all_transfers(request: Request, db: Session = Depends(get_db)):
    crud.auto_tag_transfers(db)
    context = {"request": request, **_detect_transfers_context(db)}
    return templates.TemplateResponse("accounts/_detect_transfers_content.html", context)
