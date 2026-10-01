from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from backend import crud
from backend.database import get_db
from backend.models import Category, Rule
from backend.receipt_families import RECEIPT_FAMILIES
from backend.templating import templates
from backend.i18n import gettext as _t

router = APIRouter(prefix="/rules", tags=["rules"])


def _list_context(db: Session) -> dict:
    return {
        "rules_with_usage": crud.get_rules_with_usage(db),
        "payment_methods": crud.get_payment_methods_dict(db),
        "receipt_families": RECEIPT_FAMILIES,
        # Propositions faites au fil des catégorisations et jamais traitées.
        # Elles n'avaient aucun endroit où être retrouvées : affichées une
        # fois, perdues ensuite — et en catégorisation de masse, elles
        # arrivaient plus vite qu'on ne pouvait les valider.
        "pending_suggestions": crud.list_pending_rule_suggestions(db),
    }


def _form_context(db: Session) -> dict:
    return {"parent_categories": crud.get_top_level_categories(db), "receipt_families": RECEIPT_FAMILIES}


@router.post("/suggestions/{suggestion_id}/dismiss", response_class=HTMLResponse)
def dismiss_suggestion(request: Request, suggestion_id: int, db: Session = Depends(get_db)):
    """Refus mémorisé : la proposition ne reviendra plus (voir RuleSuggestion)."""
    crud.dismiss_rule_suggestion(db, suggestion_id)
    context = {"request": request, **_list_context(db)}
    return templates.TemplateResponse("rules/_content.html", context)


@router.get("", response_class=HTMLResponse)
def rules_page(request: Request, db: Session = Depends(get_db)):
    context = {"request": request, **_list_context(db), **_form_context(db)}
    return templates.TemplateResponse("rules/index.html", context)


@router.get("/list", response_class=HTMLResponse)
def rules_list(request: Request, db: Session = Depends(get_db)):
    context = {"request": request, **_list_context(db)}
    return templates.TemplateResponse("rules/_content.html", context)


@router.post("/create", response_class=HTMLResponse)
def create_rule(
    request: Request,
    keyword: str = Form(...),
    category_id: str = Form(...),
    payment_method: str = Form(""),
    receipt_family: str = Form(""),
    db: Session = Depends(get_db),
):
    category = db.get(Category, int(category_id)) if category_id else None
    if category is None:
        raise HTTPException(status_code=404, detail=_t("Catégorie introuvable"))
    if keyword.strip():
        crud.create_rule(
            db,
            keyword.strip(),
            category,
            payment_method=payment_method or None,
            receipt_family=receipt_family or None,
        )
    context = {"request": request, **_list_context(db)}
    return templates.TemplateResponse("rules/_content.html", context)


@router.get("/{rule_id}/row", response_class=HTMLResponse)
def rule_row(request: Request, rule_id: int, db: Session = Depends(get_db)):
    rule = db.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail=_t("Règle introuvable"))
    usage_count = next(
        (item["usage_count"] for item in crud.get_rules_with_usage(db) if item["rule"].id == rule_id),
        0,
    )
    context = {
        "request": request,
        "rule": rule,
        "usage_count": usage_count,
        "payment_methods": crud.get_payment_methods_dict(db),
    }
    return templates.TemplateResponse("rules/_row.html", context)


@router.get("/{rule_id}/edit", response_class=HTMLResponse)
def edit_rule_form(request: Request, rule_id: int, db: Session = Depends(get_db)):
    rule = db.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail=_t("Règle introuvable"))
    current_parent = crud.resolve_top_level_category(rule.category)
    subcategories = crud.get_child_categories(db, current_parent.id) if current_parent else []
    context = {
        "request": request,
        "rule": rule,
        "parent_categories": crud.get_top_level_categories(db),
        "current_parent_id": current_parent.id if current_parent else None,
        "parent": current_parent,
        "subcategories": subcategories,
        "selected_category_id": rule.category_id,
        "payment_methods": crud.get_payment_methods_dict(db),
        "receipt_families": RECEIPT_FAMILIES,
    }
    return templates.TemplateResponse("rules/_row_edit.html", context)


@router.post("/{rule_id}/update", response_class=HTMLResponse)
def update_rule(
    request: Request,
    rule_id: int,
    keyword: str = Form(...),
    category_id: str = Form(...),
    payment_method: str = Form(""),
    receipt_family: str = Form(""),
    db: Session = Depends(get_db),
):
    rule = db.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail=_t("Règle introuvable"))
    category = db.get(Category, int(category_id)) if category_id else None
    if category is None:
        raise HTTPException(status_code=404, detail=_t("Catégorie introuvable"))
    crud.update_rule(
        db,
        rule,
        keyword.strip(),
        category,
        payment_method=payment_method or None,
        receipt_family=receipt_family or None,
    )

    # Ré-affiche toute la liste (pas juste la ligne) : changer le mot-clé
    # peut changer le compte d'utilisation de la règle, donc potentiellement
    # sa place dans le tri "plus utilisées d'abord".
    context = {"request": request, **_list_context(db)}
    return templates.TemplateResponse("rules/_content.html", context)


@router.post("/{rule_id}/delete", response_class=HTMLResponse)
def delete_rule(request: Request, rule_id: int, db: Session = Depends(get_db)):
    rule = db.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail=_t("Règle introuvable"))
    crud.delete_rule(db, rule)
    context = {"request": request, **_list_context(db)}
    return templates.TemplateResponse("rules/_content.html", context)


@router.post("/test", response_class=HTMLResponse)
def test_rule(request: Request, label: str = Form(""), db: Session = Depends(get_db)):
    matched_rule = crud.find_matching_rule(db, label) if label.strip() else None
    context = {"request": request, "tested_label": label.strip(), "matched_rule": matched_rule}
    return templates.TemplateResponse("rules/_test_result.html", context)
