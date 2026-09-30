import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from backend import crud
from backend.database import get_db
from backend.dates import month_label, month_range
from backend.models import Account, Category, Transaction
from backend.receipt_families import RECEIPT_FAMILIES, group_items_by_family
from backend.templating import templates
from imports.common import ImportParseError, parse_decimal_amount

router = APIRouter(prefix="/transactions", tags=["transactions"])


def _parse_history(history: str | None) -> list[int]:
    if not history:
        return []
    return [int(chunk) for chunk in history.split(",") if chunk.strip().isdigit()]


def _history_csv(ids: list[int]) -> str:
    return ",".join(str(i) for i in ids)


def _giraffe_scale(pending_count: int) -> float:
    # Twiga grandit visuellement à mesure que La Savane se vide : purement
    # cosmétique, recalculé à chaque affichage à partir du nombre
    # d'opérations en attente — aucun état à retenir, aucune migration.
    cap = 20
    progress = 1 - min(pending_count, cap) / cap
    return round(0.6 + progress * 0.8, 2)


def _build_card_context(db: Session, transaction: Transaction | None) -> dict:
    if transaction is None:
        return {"transaction": None}

    # Fusion avec la catégorisation de masse : même moteur de suggestion
    # (règle explicite en priorité, sinon similarité floue avec l'historique
    # déjà catégorisé), avec son score de fiabilité affiché sur la carte —
    # voir crud.suggest_category_with_confidence.
    suggestion = crud.suggest_category_with_confidence(db, transaction)
    suggested_category = suggestion["category"] if suggestion else None

    context = {
        "transaction": transaction,
        "suggested_category": suggested_category,
        "suggestion_confidence": suggestion["confidence"] if suggestion else None,
        "suggestion_based_on": suggestion["based_on_label"] if suggestion else None,
        "possible_transfer": (
            not transaction.is_transfer and crud.looks_like_transfer(transaction.raw_label)
        ),
    }
    if suggested_category is None:
        context["categories"] = crud.get_top_level_categories(db)
    return context


def _render_next_card(
    request: Request,
    db: Session,
    transaction: Transaction | None,
    history: list[int],
    just_categorized_id: int | None = None,
    rule_suggestion: dict | None = None,
):
    pending_count = crud.count_pending_transactions(db)
    context = {
        "request": request,
        "history": _history_csv(history),
        "pending_count": pending_count,
        "giraffe_scale": _giraffe_scale(pending_count),
        "oob": True,
        # Transaction qui vient d'être enregistrée (pas transaction, qui est
        # déjà la SUIVANTE ci-dessous) : cible du toast "🆘 Marquer comme
        # imprévu" (inbox/_unexpected_toast.html) — voir _categorize_and_advance.
        "just_categorized_id": just_categorized_id,
        # Même toast OOB "création de règle" que le backlog (voir
        # crud.maybe_rule_suggestion) : posé APRÈS enregistrement, sur la
        # transaction qui vient d'être catégorisée — pour qu'un commerçant
        # récurrent devienne une règle dès sa première rencontre plutôt que
        # de repasser indéfiniment par la suggestion floue, et que La Savane
        # reste quasi vide après quelques mois d'usage.
        "rule_suggestion": rule_suggestion,
        **_build_card_context(db, transaction),
    }
    return templates.TemplateResponse("inbox/_card_with_counter.html", context)


def _build_routine_banner_context(db: Session) -> dict:
    today = date.today()
    current_month_start = date(today.year, today.month, 1)

    state = crud.get_or_create_app_state(db)
    show_routine_banner = (
        state.last_routine_month is None or state.last_routine_month < current_month_start
    )
    if not show_routine_banner:
        return {"show_routine_banner": False}

    month_end = month_range(today.year, today.month)[1]
    budget_percent = crud.get_overall_budget_consumption(db, current_month_start, month_end)
    subscription_count = len(crud.detect_subscriptions(db, today))
    project_savings = crud.get_monthly_project_savings(db, current_month_start, month_end)

    return {
        "show_routine_banner": True,
        "routine_month_label": month_label(today.year, today.month),
        "routine_budget_percent": round(budget_percent),
        "routine_subscription_count": subscription_count,
        "routine_project_savings": project_savings,
    }


def _build_budget_alerts_context(db: Session) -> dict:
    today = date.today()
    month_start, month_end = month_range(today.year, today.month)
    progress = crud.get_budget_progress(db, month_start, month_end)
    # Triés du pire au meilleur par get_budget_progress lui-même : on n'a
    # besoin que de filtrer les budgets réellement sous surveillance
    # (>= 80 % consommé), le reste (nombre max affiché, dismiss...) est géré
    # côté client puisque l'ignoré-jusqu'au-mois-prochain vit en
    # localStorage, jamais en base.
    alerts = [item for item in progress if item["percentage"] >= 80]
    return {
        "budget_alerts": [
            {
                "category_id": item["category"].id,
                "category_name": item["category"].name,
                "percentage": float(item["percentage"]),
                "spent": float(item["spent"]),
                "budget": float(item["budget"]),
            }
            for item in alerts
        ],
        "current_month_key": today.strftime("%Y-%m"),
    }


@router.get("/inbox", response_class=HTMLResponse)
def inbox(request: Request, db: Session = Depends(get_db)):
    transaction = crud.get_next_pending_transaction(db)
    pending_count = crud.count_pending_transactions(db)
    today = date.today()
    context = {
        "request": request,
        "history": "",
        "pending_count": pending_count,
        "giraffe_scale": _giraffe_scale(pending_count),
        # Bannière mi-mois "Le Cap" : localStorage uniquement (comme
        # _budget_alerts.html, qui fournit déjà current_month_key ci-dessous),
        # jamais l'AppState de _build_routine_banner_context — voir
        # inbox/_le_cap_midmonth_banner.html.
        "show_le_cap_midmonth_banner": today.day == 15,
        **_build_card_context(db, transaction),
        **_build_routine_banner_context(db),
        **_build_budget_alerts_context(db),
    }
    return templates.TemplateResponse("inbox/index.html", context)


@router.post("/routine/dismiss", response_class=HTMLResponse)
def dismiss_routine_banner(db: Session = Depends(get_db)):
    today = date.today()
    crud.mark_routine_seen(db, date(today.year, today.month, 1))
    return HTMLResponse(content="", status_code=200)


def _categorize_and_advance(
    request: Request,
    db: Session,
    transaction: Transaction,
    category: Category,
    label: str | None,
    history: str | None,
    payment_method: str | None = None,
):
    crud.categorize_transaction(db, transaction, category, label=label, payment_method=payment_method)
    rule_suggestion = crud.maybe_rule_suggestion(db, transaction, category)
    new_history = _parse_history(history) + [transaction.id]
    next_transaction = crud.get_next_pending_transaction(db)
    return _render_next_card(
        request,
        db,
        next_transaction,
        new_history,
        just_categorized_id=transaction.id,
        rule_suggestion=rule_suggestion,
    )


def _render_payment_step(request: Request, db: Session, transaction: Transaction, category: Category):
    # Une règle ne pré-sélectionne un mode de paiement que si elle propose
    # AUSSI cette même catégorie ("Valider" ou un choix manuel identique au
    # match) — sinon le mode de paiement d'une règle sans rapport avec la
    # catégorie finalement choisie n'aurait pas de sens.
    matched_rule = crud.find_matching_rule(db, transaction.raw_label)
    suggested_payment_method = (
        matched_rule.payment_method
        if matched_rule is not None and matched_rule.category_id == category.id
        else None
    )
    context = {
        "request": request,
        "transaction": transaction,
        "category": category,
        "suggested_payment_method": suggested_payment_method,
        "payment_methods": crud.get_payment_methods_dict(db),
    }
    return templates.TemplateResponse("inbox/_payment_step.html", context)


@router.post("/{transaction_id}/categorize/{category_id}", response_class=HTMLResponse)
def categorize(
    request: Request,
    transaction_id: int,
    category_id: int,
    db: Session = Depends(get_db),
):
    # Tap sur une sous-catégorie (ou "catégorie générale") dans la grille de
    # sous-catégories : ne sauvegarde plus immédiatement, propose d'abord le
    # mode de paiement (facultatif) — la sauvegarde réelle se fait via
    # /finalize au tap sur un mode de paiement ou "Passer".
    transaction = db.get(Transaction, transaction_id)
    if transaction is None or transaction.validated:
        raise HTTPException(status_code=404, detail="Transaction introuvable")

    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Catégorie introuvable")

    return _render_payment_step(request, db, transaction, category)


@router.post("/{transaction_id}/select-category/{category_id}", response_class=HTMLResponse)
def select_category(
    request: Request,
    transaction_id: int,
    category_id: int,
    db: Session = Depends(get_db),
):
    # Point d'entrée commun au tap sur une catégorie de la grille ET au
    # bouton "Valider" d'une suggestion de règle : dans les deux cas, si la
    # catégorie a des sous-catégories, on marque une pause pour les proposer
    # avant d'enregistrer quoi que ce soit. Sinon, on passe directement à
    # l'étape mode de paiement (facultatif), sans encore sauvegarder.
    transaction = db.get(Transaction, transaction_id)
    if transaction is None or transaction.validated:
        raise HTTPException(status_code=404, detail="Transaction introuvable")

    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Catégorie introuvable")

    subcategories = crud.get_child_categories(db, category.id)
    if not subcategories:
        return _render_payment_step(request, db, transaction, category)

    context = {
        "request": request,
        "transaction": transaction,
        "category": category,
        "subcategories": subcategories,
    }
    return templates.TemplateResponse("inbox/_subcategories_grid.html", context)


@router.post("/{transaction_id}/finalize/{category_id}", response_class=HTMLResponse)
def finalize_categorization(
    request: Request,
    transaction_id: int,
    category_id: int,
    payment_method: str | None = Form(None),
    label: str | None = Form(None),
    history: str | None = Form(None),
    db: Session = Depends(get_db),
):
    # Étape terminale de l'étape mode de paiement (facultative) : tap sur un
    # mode de paiement OU sur "Passer" (payment_method absent dans ce cas).
    transaction = db.get(Transaction, transaction_id)
    if transaction is None or transaction.validated:
        raise HTTPException(status_code=404, detail="Transaction introuvable")

    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Catégorie introuvable")

    payment = payment_method if payment_method in crud.get_payment_methods_dict(db) else None
    return _categorize_and_advance(request, db, transaction, category, label, history, payment)


@router.post("/{transaction_id}/skip", response_class=HTMLResponse)
def skip(
    request: Request,
    transaction_id: int,
    label: str | None = Form(None),
    history: str | None = Form(None),
    db: Session = Depends(get_db),
):
    transaction = db.get(Transaction, transaction_id)
    if transaction is None or transaction.validated:
        raise HTTPException(status_code=404, detail="Transaction introuvable")

    crud.skip_transaction(db, transaction, label=label)

    new_history = _parse_history(history) + [transaction_id]
    next_transaction = crud.get_next_pending_transaction(db)
    return _render_next_card(request, db, next_transaction, new_history)


@router.post("/{transaction_id}/mark-transfer", response_class=HTMLResponse)
def mark_transfer(
    request: Request,
    transaction_id: int,
    label: str | None = Form(None),
    history: str | None = Form(None),
    db: Session = Depends(get_db),
):
    transaction = db.get(Transaction, transaction_id)
    if transaction is None or transaction.validated:
        raise HTTPException(status_code=404, detail="Transaction introuvable")

    crud.mark_transaction_as_transfer(db, transaction, label=label)

    new_history = _parse_history(history) + [transaction_id]
    next_transaction = crud.get_next_pending_transaction(db)
    return _render_next_card(request, db, next_transaction, new_history)


@router.post("/undo", response_class=HTMLResponse)
def undo(request: Request, history: str | None = Form(None), db: Session = Depends(get_db)):
    remaining_history = _parse_history(history)
    if not remaining_history:
        current = crud.get_next_pending_transaction(db)
        return _render_next_card(request, db, current, [])

    previous_id = remaining_history.pop()
    transaction = db.get(Transaction, previous_id)
    if transaction is None:
        current = crud.get_next_pending_transaction(db)
        return _render_next_card(request, db, current, remaining_history)

    crud.undo_transaction(db, transaction)
    return _render_next_card(request, db, transaction, remaining_history)


@router.get("/{transaction_id}/categories", response_class=HTMLResponse)
def categories_grid(request: Request, transaction_id: int, db: Session = Depends(get_db)):
    transaction = db.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction introuvable")

    context = {
        "request": request,
        "transaction": transaction,
        "categories": crud.get_top_level_categories(db),
    }
    return templates.TemplateResponse("inbox/_categories_grid.html", context)


# --- Liste des transactions (recherche, filtres, pagination, édition) ---
#
# Les paramètres de filtre sont préfixés "f_" pour ne jamais entrer en
# collision avec les champs des formulaires d'édition (label, category_id,
# amount, date) : une même route peut ainsi recevoir à la fois le contexte
# de filtrage (query string) et les champs édités (corps du formulaire) sans
# ambiguïté de nommage.


@dataclass
class ListFilters:
    account: str | None
    category: str | None
    subcategory: str | None
    type: str | None
    date_from: str | None
    date_to: str | None
    amount_min: str | None
    amount_max: str | None
    payment_method: str | None
    search: str | None
    sort: str | None
    page: int
    page_size: str | None


# Options exposées par le sélecteur "Afficher : X par page" — toute valeur en
# dehors de cet ensemble (paramètre trafiqué, ancienne valeur en cache...)
# retombe silencieusement sur DEFAULT_PAGE_SIZE plutôt que de planter.
ALLOWED_PAGE_SIZES = (25, 50, 100)
DEFAULT_PAGE_SIZE = 25


def _get_list_filters(
    f_account: str | None = None,
    f_category: str | None = None,
    f_subcategory: str | None = None,
    f_type: str | None = None,
    f_date_from: str | None = None,
    f_date_to: str | None = None,
    f_amount_min: str | None = None,
    f_amount_max: str | None = None,
    f_payment_method: str | None = None,
    f_search: str | None = None,
    f_sort: str | None = None,
    f_page: int = 1,
    f_page_size: str | None = None,
) -> ListFilters:
    return ListFilters(
        f_account, f_category, f_subcategory, f_type, f_date_from, f_date_to,
        f_amount_min, f_amount_max, f_payment_method, f_search, f_sort, f_page,
        f_page_size,
    )


def _parse_int(raw: str | None) -> int | None:
    # Utilisé pour account_id/category_id/subcategory_id/page_size, tous
    # dérivés de paramètres de requête modifiables à la main dans l'URL :
    # une valeur non numérique (ex. ?f_page_size=abc) levait ValueError sans
    # être rattrapée, plantant la page en 500 au lieu de retomber sur "pas de
    # filtre"/valeur par défaut, comme le fait déjà ce fichier pour les
    # autres paramètres invalides (type_filter, sort...).
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _build_filter_qs(filters: ListFilters) -> str:
    params = {}
    if filters.account:
        params["f_account"] = filters.account
    if filters.category:
        params["f_category"] = filters.category
    if filters.subcategory:
        params["f_subcategory"] = filters.subcategory
    if filters.type:
        params["f_type"] = filters.type
    if filters.date_from:
        params["f_date_from"] = filters.date_from
    if filters.date_to:
        params["f_date_to"] = filters.date_to
    if filters.amount_min:
        params["f_amount_min"] = filters.amount_min
    if filters.amount_max:
        params["f_amount_max"] = filters.amount_max
    if filters.payment_method:
        params["f_payment_method"] = filters.payment_method
    if filters.search:
        params["f_search"] = filters.search
    if filters.sort and filters.sort != "date_desc":
        params["f_sort"] = filters.sort
    if filters.page and filters.page != 1:
        params["f_page"] = filters.page
    if filters.page_size and _parse_int(filters.page_size) != DEFAULT_PAGE_SIZE:
        params["f_page_size"] = filters.page_size
    return urlencode(params)


def _build_list_context(db: Session, filters: ListFilters) -> dict:
    start = date.fromisoformat(filters.date_from) if filters.date_from else None
    end = date.fromisoformat(filters.date_to) if filters.date_to else None

    uncategorized_only = filters.category == "uncategorized"
    if filters.subcategory:
        # Une sous-catégorie précise prime sur le filtre parent : on cible
        # exactement cet id, sans inclure ses éventuels descendants.
        parsed_category_id = _parse_int(filters.subcategory)
        category_exact = True
    elif filters.category and not uncategorized_only:
        parsed_category_id = _parse_int(filters.category)
        category_exact = False
    else:
        parsed_category_id = None
        category_exact = False

    # "transfer" était silencieusement perdu ici (seuls income/expense
    # passaient), rendant le filtre "Virements" du formulaire inopérant.
    type_filter = filters.type if filters.type in ("income", "expense", "transfer") else None
    page = max(filters.page or 1, 1)
    sort = (
        filters.sort
        if filters.sort in ("date_desc", "date_asc", "amount_desc", "amount_asc")
        else "date_desc"
    )
    amount_min = _parse_signed_amount(filters.amount_min) if filters.amount_min else None
    amount_max = _parse_signed_amount(filters.amount_max) if filters.amount_max else None
    parsed_page_size = _parse_int(filters.page_size)
    page_size = parsed_page_size if parsed_page_size in ALLOWED_PAGE_SIZES else DEFAULT_PAGE_SIZE

    shared_filter_kwargs = dict(
        account_id=_parse_int(filters.account),
        category_id=parsed_category_id,
        category_exact=category_exact,
        uncategorized_only=uncategorized_only,
        start=start,
        end=end,
        type_filter=type_filter,
        search=filters.search,
        amount_min=amount_min,
        amount_max=amount_max,
        payment_method=filters.payment_method or None,
    )

    transactions, total = crud.list_transactions(
        db, page=page, page_size=page_size, sort=sort, **shared_filter_kwargs
    )
    total_amount = crud.get_transactions_total_amount(db, **shared_filter_kwargs)
    total_pages = max(1, math.ceil(total / page_size)) if total else 1

    return {
        "transactions": transactions,
        "transaction_groups": crud.group_transactions_by_date(transactions),
        # Badge 🧾 sur les opérations qui ont un détail de ticket (voir
        # transactions/_content.html) — sinon l'info n'est visible qu'en
        # ouvrant la fiche une par une.
        "receipt_item_counts": crud.get_receipt_item_counts(db, [t.id for t in transactions]),
        "total": total,
        "total_amount": total_amount,
        "page": page,
        "total_pages": total_pages,
        "page_size": page_size,
        "allowed_page_sizes": ALLOWED_PAGE_SIZES,
        "filter_qs": _build_filter_qs(filters),
        "search": filters.search or "",
        "account_filter": filters.account or "",
        "category_filter": filters.category or "",
        "subcategory_filter": filters.subcategory or "",
        "type_filter": filters.type or "",
        "date_from": filters.date_from or "",
        "date_to": filters.date_to or "",
        "amount_min": filters.amount_min or "",
        "amount_max": filters.amount_max or "",
        "payment_method_filter": filters.payment_method or "",
        "sort_filter": sort,
        # Toujours inclus (pas seulement sur la page complète) : la barre
        # d'actions groupées de _content.html a besoin des catégories
        # parentes et des modes de paiement à chaque réaffichage (changement
        # de filtre, pagination, application groupée...), pas seulement au
        # premier chargement.
        "categories": crud.get_top_level_categories(db),
        "payment_methods": crud.get_payment_methods_dict(db),
    }


def _parse_signed_amount(raw: str) -> Decimal:
    try:
        return parse_decimal_amount(raw)
    except ImportParseError:
        return Decimal("0.00")


@router.get("/list", response_class=HTMLResponse)
def transactions_list(
    request: Request,
    filters: ListFilters = Depends(_get_list_filters),
    db: Session = Depends(get_db),
):
    filter_parent_id = _parse_int(filters.category) if filters.category not in (None, "", "uncategorized") else None
    filter_parent = db.get(Category, filter_parent_id) if filter_parent_id else None
    filter_subcategories = crud.get_child_categories(db, filter_parent.id) if filter_parent else []

    context = {
        "request": request,
        "accounts": crud.list_accounts(db),
        "filter_parent": filter_parent,
        "filter_subcategories": filter_subcategories,
        **_build_list_context(db, filters),  # inclut déjà "categories" et "payment_methods"
    }
    return templates.TemplateResponse("transactions/index.html", context)


@router.get("/list/content", response_class=HTMLResponse)
def transactions_list_content(
    request: Request,
    filters: ListFilters = Depends(_get_list_filters),
    db: Session = Depends(get_db),
):
    context = {"request": request, **_build_list_context(db, filters)}
    return templates.TemplateResponse("transactions/_content.html", context)


@router.get("/new", response_class=HTMLResponse)
def new_transaction_form(
    request: Request,
    filters: ListFilters = Depends(_get_list_filters),
    db: Session = Depends(get_db),
):
    context = {
        "request": request,
        "accounts": crud.list_accounts(db),
        "parent_categories": crud.get_top_level_categories(db),
        "current_parent_id": None,
        "parent": None,
        "subcategories": [],
        "selected_category_id": None,
        "field_name": "category_id",
        "element_id": "subcategory-select",
        "allow_empty": False,
        "filter_qs": _build_filter_qs(filters),
        "today": date.today().isoformat(),
        "payment_methods": crud.get_payment_methods_dict(db),
    }
    return templates.TemplateResponse("transactions/_new.html", context)


@router.post("/create", response_class=HTMLResponse)
def create_transaction(
    request: Request,
    label: str = Form(...),
    category_id: str = Form(""),
    amount: str = Form(...),
    transaction_date: str = Form(..., alias="date"),
    account_id: str = Form(...),
    is_transfer: str | None = Form(None),
    payment_method: str = Form(""),
    note: str = Form(""),
    filters: ListFilters = Depends(_get_list_filters),
    db: Session = Depends(get_db),
):
    category = db.get(Category, int(category_id)) if category_id else None
    account = db.get(Account, int(account_id))
    if account is None:
        raise HTTPException(status_code=404, detail="Compte introuvable")

    crud.create_manual_transaction(
        db,
        label=label.strip(),
        category=category,
        amount=_parse_signed_amount(amount),
        transaction_date=date.fromisoformat(transaction_date),
        account=account,
        is_transfer=is_transfer is not None,
        payment_method=payment_method if payment_method in crud.get_payment_methods_dict(db) else None,
        note=note,
    )

    context = {"request": request, **_build_list_context(db, filters)}
    context["success_message"] = "✅ Opération ajoutée"
    return templates.TemplateResponse("transactions/_content.html", context)


@router.get("/{transaction_id}/detail", response_class=HTMLResponse)
def transaction_detail(
    request: Request,
    transaction_id: int,
    filters: ListFilters = Depends(_get_list_filters),
    db: Session = Depends(get_db),
):
    transaction = db.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction introuvable")

    current_parent = crud.resolve_top_level_category(transaction.category)
    subcategories = crud.get_child_categories(db, current_parent.id) if current_parent else []
    top_level_categories = crud.get_top_level_categories(db)
    receipt_items = crud.get_receipt_items(db, transaction.id)

    context = {
        "request": request,
        "transaction": transaction,
        "accounts": crud.list_accounts(db),
        "parent_categories": top_level_categories,
        "current_parent_id": current_parent.id if current_parent else None,
        "parent": current_parent,
        "subcategories": subcategories,
        "selected_category_id": transaction.category_id,
        "field_name": "category_id",
        "element_id": "subcategory-select",
        "allow_empty": False,
        "filter_qs": _build_filter_qs(filters),
        "payment_methods": crud.get_payment_methods_dict(db),
        # Détail du ticket (transactions/_receipt.html), inclus dans ce même
        # modal — voir routers/receipts.py pour les actions (upload, lignes).
        "receipt_items": receipt_items,
        "receipt_groups": group_items_by_family(receipt_items),
        "receipt_families": RECEIPT_FAMILIES,
        "raw_extracted_text": None,
    }
    return templates.TemplateResponse("transactions/_detail.html", context)


@router.get("/subcategories", response_class=HTMLResponse)
def category_subcategories(
    request: Request,
    parent_category_id: str | None = None,
    f_category: str | None = None,
    field_name: str = "category_id",
    element_id: str = "subcategory-select",
    allow_empty: bool = False,
    db: Session = Depends(get_db),
):
    # Le modal d'édition envoie "parent_category_id" (nom de son propre
    # select) ; le filtre de la liste envoie "f_category" (pour rester
    # cohérent avec le reste du système de filtres ListFilters). Les deux
    # sont acceptés ici plutôt que d'imposer un seul nom aux deux appelants.
    raw_parent_id = parent_category_id or f_category
    parent = None
    if raw_parent_id and raw_parent_id != "uncategorized":
        parent = db.get(Category, int(raw_parent_id))
    subcategories = crud.get_child_categories(db, parent.id) if parent else []

    context = {
        "request": request,
        "parent": parent,
        "subcategories": subcategories,
        "selected_category_id": None,
        "field_name": field_name,
        "element_id": element_id,
        "allow_empty": allow_empty,
    }
    return templates.TemplateResponse("transactions/_subcategory_select.html", context)


@router.post("/{transaction_id}/update", response_class=HTMLResponse)
def update_transaction_detail(
    request: Request,
    transaction_id: int,
    label: str = Form(...),
    category_id: str = Form(""),
    amount: str = Form(...),
    transaction_date: str = Form(..., alias="date"),
    account_id: str = Form(...),
    is_transfer: str | None = Form(None),
    is_unexpected: str | None = Form(None),
    payment_method: str = Form(""),
    note: str = Form(""),
    filters: ListFilters = Depends(_get_list_filters),
    db: Session = Depends(get_db),
):
    transaction = db.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction introuvable")

    category = db.get(Category, int(category_id)) if category_id else None
    account = db.get(Account, int(account_id))
    if account is None:
        raise HTTPException(status_code=404, detail="Compte introuvable")

    crud.update_transaction(
        db,
        transaction,
        label=label.strip(),
        category=category,
        amount=_parse_signed_amount(amount),
        transaction_date=date.fromisoformat(transaction_date),
        account=account,
        # Case à cocher HTML : présente uniquement quand cochée.
        is_transfer=is_transfer is not None,
        payment_method=payment_method if payment_method in crud.get_payment_methods_dict(db) else None,
        note=note,
        is_unexpected=is_unexpected is not None,
    )

    context = {"request": request, **_build_list_context(db, filters)}
    return templates.TemplateResponse("transactions/_content.html", context)


@router.post("/{transaction_id}/mark-unexpected", response_class=HTMLResponse)
def mark_unexpected(transaction_id: int, db: Session = Depends(get_db)):
    # Bouton "🆘 Marquer comme imprévu" (La Savane, toast auto-disparaissant
    # — voir inbox/_unexpected_toast.html) : la transaction est déjà
    # enregistrée à ce stade (le tap arrive APRÈS l'avancée vers la carte
    # suivante), donc pas de contexte de carte à re-rendre ici, juste l'état
    # à poser. hx-swap="none" côté template, aucun contenu à renvoyer.
    transaction = db.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction introuvable")
    crud.mark_transaction_unexpected(db, transaction)
    return HTMLResponse(content="", status_code=200)


@router.post("/{transaction_id}/unvalidate", response_class=HTMLResponse)
def unvalidate_transaction_detail(
    request: Request,
    transaction_id: int,
    filters: ListFilters = Depends(_get_list_filters),
    db: Session = Depends(get_db),
):
    transaction = db.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction introuvable")

    crud.unvalidate_transaction(db, transaction)

    context = {"request": request, **_build_list_context(db, filters)}
    return templates.TemplateResponse("transactions/_content.html", context)


@router.post("/{transaction_id}/delete", response_class=HTMLResponse)
def delete_transaction_detail(
    request: Request,
    transaction_id: int,
    filters: ListFilters = Depends(_get_list_filters),
    db: Session = Depends(get_db),
):
    transaction = db.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction introuvable")

    crud.delete_transaction(db, transaction)

    context = {"request": request, **_build_list_context(db, filters)}
    return templates.TemplateResponse("transactions/_content.html", context)


def _plural_feminine(count: int) -> str:
    return "s" if count != 1 else ""


@router.post("/bulk-apply", response_class=HTMLResponse)
def bulk_apply(
    request: Request,
    selected_ids: list[int] | None = Form(None),
    category_id: str = Form(""),
    payment_method: str = Form(""),
    filters: ListFilters = Depends(_get_list_filters),
    db: Session = Depends(get_db),
):
    category = db.get(Category, int(category_id)) if category_id else None
    payment = payment_method if payment_method in crud.get_payment_methods_dict(db) else None
    ids = selected_ids or []

    context = {"request": request, **_build_list_context(db, filters)}
    if not ids or (category is None and payment is None):
        # Rien à appliquer (aucune case cochée, ou ni catégorie ni mode de
        # paiement renseigné) : catégorie et mode de paiement sont chacun
        # facultatifs et indépendants, appliquer seulement l'un des deux
        # doit marcher normalement (voir crud.bulk_update_transactions).
        return templates.TemplateResponse("transactions/_content.html", context)

    transactions = [t for t in (db.get(Transaction, tid) for tid in ids) if t is not None]
    crud.bulk_update_transactions(db, transactions, category=category, payment_method=payment)

    context = {"request": request, **_build_list_context(db, filters)}
    plural = _plural_feminine(len(transactions))
    context["success_message"] = f"✅ {len(transactions)} opération{plural} mise{plural} à jour"
    return templates.TemplateResponse("transactions/_content.html", context)


@router.post("/bulk-unvalidate", response_class=HTMLResponse)
def bulk_unvalidate(
    request: Request,
    selected_ids: list[int] | None = Form(None),
    filters: ListFilters = Depends(_get_list_filters),
    db: Session = Depends(get_db),
):
    ids = selected_ids or []
    transactions = [t for t in (db.get(Transaction, tid) for tid in ids) if t is not None]
    count = crud.bulk_unvalidate_transactions(db, transactions)

    context = {"request": request, **_build_list_context(db, filters)}
    if count:
        plural = _plural_feminine(count)
        context["success_message"] = f"📥 {count} opération{plural} remise{plural} dans La Savane"
    return templates.TemplateResponse("transactions/_content.html", context)


@router.post("/bulk-mark-transfer", response_class=HTMLResponse)
def bulk_mark_transfer(
    request: Request,
    selected_ids: list[int] | None = Form(None),
    filters: ListFilters = Depends(_get_list_filters),
    db: Session = Depends(get_db),
):
    ids = selected_ids or []
    transactions = [t for t in (db.get(Transaction, tid) for tid in ids) if t is not None]
    count = crud.bulk_mark_as_transfer(db, transactions)

    context = {"request": request, **_build_list_context(db, filters)}
    if count:
        plural = _plural_feminine(count)
        context["success_message"] = f"🔄 {count} opération{plural} marquée{plural} comme virement"
    return templates.TemplateResponse("transactions/_content.html", context)


@router.post("/bulk-mark-unexpected", response_class=HTMLResponse)
def bulk_mark_unexpected(
    request: Request,
    selected_ids: list[int] | None = Form(None),
    filters: ListFilters = Depends(_get_list_filters),
    db: Session = Depends(get_db),
):
    ids = selected_ids or []
    transactions = [t for t in (db.get(Transaction, tid) for tid in ids) if t is not None]
    count = crud.bulk_mark_as_unexpected(db, transactions)

    context = {"request": request, **_build_list_context(db, filters)}
    if count:
        plural = _plural_feminine(count)
        context["success_message"] = f"🆘 {count} opération{plural} marquée{plural} comme imprévu{plural}"
    return templates.TemplateResponse("transactions/_content.html", context)


@router.post("/bulk-unmark-transfer", response_class=HTMLResponse)
def bulk_unmark_transfer(
    request: Request,
    selected_ids: list[int] | None = Form(None),
    filters: ListFilters = Depends(_get_list_filters),
    db: Session = Depends(get_db),
):
    ids = selected_ids or []
    transactions = [t for t in (db.get(Transaction, tid) for tid in ids) if t is not None]
    count = crud.bulk_unmark_transfer(db, transactions)

    context = {"request": request, **_build_list_context(db, filters)}
    if count:
        plural = _plural_feminine(count)
        context["success_message"] = f"↩️ {count} opération{plural} renvoyée{plural} dans La Savane (virement annulé)"
    return templates.TemplateResponse("transactions/_content.html", context)


@router.post("/bulk-delete", response_class=HTMLResponse)
def bulk_delete(
    request: Request,
    selected_ids: list[int] | None = Form(None),
    filters: ListFilters = Depends(_get_list_filters),
    db: Session = Depends(get_db),
):
    ids = selected_ids or []
    transactions = [t for t in (db.get(Transaction, tid) for tid in ids) if t is not None]
    count = crud.bulk_delete_transactions(db, transactions)

    context = {"request": request, **_build_list_context(db, filters)}
    if count:
        plural = _plural_feminine(count)
        context["success_message"] = f"🗑️ {count} opération{plural} supprimée{plural}"
    return templates.TemplateResponse("transactions/_content.html", context)
