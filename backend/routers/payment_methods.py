from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import answers, crud
from backend.database import get_db
from backend.models import PaymentMethod
from backend.payment_methods import PICKER_ICONS, detection_examples, refresh_chosen_icons
from backend.templating import templates

router = APIRouter(prefix="/payment-methods", tags=["payment-methods"])


def _head_context(db: Session) -> dict:
    """The other way's sentence and the explanation of the detection; Classic ignores them."""
    methods = db.execute(select(PaymentMethod).order_by(PaymentMethod.display_order)).scalars().all()
    missing = crud.count_transactions_without_payment_method(db)
    return {
        "methods": methods,
        "missing": missing,
        "answer": answers.payments_answer(len(methods), missing),
        "examples": detection_examples(),
    }


@router.get("", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    context = {"request": request, "picker_icons": PICKER_ICONS, **_head_context(db)}
    return templates.TemplateResponse("payment_methods/index.html", context)


@router.get("/head", response_class=HTMLResponse)
def head(request: Request, db: Session = Depends(get_db)):
    """The sentence and the main action of the other way's page, refreshed after a detection."""
    return templates.TemplateResponse("other_way/payment_methods/_head.html", {"request": request, **_head_context(db)})


@router.post("/create")
def create(name: str = Form(...), icon: str = Form("credit-card"), db: Session = Depends(get_db)):
    if name.strip():
        db.add(PaymentMethod(name=name.strip(), icon=icon if icon in PICKER_ICONS else PICKER_ICONS[0]))
        db.commit()
        refresh_chosen_icons()
    return RedirectResponse("/payment-methods", status_code=303)


@router.post("/{method_id}/update")
def update(method_id: int, name: str = Form(...), icon: str = Form(...), db: Session = Depends(get_db)):
    pm = db.get(PaymentMethod, method_id)
    if pm and name.strip():
        pm.name = name.strip()
        if icon in PICKER_ICONS:
            pm.icon = icon
        db.commit()
        refresh_chosen_icons()
    return RedirectResponse("/payment-methods", status_code=303)


@router.post("/{method_id}/delete")
def delete(method_id: int, db: Session = Depends(get_db)):
    pm = db.get(PaymentMethod, method_id)
    if pm:
        db.delete(pm)
        db.commit()
        refresh_chosen_icons()
    return RedirectResponse("/payment-methods", status_code=303)
