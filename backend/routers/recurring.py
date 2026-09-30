from decimal import Decimal

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from backend import crud
from backend.database import get_db
from backend.templating import templates

router = APIRouter(prefix="/recurring", tags=["recurring"])


def _build_context(db: Session) -> dict:
    return {
        **crud.get_recurring_patterns_overview(db),
        "payment_methods": crud.get_payment_methods_dict(db),
    }


@router.get("", response_class=HTMLResponse)
def recurring_page(request: Request, db: Session = Depends(get_db)):
    context = {"request": request, **_build_context(db)}
    return templates.TemplateResponse("recurring/index.html", context)


@router.get("/content", response_class=HTMLResponse)
def recurring_content(request: Request, db: Session = Depends(get_db)):
    context = {"request": request, **_build_context(db)}
    return templates.TemplateResponse("recurring/_content.html", context)


def _set_status(
    request: Request,
    db: Session,
    label_pattern: str,
    amount: str,
    frequency_days: int,
    category_id: str,
    status: str,
):
    crud.set_recurring_pattern_status(
        db,
        label_pattern=label_pattern,
        amount=Decimal(amount),
        frequency_days=frequency_days,
        category_id=int(category_id) if category_id else None,
        status=status,
    )
    context = {"request": request, **_build_context(db)}
    return templates.TemplateResponse("recurring/_content.html", context)


@router.post("/confirm", response_class=HTMLResponse)
def confirm_pattern(
    request: Request,
    label_pattern: str = Form(...),
    amount: str = Form(...),
    frequency_days: int = Form(...),
    category_id: str = Form(""),
    db: Session = Depends(get_db),
):
    return _set_status(request, db, label_pattern, amount, frequency_days, category_id, "confirmed")


@router.post("/ignore", response_class=HTMLResponse)
def ignore_pattern(
    request: Request,
    label_pattern: str = Form(...),
    amount: str = Form(...),
    frequency_days: int = Form(...),
    category_id: str = Form(""),
    db: Session = Depends(get_db),
):
    return _set_status(request, db, label_pattern, amount, frequency_days, category_id, "ignored")


@router.post("/merge", response_class=HTMLResponse)
def merge_patterns(
    request: Request,
    label_pattern: list[str] = Form(...),
    amount: str = Form(...),
    frequency_days: int = Form(...),
    category_id: str = Form(""),
    db: Session = Depends(get_db),
):
    crud.merge_recurring_patterns(
        db,
        label_patterns=label_pattern,
        amount=Decimal(amount),
        frequency_days=frequency_days,
        category_id=int(category_id) if category_id else None,
    )
    context = {"request": request, **_build_context(db)}
    return templates.TemplateResponse("recurring/_content.html", context)
