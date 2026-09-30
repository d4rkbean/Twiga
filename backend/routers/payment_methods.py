from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import PaymentMethod
from backend.templating import templates

router = APIRouter(prefix="/payment-methods", tags=["payment-methods"])


@router.get("", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    methods = db.execute(select(PaymentMethod).order_by(PaymentMethod.display_order)).scalars().all()
    return templates.TemplateResponse("payment_methods/index.html", {"request": request, "methods": methods})


@router.post("/create")
def create(name: str = Form(...), icon: str = Form("💳"), db: Session = Depends(get_db)):
    if name.strip():
        db.add(PaymentMethod(name=name.strip(), icon=icon.strip() or "💳"))
        db.commit()
    return RedirectResponse("/payment-methods", status_code=303)


@router.post("/{method_id}/update")
def update(method_id: int, name: str = Form(...), icon: str = Form(...), db: Session = Depends(get_db)):
    pm = db.get(PaymentMethod, method_id)
    if pm and name.strip():
        pm.name = name.strip()
        pm.icon = icon.strip() or pm.icon
        db.commit()
    return RedirectResponse("/payment-methods", status_code=303)


@router.post("/{method_id}/delete")
def delete(method_id: int, db: Session = Depends(get_db)):
    pm = db.get(PaymentMethod, method_id)
    if pm:
        db.delete(pm)
        db.commit()
    return RedirectResponse("/payment-methods", status_code=303)
