from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from backend import crud
from backend.database import get_db
from backend.models import Project
from backend.templating import templates
from imports.common import ImportParseError, parse_decimal_amount

router = APIRouter(prefix="/projects", tags=["projects"])


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
        items.append(
            {
                "project": project,
                "monthly_effort": monthly_effort,
                "percentage_display": round(percentage),
                "bar_width": max(0, min(round(percentage), 100)),
                "movements": crud.get_project_movements(db, project.id),
            }
        )

    return {"items": items}


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
        raise HTTPException(status_code=404, detail="Projet introuvable")

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
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Projet introuvable")

    crud.add_project_funds(db, project, _parse_positive_amount(amount), note.strip() or None)
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
        raise HTTPException(status_code=404, detail="Projet introuvable")

    crud.spend_project_funds(db, project, _parse_positive_amount(amount), note.strip() or None)
    context = {"request": request, **_build_context(db)}
    return templates.TemplateResponse("projects/_list.html", context)


@router.post("/{project_id}/delete", response_class=HTMLResponse)
def delete_project(request: Request, project_id: int, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Projet introuvable")

    crud.delete_project(db, project)
    context = {"request": request, **_build_context(db)}
    return templates.TemplateResponse("projects/_list.html", context)
