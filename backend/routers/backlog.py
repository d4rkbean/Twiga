import logging
import math
import time

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import crud
from backend.database import get_db
from backend.models import Category, Transaction
from backend.templating import templates
from backend.i18n import gettext as _t

logger = logging.getLogger("backend.backlog")

router = APIRouter(prefix="/backlog", tags=["backlog"])

PAGE_SIZE = 50

# Cache en mémoire du process (app mono-utilisateur, un seul worker uvicorn) :
# calculer la similarité de TOUTES les transactions en attente contre TOUT
# l'historique catégorisé est le calcul coûteux de cette fonctionnalité. Le
# refaire à chaque clic ✓/✗ (juste pour retirer UNE ligne et réafficher la
# liste) le rendait inutilement lent. On le calcule une fois, puis chaque
# action retire simplement l'élément traité de la liste déjà en mémoire.
# `_cache["count"]` sert de détecteur de péremption bon marché : s'il ne
# correspond plus au compte réel en base (nouvel import, transaction modifiée
# ailleurs que via cette page...), le cache est invalidé et reconstruit.
_cache: dict = {"items": None, "count": None}


def _build_items(db: Session) -> list[dict]:
    # Le cache ne garde QUE des données déjà extraites (pas d'objets ORM
    # vivants) : les objets SQLAlchemy sont liés à la Session de LA requête
    # qui les a chargés, or ce cache survit entre requêtes (chacune avec sa
    # propre Session) — garder un Transaction/Category "détaché" exposerait
    # à un DetachedInstanceError au moindre accès à un attribut non déjà
    # chargé une fois la Session d'origine fermée.
    pending = crud.get_backlog_transactions(db)
    samples = crud.get_categorized_label_samples(db)
    categories_by_id = {c.id: c for c in db.execute(select(Category)).scalars().all()}

    items = []
    for tx in pending:
        raw_suggestion = crud.suggest_backlog_category(tx, samples, categories_by_id)
        suggestion = None
        if raw_suggestion is not None:
            category = raw_suggestion["category"]
            suggestion = {
                "category_id": category.id,
                "category_name": category.name,
                "category_icon": category.icon,
                "based_on_label": raw_suggestion["based_on_label"],
                "confidence": raw_suggestion["confidence"],
            }
        items.append(
            {
                "transaction_id": tx.id,
                "date": tx.date,
                "label": tx.label,
                "account_name": tx.account.name,
                "amount": tx.amount,
                "suggestion": suggestion,
            }
        )
    items.sort(
        key=lambda item: item["suggestion"]["confidence"] if item["suggestion"] else -1,
        reverse=True,
    )
    return items


def _cached_items(db: Session) -> list[dict]:
    current_count = crud.count_backlog_transactions(db)
    if _cache["items"] is None or _cache["count"] != current_count:
        # Chemin coûteux (score de similarité de chaque transaction en
        # attente contre tout l'historique) : ne doit s'exécuter qu'au tout
        # premier accès, ou quand quelque chose a changé le backlog sans
        # passer par _remove_from_cache (import, édition ailleurs...). S'il
        # apparaît dans les logs à CHAQUE clic, le cache n'est pas actif —
        # le plus souvent parce que l'image Docker n'a pas été reconstruite.
        started = time.monotonic()
        _cache["items"] = _build_items(db)
        _cache["count"] = len(_cache["items"])
        logger.info(
            "backlog: reconstruction complète du cache (%d transactions) en %.2fs",
            _cache["count"],
            time.monotonic() - started,
        )
    return _cache["items"]


def _remove_from_cache(transaction_ids: set[int]) -> None:
    if _cache["items"] is None:
        return
    _cache["items"] = [
        item for item in _cache["items"] if item["transaction_id"] not in transaction_ids
    ]
    _cache["count"] = len(_cache["items"])


def _apply_filters(items: list[dict], search: str, suggestion_filter: str) -> list[dict]:
    filtered = items
    needle = search.strip().lower()
    if needle:
        filtered = [item for item in filtered if needle in item["label"].lower()]
    if suggestion_filter == "none":
        filtered = [item for item in filtered if item["suggestion"] is None]
    elif suggestion_filter == "high":
        filtered = [
            item
            for item in filtered
            if item["suggestion"] is not None and item["suggestion"]["confidence"] > 90
        ]
    return filtered


def _build_page_context(
    db: Session, page: int, search: str = "", suggestion_filter: str = "all"
) -> dict:
    all_items = _cached_items(db)
    filtered_items = _apply_filters(all_items, search, suggestion_filter)
    total = len(filtered_items)
    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    page = max(1, min(page, total_pages))
    start = (page - 1) * PAGE_SIZE
    return {
        "items": filtered_items[start : start + PAGE_SIZE],
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "parent_categories": crud.get_top_level_categories(db),
        "search": search,
        "suggestion_filter": suggestion_filter,
        "payment_methods": crud.get_payment_methods_dict(db),
    }


def _content_response(
    request: Request,
    db: Session,
    page: int,
    rule_suggestions: list[dict] | None = None,
    search: str = "",
    suggestion_filter: str = "all",
):
    context = _build_page_context(db, page, search=search, suggestion_filter=suggestion_filter)
    context["request"] = request
    context["rule_suggestions"] = rule_suggestions or []
    return templates.TemplateResponse("backlog/_content.html", context)


def _dedupe_rule_suggestions(suggestions: list[dict]) -> list[dict]:
    seen: set[tuple[str, int]] = set()
    deduped = []
    for suggestion in suggestions:
        key = (suggestion["keyword"].strip().lower(), suggestion["category_id"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(suggestion)
    return deduped


@router.get("", response_class=HTMLResponse)
def backlog_page(
    request: Request,
    page: int = 1,
    search: str = "",
    suggestion_filter: str = "all",
    db: Session = Depends(get_db),
):
    context = _build_page_context(db, page, search=search, suggestion_filter=suggestion_filter)
    context["request"] = request
    context["rule_suggestions"] = []
    return templates.TemplateResponse("backlog/index.html", context)


@router.get("/content", response_class=HTMLResponse)
def backlog_content(
    request: Request,
    page: int = 1,
    search: str = "",
    suggestion_filter: str = "all",
    db: Session = Depends(get_db),
):
    return _content_response(request, db, page, search=search, suggestion_filter=suggestion_filter)


@router.get("/{transaction_id}/category-select", response_class=HTMLResponse)
def category_select(
    request: Request, transaction_id: int, page: int = 1, db: Session = Depends(get_db)
):
    transaction = db.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=404, detail=_t("Transaction introuvable"))
    context = {
        "request": request,
        "transaction": transaction,
        "categories": crud.get_top_level_categories(db),
        "page": page,
    }
    return templates.TemplateResponse("backlog/_category_select.html", context)


@router.get("/{transaction_id}/category-confirm", response_class=HTMLResponse)
def category_confirm(
    request: Request,
    transaction_id: int,
    category_id: int,
    page: int = 1,
    db: Session = Depends(get_db),
):
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail=_t("Catégorie introuvable"))
    context = {
        "request": request,
        "transaction_id": transaction_id,
        "category": category,
        "page": page,
    }
    return templates.TemplateResponse("backlog/_category_confirm.html", context)


@router.post("/{transaction_id}/validate", response_class=HTMLResponse)
def validate_suggestion(
    request: Request,
    transaction_id: int,
    category_id: int = Form(...),
    page: int = Form(1),
    search: str = Form(""),
    suggestion_filter: str = Form("all"),
    db: Session = Depends(get_db),
):
    transaction = db.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=404, detail=_t("Transaction introuvable"))
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail=_t("Catégorie introuvable"))

    rule_suggestion = crud.maybe_rule_suggestion(db, transaction, category)
    crud.categorize_transaction(db, transaction, category)
    _remove_from_cache({transaction_id})

    return _content_response(
        request,
        db,
        page,
        [rule_suggestion] if rule_suggestion else [],
        search=search,
        suggestion_filter=suggestion_filter,
    )


@router.post("/{transaction_id}/reject", response_class=HTMLResponse)
def reject_suggestion(
    request: Request,
    transaction_id: int,
    page: int = Form(1),
    search: str = Form(""),
    suggestion_filter: str = Form("all"),
    db: Session = Depends(get_db),
):
    transaction = db.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=404, detail=_t("Transaction introuvable"))

    crud.reject_from_backlog(db, transaction)
    _remove_from_cache({transaction_id})
    return _content_response(request, db, page, search=search, suggestion_filter=suggestion_filter)


@router.post("/bulk-validate", response_class=HTMLResponse)
def bulk_validate(
    request: Request,
    min_confidence: int = Form(90),
    page: int = Form(1),
    search: str = Form(""),
    suggestion_filter: str = Form("all"),
    db: Session = Depends(get_db),
):
    page_context = _build_page_context(db, page, search=search, suggestion_filter=suggestion_filter)
    rule_suggestions = []
    processed_ids: set[int] = set()
    for item in page_context["items"]:
        suggestion = item["suggestion"]
        if suggestion is None or suggestion["confidence"] <= min_confidence:
            continue
        transaction = db.get(Transaction, item["transaction_id"])
        category = db.get(Category, suggestion["category_id"])
        if transaction is None or category is None:
            continue
        maybe_rule = crud.maybe_rule_suggestion(db, transaction, category)
        crud.categorize_transaction(db, transaction, category)
        processed_ids.add(transaction.id)
        if maybe_rule:
            rule_suggestions.append(maybe_rule)

    _remove_from_cache(processed_ids)
    return _content_response(
        request,
        db,
        page,
        _dedupe_rule_suggestions(rule_suggestions),
        search=search,
        suggestion_filter=suggestion_filter,
    )


@router.post("/bulk-reject", response_class=HTMLResponse)
def bulk_reject(
    request: Request,
    max_confidence: int = Form(70),
    page: int = Form(1),
    search: str = Form(""),
    suggestion_filter: str = Form("all"),
    db: Session = Depends(get_db),
):
    page_context = _build_page_context(db, page, search=search, suggestion_filter=suggestion_filter)
    processed_ids: set[int] = set()
    for item in page_context["items"]:
        suggestion = item["suggestion"]
        if suggestion is not None and suggestion["confidence"] >= max_confidence:
            continue
        transaction = db.get(Transaction, item["transaction_id"])
        if transaction is None:
            continue
        crud.reject_from_backlog(db, transaction)
        processed_ids.add(item["transaction_id"])

    _remove_from_cache(processed_ids)
    return _content_response(request, db, page, search=search, suggestion_filter=suggestion_filter)


@router.post("/bulk-apply", response_class=HTMLResponse)
def bulk_apply(
    request: Request,
    selected_ids: list[int] | None = Form(None),
    category_id: str = Form(""),
    payment_method: str = Form(""),
    page: int = Form(1),
    search: str = Form(""),
    suggestion_filter: str = Form("all"),
    db: Session = Depends(get_db),
):
    category = db.get(Category, int(category_id)) if category_id else None
    payment = payment_method if payment_method in crud.get_payment_methods_dict(db) else None
    ids = selected_ids or []

    if not ids or (category is None and payment is None):
        # Rien à appliquer (aucune transaction cochée, ou ni catégorie ni
        # mode de paiement renseigné) : on réaffiche juste l'état actuel
        # plutôt que de planter, la sélection Alpine repart de zéro au
        # réaffichage. Catégorie et mode de paiement sont chacun facultatifs
        # et indépendants : appliquer uniquement l'un des deux doit marcher.
        return _content_response(request, db, page, search=search, suggestion_filter=suggestion_filter)

    transactions = [t for t in (db.get(Transaction, tid) for tid in ids) if t is not None]
    categorized_ids = crud.bulk_update_transactions(
        db, transactions, category=category, payment_method=payment
    )

    # Seules les transactions qui ont reçu une catégorie quittent le backlog
    # (elles ne sont plus "en attente") : un mode de paiement appliqué seul
    # laisse la transaction non catégorisée visible dans la liste.
    _remove_from_cache(set(categorized_ids))
    return _content_response(request, db, page, search=search, suggestion_filter=suggestion_filter)


@router.post("/create-rule", response_class=HTMLResponse)
def create_rule_from_suggestion(
    keyword: str = Form(...), category_id: int = Form(...), db: Session = Depends(get_db)
):
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail=_t("Catégorie introuvable"))
    if keyword.strip():
        crud.create_rule(db, keyword.strip(), category)
    return HTMLResponse(content=_t('<p class="text-sm text-success py-2">✓ Règle créée</p>'))
