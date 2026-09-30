from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from backend import crud
from backend.database import get_db
from backend.models import Category
from backend.templating import templates

router = APIRouter(prefix="/categories", tags=["categories"])


def _content_context(db: Session) -> dict:
    return {"categories": crud.get_categories_tree(db)}


@router.get("", response_class=HTMLResponse)
def categories_page(request: Request, db: Session = Depends(get_db)):
    context = {"request": request, **_content_context(db)}
    return templates.TemplateResponse("categories/index.html", context)


@router.get("/content", response_class=HTMLResponse)
def categories_content(request: Request, db: Session = Depends(get_db)):
    context = {"request": request, **_content_context(db)}
    return templates.TemplateResponse("categories/_content.html", context)


@router.post("/create", response_class=HTMLResponse)
def create_category(
    request: Request,
    name: str = Form(...),
    parent_id: str = Form(""),
    db: Session = Depends(get_db),
):
    parent = db.get(Category, int(parent_id)) if parent_id else None
    if name.strip():
        crud.create_category(db, name.strip(), parent)
    context = {"request": request, **_content_context(db)}
    return templates.TemplateResponse("categories/_content.html", context)


@router.get("/{category_id}/row", response_class=HTMLResponse)
def category_row(
    request: Request, category_id: int, is_child: bool = False, db: Session = Depends(get_db)
):
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Catégorie introuvable")
    context = {"request": request, "category": category, "is_child": is_child}
    return templates.TemplateResponse("categories/_row.html", context)


@router.get("/{category_id}/edit", response_class=HTMLResponse)
def edit_category_form(
    request: Request, category_id: int, is_child: bool = False, db: Session = Depends(get_db)
):
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Catégorie introuvable")
    context = {"request": request, "category": category, "is_child": is_child}
    return templates.TemplateResponse("categories/_row_edit.html", context)


@router.post("/{category_id}/update", response_class=HTMLResponse)
def update_category(
    request: Request,
    category_id: int,
    name: str = Form(...),
    db: Session = Depends(get_db),
):
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Catégorie introuvable")
    if name.strip():
        crud.update_category_name(db, category, name.strip())
    context = {"request": request, **_content_context(db)}
    return templates.TemplateResponse("categories/_content.html", context)


@router.post("/{category_id}/update-pillar", response_class=HTMLResponse)
def update_category_pillar(
    request: Request,
    category_id: int,
    pillar: str = Form(""),
    is_child: bool = False,
    db: Session = Depends(get_db),
):
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Catégorie introuvable")
    # "" (option "↳ Hériter du parent" / non défini) -> None, jamais une
    # chaîne vide stockée en base (voir Category.pillar / resolve_category_pillar).
    crud.update_category_pillar(db, category, pillar or None)
    context = {"request": request, "category": category, "is_child": is_child}
    return templates.TemplateResponse("categories/_row.html", context)


@router.post("/{category_id}/update-budget-exclusion", response_class=HTMLResponse)
def update_category_budget_exclusion(
    request: Request,
    category_id: int,
    excluded: bool = Form(False),
    is_child: bool = False,
    db: Session = Depends(get_db),
):
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Catégorie introuvable")
    crud.update_category_budget_exclusion(db, category, excluded)
    context = {"request": request, "category": category, "is_child": is_child}
    return templates.TemplateResponse("categories/_row.html", context)


@router.post("/reset-pillar-overrides", response_class=HTMLResponse)
def reset_pillar_overrides(request: Request, db: Session = Depends(get_db)):
    crud.reset_subcategory_pillar_overrides(db)
    context = {"request": request, **_content_context(db)}
    return templates.TemplateResponse("categories/_content.html", context)


@router.get("/{category_id}/delete-confirm", response_class=HTMLResponse)
def delete_confirm(
    request: Request, category_id: int, is_child: bool = False, db: Session = Depends(get_db)
):
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Catégorie introuvable")
    context = {
        "request": request,
        "category": category,
        "is_child": is_child,
        "usage": crud.get_category_usage(db, category_id),
        "all_categories": crud.get_categories_tree(db),
    }
    return templates.TemplateResponse("categories/_delete_confirm.html", context)


@router.post("/{category_id}/delete", response_class=HTMLResponse)
def delete_category(
    request: Request,
    category_id: int,
    reassign_to: str = Form(""),
    db: Session = Depends(get_db),
):
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Catégorie introuvable")

    usage = crud.get_category_usage(db, category_id)
    if usage["children"]:
        # Ne devrait pas arriver via l'UI normale (le bouton OK ramène juste
        # à l'affichage), mais on refuse quand même côté serveur par sécurité.
        context = {"request": request, **_content_context(db)}
        return templates.TemplateResponse("categories/_content.html", context)

    has_references = usage["transactions"] or usage["budgets"] or usage["rules"] or usage["recurring_patterns"]
    if has_references and reassign_to:
        crud.reassign_category_references(db, category_id, int(reassign_to))

    crud.delete_category(db, category)
    context = {"request": request, **_content_context(db)}
    return templates.TemplateResponse("categories/_content.html", context)


@router.get("/{parent_id}/add-subcategory-form", response_class=HTMLResponse)
def add_subcategory_form(request: Request, parent_id: int, db: Session = Depends(get_db)):
    parent = db.get(Category, parent_id)
    if parent is None:
        raise HTTPException(status_code=404, detail="Catégorie introuvable")
    context = {"request": request, "parent": parent}
    return templates.TemplateResponse("categories/_add_subcategory_form.html", context)


@router.get("/{parent_id}/add-subcategory-button", response_class=HTMLResponse)
def add_subcategory_button(request: Request, parent_id: int, db: Session = Depends(get_db)):
    parent = db.get(Category, parent_id)
    if parent is None:
        raise HTTPException(status_code=404, detail="Catégorie introuvable")
    context = {"request": request, "parent": parent}
    return templates.TemplateResponse("categories/_add_subcategory_button.html", context)
