from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from backend import crud
from backend.database import get_db
from backend.dates import month_label
from backend.models import Account, Project
from backend.templating import templates
from imports.common import ImportParseError, parse_decimal_amount
from backend.i18n import current_language, gettext as _t

router = APIRouter(prefix="/projects", tags=["projects"])


def _month_text(value: date) -> str:
    """"juin 2027" in French (lowercase mid-sentence), "June 2027" in English."""
    label = month_label(value.year, value.month)
    return label.lower() if current_language() == "fr" else label


def _parse_positive_amount(raw: str) -> Decimal:
    try:
        return abs(parse_decimal_amount(raw))
    except ImportParseError:
        return Decimal("0.00")


def _build_context(db: Session) -> dict:
    projects = crud.list_projects(db)
    today = date.today()

    items = []
    for project in projects:
        monthly_effort = crud.compute_monthly_effort(
            project.target_amount, project.current_amount, project.target_date, today
        )
        percentage = (
            min(project.current_amount / project.target_amount * 100, Decimal("100"))
            if project.target_amount
            else Decimal("0")
        )
        effort = crud.compute_project_effort(db, project.id, today)
        rhythm = crud.project_rhythm(
            project.target_amount, project.current_amount, project.target_date, effort, today
        )
        if rhythm["reach"] is not None:
            rhythm["reach_label"] = _month_text(rhythm["reach"])
        items.append(
            {
                "project": project,
                "monthly_effort": monthly_effort,
                "effort": effort,
                "rhythm": rhythm,
                "deadline_label": _month_text(project.target_date),
                "percentage_display": round(percentage),
                "bar_width": max(0, min(round(percentage), 100)),
                "movements": crud.get_project_movements(db, project.id),
            }
        )

    late = next((item for item in items if item["rhythm"]["state"] == "late"), None)
    return {
        "items": items,
        "late": late,
        "accounts": crud.list_accounts(db),
        "deadline_options": _deadline_options(today),
    }


def _deadline_options(today: date) -> list[dict]:
    """The next 48 months, as first-of-month dates (the form's "Date cible")."""
    options = []
    for offset in range(1, 49):
        index = today.year * 12 + today.month - 1 + offset
        year, month = index // 12, index % 12 + 1
        options.append({"value": date(year, month, 1).isoformat(), "label": month_label(year, month)})
    return options


@router.get("", response_class=HTMLResponse)
def projects_page(request: Request, db: Session = Depends(get_db)):
    context = {"request": request, **_build_context(db)}
    return templates.TemplateResponse("projects/index.html", context)


@router.post("/create", response_class=HTMLResponse)
def create_project(
    request: Request,
    name: str = Form(...),
    target_amount: str = Form(...),
    target_date: str = Form(...),
    current_amount: str = Form(""),
    db: Session = Depends(get_db),
):
    crud.create_project(
        db,
        name=name.strip(),
        target_amount=_parse_positive_amount(target_amount),
        target_date=date.fromisoformat(target_date),
        current_amount=_parse_positive_amount(current_amount),
    )
    context = {"request": request, **_build_context(db)}
    return templates.TemplateResponse("projects/_list.html", context)


@router.post("/{project_id}/update", response_class=HTMLResponse)
def update_project(
    request: Request,
    project_id: int,
    name: str = Form(...),
    target_amount: str = Form(...),
    target_date: str = Form(...),
    current_amount: str = Form(""),
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=_t("Projet introuvable"))

    crud.update_project(
        db,
        project,
        name=name.strip(),
        target_amount=_parse_positive_amount(target_amount),
        target_date=date.fromisoformat(target_date),
        current_amount=_parse_positive_amount(current_amount),
    )
    context = {"request": request, **_build_context(db)}
    return templates.TemplateResponse("projects/_list.html", context)


@router.post("/{project_id}/add", response_class=HTMLResponse)
def add_funds(
    request: Request,
    project_id: int,
    amount: str = Form(...),
    note: str = Form(""),
    account_id: str = Form(""),
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=_t("Projet introuvable"))

    value = _parse_positive_amount(amount)
    account = db.get(Account, int(account_id)) if account_id.isdigit() else None
    if value > 0:
        crud.add_project_funds(db, project, value, note.strip() or None, account.id if account else None)
    context = {"request": request, **_build_context(db)}
    return templates.TemplateResponse("projects/_list.html", context)


@router.post("/{project_id}/spend", response_class=HTMLResponse)
def spend_funds(
    request: Request,
    project_id: int,
    amount: str = Form(...),
    note: str = Form(""),
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=_t("Projet introuvable"))

    value = _parse_positive_amount(amount)
    if 0 < value <= project.current_amount:
        crud.spend_project_funds(db, project, value, note.strip() or None)
    context = {"request": request, **_build_context(db)}
    return templates.TemplateResponse("projects/_list.html", context)


@router.post("/{project_id}/delete", response_class=HTMLResponse)
def delete_project(request: Request, project_id: int, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=_t("Projet introuvable"))

    crud.delete_project(db, project)
    context = {"request": request, **_build_context(db)}
    return templates.TemplateResponse("projects/_list.html", context)
