import logging
import time
import unicodedata
from decimal import Decimal

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import answers, crud, preferences, savane
from backend.database import get_db
from backend.formatting import format_amount
from backend.models import Category, Transaction
from backend.templating import flash_html, templates
from backend.i18n import gettext as _t

logger = logging.getLogger("backend.backlog")

router = APIRouter(prefix="/backlog", tags=["backlog"])

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


def _normalize_label(label: str) -> str:
    """Key under which two labels count as "the same": case, accents and spacing ignored."""
    decomposed = unicodedata.normalize("NFKD", label or "")
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(stripped.lower().split())


def _build_items(db: Session) -> list[dict]:
    # Le cache ne garde QUE des données déjà extraites (pas d'objets ORM
    # vivants) : les objets SQLAlchemy sont liés à la Session de LA requête
    # qui les a chargés, or ce cache survit entre requêtes (chacune avec sa
    # propre Session) — garder un Transaction/Category "détaché" exposerait
    # à un DetachedInstanceError au moindre accès à un attribut non déjà
    # chargé une fois la Session d'origine fermée.
    pending = crud.get_backlog_transactions(db)
    samples = crud.get_categorized_label_samples(db)
    history = savane.history_index(db)
    categories_by_id = {c.id: c for c in db.execute(select(Category)).scalars().all()}

    items = []
    for tx in pending:
        raw_suggestion = crud.suggest_backlog_category(tx, samples, categories_by_id)
        suggestion = None
        if raw_suggestion is not None:
            category = raw_suggestion["category"]
            parent = categories_by_id.get(category.parent_id) if category.parent_id else None
            in_category, history_total = savane.history_counts(history, tx, category.id)
            suggestion = {
                # The lot of the other way: sure, and not contradicted by the history.
                "history_in": in_category,
                "history_total": history_total,
                "sure": raw_suggestion["confidence"] >= savane.SURE_CONFIDENCE
                and (history_total == 0 or in_category / history_total >= savane.SURE_HISTORY_SHARE),
                "category_id": category.id,
                "category_name": category.name,
                "category_icon": category.icon,
                # "Parent › Child" for a sub-category, the bare name for a top-level one.
                "category_path": f"{parent.name} › {category.name}" if parent else category.name,
                # Colour and "Suggested category" filter follow the top-level category.
                "category_top_id": parent.id if parent else category.id,
                "category_top_name": parent.name if parent else category.name,
                "based_on_label": raw_suggestion["based_on_label"],
                "confidence": raw_suggestion["confidence"],
            }
        items.append(
            {
                "transaction_id": tx.id,
                "date": tx.date,
                "label": tx.label,
                "raw_label": tx.raw_label,
                "payment_method": tx.payment_method,
                "label_key": _normalize_label(tx.label),
                "account_id": tx.account_id,
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




# Rows shown at first, and added by each "Show the next ones" click.
PAGE_SIZE = 10
MAX_LIMIT = 1000

# Confidence classes, shared by the filter chips, the counters and the badges.
HIGH_CONFIDENCE = savane.SURE_CONFIDENCE
MID_CONFIDENCE = 70
# "sure" is the other way's lot: sure and not contradicted by the history.
CONFIDENCE_FILTERS = ("all", "high", "mid", "low", "none", "sure")


def confidence_class(confidence: int | None) -> str:
    if confidence is None:
        return "none"
    if confidence >= HIGH_CONFIDENCE:
        return "high"
    if confidence >= MID_CONFIDENCE:
        return "mid"
    return "low"


def _to_int(value: str | int | None) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _parse_ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    return [int(part) for part in raw.split(",") if part.strip().isdigit()]


def _matches_scope(item: dict, search: str, account_id: int | None, category_id: int | None) -> bool:
    """Search, account and suggested-category filters (everything but the confidence chips)."""
    needle = search.strip().lower()
    if needle and needle not in item["label"].lower():
        return False
    if account_id is not None and item["account_id"] != account_id:
        return False
    if category_id is not None:
        suggestion = item["suggestion"]
        if suggestion is None or suggestion["category_top_id"] != category_id:
            return False
    return True


def _scoped_items(
    items: list[dict],
    search: str = "",
    account_id: int | None = None,
    category_id: int | None = None,
) -> list[dict]:
    return [i for i in items if _matches_scope(i, search, account_id, category_id)]


def _item_class(item: dict) -> str:
    return confidence_class(item["suggestion"]["confidence"] if item["suggestion"] else None)


def _apply_filters(
    items: list[dict],
    search: str,
    suggestion_filter: str,
    account_id: int | None = None,
    category_id: int | None = None,
) -> list[dict]:
    scoped = _scoped_items(items, search, account_id, category_id)
    if suggestion_filter not in CONFIDENCE_FILTERS or suggestion_filter == "all":
        return scoped
    if suggestion_filter == "sure":
        return [i for i in scoped if i["suggestion"] and i["suggestion"]["sure"]]
    return [i for i in scoped if _item_class(i) == suggestion_filter]


def _confidence_counts(scoped: list[dict]) -> dict[str, int]:
    counts = {key: 0 for key in CONFIDENCE_FILTERS}
    counts["all"] = len(scoped)
    for item in scoped:
        counts[_item_class(item)] += 1
        if item["suggestion"] and item["suggestion"]["sure"]:
            counts["sure"] += 1
    return counts


def _group_rows(items: list[dict], group: bool) -> list[dict]:
    """One row per operation, or one per (normalized label, suggested category) when grouping."""
    rows: list[dict] = []
    index: dict[str, int] = {}
    for item in items:
        suggestion = item["suggestion"]
        key = (
            f"{item['label_key']}|{suggestion['category_id'] if suggestion else ''}"
            if group
            else str(item["transaction_id"])
        )
        if key not in index:
            index[key] = len(rows)
            rows.append({"key": key, "items": []})
        rows[index[key]]["items"].append(item)
    for row in rows:
        first = row["items"][0]
        confidences = [
            i["suggestion"]["confidence"] for i in row["items"] if i["suggestion"] is not None
        ]
        row.update(
            ids=[i["transaction_id"] for i in row["items"]],
            count=len(row["items"]),
            label=first["label"],
            suggestion=first["suggestion"],
            # A group is only as sure as its least sure operation.
            confidence=min(confidences) if confidences else None,
            amount=sum((i["amount"] for i in row["items"]), Decimal("0")),
        )
    return rows


def _filter_state(
    search: str, suggestion_filter: str, account: str, category: str, group: str, limit: int
) -> dict:
    return {
        "search": search,
        "suggestion_filter": suggestion_filter if suggestion_filter in CONFIDENCE_FILTERS else "all",
        "account_id": _to_int(account),
        "category_id": _to_int(category),
        "group": group in ("1", "true", "on"),
        "limit": max(PAGE_SIZE, min(limit, MAX_LIMIT)),
    }


def _build_page_context(
    db: Session,
    search: str = "",
    suggestion_filter: str = "all",
    account: str = "",
    category: str = "",
    group: str = "",
    limit: int = PAGE_SIZE,
    page: int = 1,
    other_way: bool = False,
) -> dict:
    state = _filter_state(search, suggestion_filter, account, category, group, limit)
    all_items = _cached_items(db)
    scoped = _scoped_items(all_items, state["search"], state["account_id"], state["category_id"])
    counts = _confidence_counts(scoped)
    visible = _apply_filters(
        all_items,
        state["search"],
        state["suggestion_filter"],
        state["account_id"],
        state["category_id"],
    )
    rows = _group_rows(visible, state["group"])
    accounts = crud.list_accounts(db)
    parent_categories = crud.get_top_level_categories(db)
    extra = _other_way_context(all_items, scoped, visible, rows, state, page) if other_way else {}
    return {
        **extra,
        "rows": rows[: state["limit"]],
        "rows_total": len(rows),
        "remaining": max(0, len(rows) - state["limit"]),
        "visible_total": len(visible),
        "visible_ids": [i["transaction_id"] for i in visible],
        "counts": counts,
        "pending_total": len(all_items),
        "state": state,
        "accounts": accounts,
        "parent_categories": parent_categories,
        "account_labels": {str(a.id): a.name for a in accounts},
        "category_labels": {str(c.id): c.name for c in parent_categories},
        "payment_methods": crud.get_payment_methods_dict(db),
        "step": PAGE_SIZE,
    }


# Groups per page on the other way's screen.
GROUPS_PER_PAGE = 6
# Rows drawn in a group; the count and the group's action still cover them all.
GROUP_ROWS_SHOWN = 40


def _other_way_context(
    all_items: list[dict], scoped: list[dict], visible: list[dict], rows: list[dict], state: dict, page: int
) -> dict:
    """What the other way draws on top of the rows: the groups, the lot in view, the sentence.

    Groups are the top-level categories the suggestions point to, plus one for
    the operations without a suggestion (last). The lot is what is sure
    (HIGH_CONFIDENCE) among the operations in view; « Tout ranger » files it,
    minus the lines the user leaves aside (kept by the page, not here).
    """
    groups: dict[object, dict] = {}
    for row in rows:
        suggestion = row["suggestion"]
        key = suggestion["category_top_id"] if suggestion else None
        group = groups.setdefault(
            key,
            {
                "key": key,
                "top_id": key,
                "name": suggestion["category_top_name"] if suggestion else None,
                "rows": [],
                "count": 0,
                "total": Decimal("0"),
                "confidences": [],
                "payments": [],
                "lot_ids": [],
            },
        )
        row["sure"] = bool(suggestion and suggestion["sure"])
        group["rows"].append(row)
        group["count"] += row["count"]
        group["total"] += row["amount"]
        if row["confidence"] is not None:
            group["confidences"].append(row["confidence"])
        for item in row["items"]:
            method = item["payment_method"]
            if method and method not in group["payments"]:
                group["payments"].append(method)
            if item["suggestion"] and item["suggestion"]["sure"]:
                group["lot_ids"].append(item["transaction_id"])
    ordered = sorted(
        groups.values(), key=lambda g: (g["key"] is None, -g["count"], g["name"] or "")
    )
    for group in ordered:
        group["min_confidence"] = min(group["confidences"]) if group["confidences"] else None
        group["hidden_rows"] = max(0, len(group["rows"]) - GROUP_ROWS_SHOWN)
        group["rows"] = group["rows"][:GROUP_ROWS_SHOWN]
    pages = max(1, -(-len(ordered) // GROUPS_PER_PAGE))
    page = min(max(page, 1), pages)
    shown = ordered[(page - 1) * GROUPS_PER_PAGE : page * GROUPS_PER_PAGE]

    lot = [i for i in visible if i["suggestion"] and i["suggestion"]["sure"]]
    lot_total = sum((i["amount"] for i in lot), Decimal("0"))
    by_category: dict[int, dict] = {}
    payments: dict[str, int] = {}
    for item in lot:
        suggestion = item["suggestion"]
        entry = by_category.setdefault(
            suggestion["category_top_id"],
            {"top_id": suggestion["category_top_id"], "name": suggestion["category_top_name"], "total": Decimal("0")},
        )
        entry["total"] += item["amount"]
        payments[item["payment_method"] or ""] = payments.get(item["payment_method"] or "", 0) + 1
    lot_categories = sorted(by_category.values(), key=lambda e: e["total"])
    min_confidence = min((i["suggestion"]["confidence"] for i in lot), default=None)
    answer = answers.masse_answer(
        count=len(lot),
        categories=len(lot_categories),
        amount=format_amount(abs(lot_total)),
        min_confidence=min_confidence,
        pending=len(all_items),
        searching=bool(state["search"].strip()),
    )
    return {
        "groups": shown,
        "shown_ids": [i for g in shown for r in g["rows"] for i in r["ids"]],
        "groups_total": len(ordered),
        "page": page,
        "pages": pages,
        "lot_ids": [i["transaction_id"] for i in lot],
        "lot_count": len(lot),
        "lot_total": lot_total,
        "lot_categories": lot_categories,
        "lot_category_max": max((abs(e["total"]) for e in lot_categories), default=Decimal("1")) or Decimal("1"),
        "lot_payments": sorted(payments.items(), key=lambda kv: -kv[1]),
        "doubt_count": max(0, len(all_items) - len(lot)),
        "answer": answer,
        "scoped_total": len(scoped),
    }


def _other_way(request: Request) -> bool:
    variant = getattr(request.state, "ui_variant", None) or preferences.current_ui_variant()
    return variant == "other_way"


def _filters(
    search: str, suggestion_filter: str, account: str, category: str, group: str, limit: int, page: int = 1
) -> dict:
    return {
        "search": search,
        "suggestion_filter": suggestion_filter,
        "account": account,
        "category": category,
        "group": group,
        "limit": limit,
        "page": page,
    }


def _content_response(
    request: Request,
    db: Session,
    filters: dict,
    rule_suggestions: list[dict] | None = None,
    last: dict | None = None,
):
    context = _build_page_context(db, **filters, other_way=_other_way(request))
    context["request"] = request
    context["rule_suggestions"] = rule_suggestions or []
    context["last"] = last
    context["oob"] = True
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


def _items_by_id(db: Session) -> dict[int, dict]:
    return {item["transaction_id"]: item for item in _cached_items(db)}


def _category_path(category: Category) -> str:
    return f"{category.parent.name} › {category.name}" if category.parent else category.name


def _common_path(categories: list[Category]) -> str:
    paths = {_category_path(c) for c in categories}
    return paths.pop() if len(paths) == 1 else ""


@router.get("", response_class=HTMLResponse)
def backlog_page(
    request: Request,
    search: str = "",
    suggestion_filter: str | None = None,
    account: str = "",
    category: str = "",
    group: str = "",
    limit: int = PAGE_SIZE,
    page: int = 1,
    db: Session = Depends(get_db),
):
    other_way = _other_way(request)
    if suggestion_filter is None:
        # The other way opens on the lot: what is sure.
        suggestion_filter = "sure" if other_way else "all"
    context = _build_page_context(
        db, search, suggestion_filter, account, category, group, limit, page, other_way
    )
    context["request"] = request
    context["rule_suggestions"] = []
    context["last"] = None
    context["oob"] = False
    return templates.TemplateResponse("backlog/index.html", context)


@router.get("/content", response_class=HTMLResponse)
def backlog_content(
    request: Request,
    search: str = "",
    suggestion_filter: str | None = None,
    account: str = "",
    category: str = "",
    group: str = "",
    limit: int = PAGE_SIZE,
    page: int = 1,
    db: Session = Depends(get_db),
):
    if suggestion_filter is None:
        suggestion_filter = "sure" if _other_way(request) else "all"
    return _content_response(
        request, db, _filters(search, suggestion_filter, account, category, group, limit, page)
    )


@router.post("/validate", response_class=HTMLResponse)
def validate_rows(
    request: Request,
    ids: str = Form(""),
    category_id: str = Form(""),
    search: str = Form(""),
    suggestion_filter: str = Form("all"),
    account: str = Form(""),
    category: str = Form(""),
    group: str = Form(""),
    limit: int = Form(PAGE_SIZE),
    page: int = Form(1),
    db: Session = Depends(get_db),
):
    """File one row (or every operation of a grouped row): in the chosen category,
    or in each operation's own suggestion when none is given."""
    chosen = db.get(Category, int(category_id)) if category_id else None
    if category_id and chosen is None:
        raise HTTPException(status_code=404, detail=_t("Catégorie introuvable"))
    by_id = _items_by_id(db)
    rule_suggestions = []
    processed: list[tuple[Transaction, Category]] = []
    for transaction_id in _parse_ids(ids):
        transaction = db.get(Transaction, transaction_id)
        if transaction is None:
            raise HTTPException(status_code=404, detail=_t("Transaction introuvable"))
        target = chosen
        if target is None:
            suggestion = (by_id.get(transaction_id) or {}).get("suggestion")
            target = db.get(Category, suggestion["category_id"]) if suggestion else None
        if target is None:
            continue
        maybe_rule = crud.maybe_rule_suggestion(db, transaction, target)
        crud.categorize_transaction(db, transaction, target)
        processed.append((transaction, target))
        if maybe_rule:
            rule_suggestions.append(maybe_rule)
    _remove_from_cache({t.id for t, _ in processed})
    last = None
    if processed:
        last = {
            "kind": "filed",
            "count": len(processed),
            "label": processed[0][0].label,
            "path": _common_path([c for _, c in processed]),
        }
    return _content_response(
        request,
        db,
        _filters(search, suggestion_filter, account, category, group, limit, page),
        _dedupe_rule_suggestions(rule_suggestions),
        last,
    )


def _reject(db: Session, ids: list[int]) -> set[int]:
    processed: set[int] = set()
    for transaction_id in ids:
        transaction = db.get(Transaction, transaction_id)
        if transaction is None:
            raise HTTPException(status_code=404, detail=_t("Transaction introuvable"))
        crud.reject_from_backlog(db, transaction)
        processed.add(transaction_id)
    _remove_from_cache(processed)
    return processed


@router.post("/reject", response_class=HTMLResponse)
def reject_rows(
    request: Request,
    ids: str = Form(""),
    search: str = Form(""),
    suggestion_filter: str = Form("all"),
    account: str = Form(""),
    category: str = Form(""),
    group: str = Form(""),
    limit: int = Form(PAGE_SIZE),
    page: int = Form(1),
    db: Session = Depends(get_db),
):
    """Send a row back to La Savane: it leaves this list, nothing is categorized."""
    processed = _reject(db, _parse_ids(ids))
    return _content_response(
        request,
        db,
        _filters(search, suggestion_filter, account, category, group, limit, page),
        last={"kind": "rejected", "count": len(processed)} if processed else None,
    )


def _visible_items(
    db: Session, search: str, suggestion_filter: str, account: str, category: str
) -> list[dict]:
    return _apply_filters(
        _cached_items(db), search, suggestion_filter, _to_int(account), _to_int(category)
    )


@router.post("/bulk-validate", response_class=HTMLResponse)
def bulk_validate(
    request: Request,
    min_confidence: int = Form(HIGH_CONFIDENCE),
    search: str = Form(""),
    suggestion_filter: str = Form("all"),
    account: str = Form(""),
    category: str = Form(""),
    group: str = Form(""),
    limit: int = Form(PAGE_SIZE),
    page: int = Form(1),
    db: Session = Depends(get_db),
):
    """File every listed operation whose suggestion is at least `min_confidence` sure."""
    rule_suggestions = []
    processed_ids: set[int] = set()
    for item in _visible_items(db, search, suggestion_filter, account, category):
        suggestion = item["suggestion"]
        if suggestion is None or suggestion["confidence"] < min_confidence:
            continue
        transaction = db.get(Transaction, item["transaction_id"])
        target = db.get(Category, suggestion["category_id"])
        if transaction is None or target is None:
            continue
        maybe_rule = crud.maybe_rule_suggestion(db, transaction, target)
        crud.categorize_transaction(db, transaction, target)
        processed_ids.add(transaction.id)
        if maybe_rule:
            rule_suggestions.append(maybe_rule)
    _remove_from_cache(processed_ids)
    return _content_response(
        request,
        db,
        _filters(search, suggestion_filter, account, category, group, limit, page),
        _dedupe_rule_suggestions(rule_suggestions),
        {"kind": "filed_sure", "count": len(processed_ids), "threshold": min_confidence}
        if processed_ids
        else None,
    )


@router.post("/bulk-reject", response_class=HTMLResponse)
def bulk_reject(
    request: Request,
    max_confidence: int = Form(MID_CONFIDENCE),
    search: str = Form(""),
    suggestion_filter: str = Form("all"),
    account: str = Form(""),
    category: str = Form(""),
    group: str = Form(""),
    limit: int = Form(PAGE_SIZE),
    page: int = Form(1),
    db: Session = Depends(get_db),
):
    """Send back to La Savane every listed operation whose suggestion is under `max_confidence`."""
    ids = [
        item["transaction_id"]
        for item in _visible_items(db, search, suggestion_filter, account, category)
        if item["suggestion"] is not None and item["suggestion"]["confidence"] < max_confidence
    ]
    processed = _reject(db, ids)
    return _content_response(
        request,
        db,
        _filters(search, suggestion_filter, account, category, group, limit, page),
        last={"kind": "rejected", "count": len(processed)} if processed else None,
    )


@router.post("/bulk-apply", response_class=HTMLResponse)
def bulk_apply(
    request: Request,
    selected_ids: list[int] | None = Form(None),
    apply_category_id: str = Form(""),
    apply_payment_method: str = Form(""),
    search: str = Form(""),
    suggestion_filter: str = Form("all"),
    account: str = Form(""),
    category: str = Form(""),
    group: str = Form(""),
    limit: int = Form(PAGE_SIZE),
    page: int = Form(1),
    db: Session = Depends(get_db),
):
    """Apply to the selection: the chosen category (or each operation's own suggestion),
    and/or a payment method. Operations with nothing to be filed in stay in the list."""
    chosen = db.get(Category, int(apply_category_id)) if apply_category_id else None
    payment = (
        apply_payment_method
        if apply_payment_method in crud.get_payment_methods_dict(db)
        else None
    )
    filters = _filters(search, suggestion_filter, account, category, group, limit, page)
    ids = selected_ids or []
    if not ids:
        return _content_response(request, db, filters)

    by_id = _items_by_id(db)
    filed: list[tuple[Transaction, Category]] = []
    kept = 0
    for transaction_id in ids:
        transaction = db.get(Transaction, transaction_id)
        if transaction is None:
            continue
        target = chosen
        if target is None:
            suggestion = (by_id.get(transaction_id) or {}).get("suggestion")
            target = db.get(Category, suggestion["category_id"]) if suggestion else None
        if target is None:
            kept += 1
            if payment is not None:
                crud.bulk_update_transactions(db, [transaction], payment_method=payment)
            continue
        crud.bulk_update_transactions(db, [transaction], category=target, payment_method=payment)
        filed.append((transaction, target))

    # Only operations that received a category leave the list.
    _remove_from_cache({t.id for t, _ in filed})
    last = None
    if filed or kept:
        last = {
            "kind": "applied",
            "count": len(filed),
            "label": filed[0][0].label if filed else "",
            "path": _common_path([c for _, c in filed]),
            "kept": kept,
            "payment": payment or "",
        }
    return _content_response(request, db, filters, last=last)


@router.post("/create-rule", response_class=HTMLResponse)
def create_rule_from_suggestion(
    keyword: str = Form(...), category_id: int = Form(...), db: Session = Depends(get_db)
):
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail=_t("Catégorie introuvable"))
    if keyword.strip():
        crud.create_rule(db, keyword.strip(), category)
    return HTMLResponse(content=flash_html("success", _t("Règle créée")))
