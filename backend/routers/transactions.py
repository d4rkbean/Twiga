import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from backend import answers, crud, preferences, role_rights, savane
from backend.auth import check_role_access
from backend.database import get_db
from backend.budget_month import period_containing, period_spanning
from backend.formatting import format_amount, format_date
from backend.models import Account, Category, Transaction
from backend.receipt_families import RECEIPT_FAMILIES, group_items_by_family
from backend.templating import templates, user_display_name
from imports.common import ImportParseError, parse_decimal_amount
from backend.i18n import gettext as _t, ngettext

router = APIRouter(prefix="/transactions", tags=["transactions"])


def _other_way(request: Request) -> bool:
    """Whether this request is served in the other way: the extra figures it needs are only computed then."""
    variant = getattr(request.state, "ui_variant", None) or preferences.current_ui_variant()
    return variant == "other_way"


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


def _build_session_context(db: Session, history: list[int], pending_count: int) -> dict:
    """What this visit to La Savane did so far, from the ids the page carries.

    "Filed" are the operations of the history that are now validated, "skipped"
    the ones put aside; the journal lists the last filings, newest first. The
    total is what was filed plus what is still waiting: it grows only when an
    import brings new operations.
    """
    rows = crud.get_transactions_by_ids(db, list(dict.fromkeys(history)))
    filed_ids = [i for i in dict.fromkeys(history) if i in rows and rows[i].validated]
    skipped_ids = [i for i in dict.fromkeys(history) if i in rows and not rows[i].validated]
    journal = [rows[i] for i in reversed(history) if i in rows and rows[i].validated]
    journal = list(dict.fromkeys(journal))[:3]

    breakdown: dict[int, dict] = {}
    for i in filed_ids:
        top = crud.resolve_top_level_category(rows[i].category)
        if top is None:
            continue
        entry = breakdown.setdefault(top.id, {"id": top.id, "name": top.name, "count": 0})
        entry["count"] += 1
    return {
        "session_filed": len(filed_ids),
        "session_skipped": len(skipped_ids),
        "session_left": pending_count,
        "session_total": pending_count + len(filed_ids),
        "session_position": len(filed_ids) + 1,
        "session_percent": round(100 * len(filed_ids) / (pending_count + len(filed_ids)))
        if pending_count + len(filed_ids)
        else 100,
        "session_journal": journal,
        "session_breakdown": sorted(breakdown.values(), key=lambda e: (-e["count"], e["name"])),
        "session_unexpected": sum(1 for i in filed_ids if rows[i].is_unexpected),
        # What this visit filed, for the other way's panel and its review.
        "session_amount": sum((rows[i].amount for i in filed_ids), Decimal("0.00")),
        "session_filed_rows": [rows[i] for i in filed_ids],
    }


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
        "suggestion_rule_keyword": suggestion.get("rule_keyword") if suggestion else None,
        "possible_transfer": (
            not transaction.is_transfer and crud.looks_like_transfer(transaction.raw_label)
        ),
    }
    # The mock-up shows the payment method next to « Valider »: the one a rule
    # proposes for this very category (see _render_payment_step).
    matched_rule = crud.find_matching_rule(db, transaction.raw_label)
    context["suggested_payment_method"] = (
        matched_rule.payment_method
        if matched_rule is not None
        and suggested_category is not None
        and matched_rule.category_id == suggested_category.id
        else None
    )
    # The grid « Ou une autre catégorie » is always on the screen.
    context["categories"] = crud.get_top_level_categories(db)
    return context


# Nombre de lignes de la liste « À suivre » : le début de la file, pas la file
# entière (La Savane peut compter des centaines d'opérations).
UPCOMING_LIMIT = 8


def _build_upcoming_context(db: Session, current: Transaction | None) -> dict:
    # La liste « À suivre » à côté de la carte : les prochaines opérations de
    # la file, dans l'ordre exact où La Savane les présente (même requête que
    # la carte courante), avec la catégorie qu'elle leur proposerait.
    upcoming = crud.get_upcoming_pending_transactions(db, UPCOMING_LIMIT)
    suggestions = crud.suggest_categories_for_transactions(db, upcoming)
    return {
        "upcoming": [
            {
                "transaction": transaction,
                "category": suggestions[transaction.id]["category"]
                if transaction.id in suggestions
                else None,
            }
            for transaction in upcoming
        ],
        "current_id": current.id if current is not None else None,
    }


def _build_board_context(
    db: Session,
    history: list[int],
    *,
    focus: Transaction | None = None,
    q_done: int = 0,
    rule_suggestion: dict | None = None,
    note: dict | None = None,
) -> dict:
    """Everything the other way's La Savane draws: the lot, the current question, the visit.

    `focus` forces the operation shown as the question (one that was just taken
    out of the lot, or just undone); otherwise it is the first of the
    questions. `q_done` is how many questions this visit has answered, carried
    by the page, so that « 3 sur 6 » can be told without any state on the server.
    """
    split = savane.pending_split(db)
    lot = split["lot"]
    questions = list(split["questions"])
    if focus is not None:
        lot = [item for item in lot if item["transaction"].id != focus.id]
        questions = [q for q in questions if q.id != focus.id]
        question_count = len(questions) + 1
        current = focus
    else:
        question_count = len(questions)
        current = questions[0] if questions else None
    lot_count = len(lot)
    pending_count = lot_count + question_count
    session = _build_session_context(db, history, pending_count)

    context = {
        "history": _history_csv(history),
        "pending_count": pending_count,
        **session,
        "lot": lot,
        "lot_count": lot_count,
        "lot_total": sum((item["transaction"].amount for item in lot), Decimal("0.00")),
        "lot_min_confidence": min((item["confidence"] for item in lot), default=None),
        "question_count": question_count,
        "q_done": q_done,
        "q_total": q_done + question_count,
        "q_position": q_done + 1,
        "q_percent": round(100 * q_done / (q_done + question_count)) if q_done + question_count else 100,
        "stage": "lot" if lot_count else ("decision" if current is not None else "bilan"),
        "answer": answers.savane_answer(lot=lot_count, questions=question_count, filed=session["session_filed"]),
        "next_text": answers.next_text(lot=lot_count, questions=question_count),
        "rule_suggestion": rule_suggestion,
        "board_note": note,
        **_build_card_context(db, current),
    }
    if current is not None:
        suggested = context["suggested_category"]
        in_category, total = savane.history_counts(
            savane.history_index(db), current, suggested.id if suggested else None
        )
        context["reason"] = answers.suggestion_reason(
            in_category=in_category,
            total=total,
            rule_keyword=context["suggestion_rule_keyword"],
            based_on_label=context["suggestion_based_on"],
            confidence=context["suggestion_confidence"],
        ) if suggested else None
        context["label_proposals"] = savane.label_proposals(current, context["suggestion_based_on"])
        context["payment_methods"] = crud.get_payment_methods_dict(db)
        alerts = _build_budget_alerts_context(db) if suggested else {"budget_alerts": [], "current_month_key": ""}
        context["card_budget_alert"] = savane.budget_alert_for(alerts["budget_alerts"], suggested)
        context["budget_month_key"] = alerts["current_month_key"]
    if pending_count == 0:
        context["review"] = savane.pillar_review(db, session["session_filed_rows"])
    return context


def _render_next_card(
    request: Request,
    db: Session,
    transaction: Transaction | None,
    history: list[int],
    just_categorized_id: int | None = None,
    rule_suggestion: dict | None = None,
    focus: bool = False,
    q_done: int = 0,
    note: dict | None = None,
):
    if _other_way(request):
        context = {
            "request": request,
            "oob": True,
            **_build_board_context(
                db,
                history,
                focus=transaction if focus else None,
                q_done=q_done,
                rule_suggestion=rule_suggestion,
                note=note,
            ),
        }
        return templates.TemplateResponse("inbox/_card_with_counter.html", context)
    pending_count = crud.count_pending_transactions(db)
    context = {
        "request": request,
        **_build_upcoming_context(db, transaction),
        "history": _history_csv(history),
        "pending_count": pending_count,
        "giraffe_scale": _giraffe_scale(pending_count),
        **_build_session_context(db, history, pending_count),
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
    current_period = period_containing(today, crud.get_budget_start_day(db))

    state = crud.get_or_create_app_state(db)
    show_routine_banner = (
        state.last_routine_month is None or state.last_routine_month < current_period.month
    )
    if not show_routine_banner:
        return {"show_routine_banner": False}

    budget_percent = crud.get_overall_budget_consumption(db, current_period.start, current_period.last_day)
    subscription_count = len(crud.detect_subscriptions(db, today))
    project_savings = crud.get_monthly_project_savings(db, current_period.start, current_period.last_day)

    return {
        "show_routine_banner": True,
        "routine_month_label": current_period.label,
        "routine_budget_percent": round(budget_percent),
        "routine_subscription_count": subscription_count,
        "routine_project_savings": project_savings,
    }


def _build_budget_alerts_context(db: Session) -> dict:
    today = date.today()
    current_period = period_containing(today, crud.get_budget_start_day(db))
    progress = crud.get_budget_progress(db, current_period.start, current_period.last_day)
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
        "current_month_key": current_period.month.strftime("%Y-%m"),
    }


def _build_reader_context(request: Request, db: Session, user) -> dict:
    """The lot as a read-only list, the sentence of the reader and what the role allows."""
    split = savane.pending_split(db)
    waiting = len(split["lot"]) + len(split["questions"])
    admins = [u for u in crud.list_users(db) if u.is_active and u.role == "admin"]
    helper = user_display_name(admins[0]) if admins else None
    return {
        "request": request,
        "lot": split["lot"],
        "answer": answers.reader_answer(waiting, helper),
        "lot_title": answers.reader_lot_title(date.today()),
        "rights": role_rights.capabilities(user.role),
        "questions_count": len(split["questions"]),
    }


@router.get("/inbox", response_class=HTMLResponse)
def inbox(request: Request, db: Session = Depends(get_db)):
    user = getattr(request.state, "user", None)
    if _other_way(request) and user is not None and not check_role_access(user.role, "POST", "/transactions/1/update"):
        # A reader decides nothing here: the other way shows what waits and what the role allows.
        return templates.TemplateResponse("other_way/inbox/reader.html", _build_reader_context(request, db, user))
    if _other_way(request):
        today = date.today()
        context = {
            "request": request,
            "oob": False,
            **_build_board_context(db, []),
            "show_le_cap_midmonth_banner": (
                today - period_containing(today, crud.get_budget_start_day(db)).start
            ).days == 14,
            **_build_routine_banner_context(db),
            **_build_budget_alerts_context(db),
        }
        return templates.TemplateResponse("inbox/index.html", context)
    transaction = crud.get_next_pending_transaction(db)
    pending_count = crud.count_pending_transactions(db)
    today = date.today()
    context = {
        "request": request,
        "history": "",
        "pending_count": pending_count,
        "giraffe_scale": _giraffe_scale(pending_count),
        **_build_session_context(db, [], pending_count),
        # Bannière mi-mois "Le Cap" : localStorage uniquement (comme
        # _budget_alerts.html, qui fournit déjà current_month_key ci-dessous),
        # jamais l'AppState de _build_routine_banner_context — voir
        # inbox/_le_cap_midmonth_banner.html.
        "show_le_cap_midmonth_banner": (
            today - period_containing(today, crud.get_budget_start_day(db)).start
        ).days == 14,
        **_build_upcoming_context(db, transaction),
        **_build_card_context(db, transaction),
        **_build_routine_banner_context(db),
        **_build_budget_alerts_context(db),
    }
    return templates.TemplateResponse("inbox/index.html", context)


@router.post("/routine/dismiss", response_class=HTMLResponse)
def dismiss_routine_banner(db: Session = Depends(get_db)):
    current_period = period_containing(date.today(), crud.get_budget_start_day(db))
    crud.mark_routine_seen(db, current_period.month)
    return HTMLResponse(content="", status_code=200)


def _categorize_and_advance(
    request: Request,
    db: Session,
    transaction: Transaction,
    category: Category,
    label: str | None,
    history: str | None,
    payment_method: str | None = None,
    is_unexpected: bool | None = None,
    q_done: int = 0,
):
    crud.categorize_transaction(
        db, transaction, category, label=label, payment_method=payment_method,
        is_unexpected=is_unexpected,
    )
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
        q_done=q_done + 1,
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
        raise HTTPException(status_code=404, detail=_t("Transaction introuvable"))

    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail=_t("Catégorie introuvable"))

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
        raise HTTPException(status_code=404, detail=_t("Transaction introuvable"))

    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail=_t("Catégorie introuvable"))

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
    unexpected: str | None = Form(None),
    qdone: int = Form(0),
    db: Session = Depends(get_db),
):
    # Étape terminale de l'étape mode de paiement (facultative) : tap sur un
    # mode de paiement OU sur "Passer" (payment_method absent dans ce cas).
    # `unexpected` : la bascule « Imprévu » de la carte (champ caché, "1" quand
    # elle est enfoncée, vide sinon) ; absent = la carte ne la portait pas.
    transaction = db.get(Transaction, transaction_id)
    if transaction is None or transaction.validated:
        raise HTTPException(status_code=404, detail=_t("Transaction introuvable"))

    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail=_t("Catégorie introuvable"))

    payment = payment_method if payment_method in crud.get_payment_methods_dict(db) else None
    return _categorize_and_advance(
        request, db, transaction, category, label, history, payment,
        is_unexpected=None if unexpected is None else bool(unexpected),
        q_done=qdone,
    )


@router.post("/{transaction_id}/skip", response_class=HTMLResponse)
def skip(
    request: Request,
    transaction_id: int,
    label: str | None = Form(None),
    history: str | None = Form(None),
    qdone: int = Form(0),
    db: Session = Depends(get_db),
):
    transaction = db.get(Transaction, transaction_id)
    if transaction is None or transaction.validated:
        raise HTTPException(status_code=404, detail=_t("Transaction introuvable"))

    crud.skip_transaction(db, transaction, label=label)

    new_history = _parse_history(history) + [transaction_id]
    next_transaction = crud.get_next_pending_transaction(db)
    return _render_next_card(request, db, next_transaction, new_history, q_done=qdone)


@router.post("/{transaction_id}/mark-transfer", response_class=HTMLResponse)
def mark_transfer(
    request: Request,
    transaction_id: int,
    label: str | None = Form(None),
    history: str | None = Form(None),
    qdone: int = Form(0),
    db: Session = Depends(get_db),
):
    transaction = db.get(Transaction, transaction_id)
    if transaction is None or transaction.validated:
        raise HTTPException(status_code=404, detail=_t("Transaction introuvable"))

    crud.mark_transaction_as_transfer(db, transaction, label=label)

    new_history = _parse_history(history) + [transaction_id]
    next_transaction = crud.get_next_pending_transaction(db)
    return _render_next_card(request, db, next_transaction, new_history, q_done=qdone + 1)


@router.post("/undo", response_class=HTMLResponse)
def undo(
    request: Request,
    history: str | None = Form(None),
    qdone: int = Form(0),
    db: Session = Depends(get_db),
):
    remaining_history = _parse_history(history)
    if not remaining_history:
        current = crud.get_next_pending_transaction(db)
        return _render_next_card(request, db, current, [], q_done=qdone)

    previous_id = remaining_history.pop()
    transaction = db.get(Transaction, previous_id)
    if transaction is None:
        current = crud.get_next_pending_transaction(db)
        return _render_next_card(request, db, current, remaining_history, q_done=qdone)

    crud.undo_transaction(db, transaction)
    return _render_next_card(
        request, db, transaction, remaining_history, focus=True, q_done=max(qdone - 1, 0)
    )


@router.post("/lot/file", response_class=HTMLResponse)
def file_the_lot(
    request: Request,
    ids: list[int] | None = Form(None),
    history: str | None = Form(None),
    qdone: int = Form(0),
    db: Session = Depends(get_db),
):
    """« Ranger les N » (the other way): file the operations of the lot in one gesture.

    Each one goes into the category Twiga recognized (and the payment method a
    rule proposes for it); only operations still in the lot are filed.
    """
    filed, rule_suggestions = savane.file_lot(db, ids or [])
    new_history = _parse_history(history) + [t.id for t in filed]
    note = {"kind": "lot", "count": len(filed), "rules": len(rule_suggestions)} if filed else None
    return _render_next_card(request, db, None, new_history, q_done=qdone, note=note)


@router.post("/{transaction_id}/leave-lot", response_class=HTMLResponse)
def leave_the_lot(
    request: Request,
    transaction_id: int,
    history: str | None = Form(None),
    qdone: int = Form(0),
    db: Session = Depends(get_db),
):
    """Touch a line of the lot (the other way): it leaves the lot and becomes the question to decide."""
    transaction = db.get(Transaction, transaction_id)
    if transaction is None or transaction.validated:
        raise HTTPException(status_code=404, detail=_t("Transaction introuvable"))
    savane.leave_lot(db, transaction)
    return _render_next_card(
        request, db, transaction, _parse_history(history), focus=True, q_done=qdone
    )


@router.get("/{transaction_id}/categories", response_class=HTMLResponse)
def categories_grid(request: Request, transaction_id: int, db: Session = Depends(get_db)):
    transaction = db.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=404, detail=_t("Transaction introuvable"))

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
    # The operation open in place (the other way); carried by the query string so
    # that a list refreshed by an action keeps its row open.
    open: str | None = None


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
    f_open: str | None = None,
) -> ListFilters:
    return ListFilters(
        f_account, f_category, f_subcategory, f_type, f_date_from, f_date_to,
        f_amount_min, f_amount_max, f_payment_method, f_search, f_sort, f_page,
        f_page_size, f_open or None,
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
    if filters.open:
        params["f_open"] = filters.open
    return urlencode(params)


def list_filter_kwargs(filters: ListFilters) -> dict:
    """The filters of the list as keyword arguments for the crud queries.

    Shared by the list itself and by the CSV export of the "Exporter" button,
    so that both always designate the same operations.
    """
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
    amount_min = _parse_signed_amount(filters.amount_min) if filters.amount_min else None
    amount_max = _parse_signed_amount(filters.amount_max) if filters.amount_max else None

    return dict(
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


def _signed(amount: Decimal) -> str:
    return ("+" if amount > 0 else "") + format_amount(amount)


def _period_context(db: Session, filters: ListFilters) -> dict:
    """The dates in view, named, with the neighbouring budget months to step to."""
    try:
        start = date.fromisoformat(filters.date_from) if filters.date_from else None
        end = date.fromisoformat(filters.date_to) if filters.date_to else None
    except ValueError:
        start = end = None
    if start and end:
        period = period_spanning(start, end, crud.get_budget_start_day(db))
        if period is not None:
            before, after = period.shifted(-1), period.shifted(1)
            return {
                "label": period.label,
                "prev": {"from": before.start.isoformat(), "to": before.last_day.isoformat(), "label": before.label},
                "next": {"from": after.start.isoformat(), "to": after.last_day.isoformat(), "label": after.label},
            }
        return {"label": f"{format_date(start)} → {format_date(end)}", "prev": None, "next": None}
    if start:
        return {"label": _t("Dès le %(date)s") % {"date": format_date(start)}, "prev": None, "next": None}
    if end:
        return {"label": _t("Jusqu'au %(date)s") % {"date": format_date(end)}, "prev": None, "next": None}
    return {"label": _t("Toutes les dates"), "prev": None, "next": None}


def _operations_context(
    db: Session,
    filters: ListFilters,
    kwargs: dict,
    transactions: list[Transaction],
    total: int,
    total_amount: Decimal,
) -> dict:
    """What the other way's list draws on top of the rows.

    The counters of the pills (computed on the filters other than the type and
    the category, which the pills themselves set), the figures of the side panel
    (expenses, income, where the expenses go), the dates in view, Twiga's
    sentence, and what the open row needs (its accounts, categories, ticket).
    """
    scope = {
        key: value
        for key, value in kwargs.items()
        if key not in ("type_filter", "category_id", "category_exact", "uncategorized_only")
    }
    counts = {
        "all": crud.count_transactions(db, **scope),
        "expense": crud.count_transactions(db, **scope, type_filter="expense"),
        "income": crud.count_transactions(db, **scope, type_filter="income"),
        "transfer": crud.count_transactions(db, **scope, type_filter="transfer"),
        "todo": crud.count_transactions(db, **scope, uncategorized_only=True),
    }
    view = {key: value for key, value in kwargs.items() if key != "type_filter"}
    expense_total = -crud.get_transactions_total_amount(db, **view, type_filter="expense")
    income_total = crud.get_transactions_total_amount(db, **view, type_filter="income")
    breakdown = crud.get_expense_breakdown(db, **view)
    period = _period_context(db, filters)

    open_id = _parse_int(filters.open)
    open_detail: dict = {}
    if open_id and any(t.id == open_id for t in transactions):
        receipt_items = crud.get_receipt_items(db, open_id)
        open_detail = {
            "accounts": crud.list_accounts(db),
            "parent_categories": crud.get_top_level_categories(db),
            "receipt_items": receipt_items,
            "receipt_groups": group_items_by_family(receipt_items),
            "receipt_families": RECEIPT_FAMILIES,
            "raw_extracted_text": None,
        }
    answer = answers.operations_answer(
        total=total,
        net=_signed(total_amount),
        todo=counts["todo"],
        period=period["label"],
        search=filters.search or "",
    )
    return {
        "scope_counts": counts,
        "expense_total": expense_total,
        "income_total": income_total,
        "expense_breakdown": breakdown[:6],
        "expense_breakdown_max": (breakdown[0]["total"] if breakdown else Decimal("1")) or Decimal("1"),
        "period": period,
        "answer": answer,
        "open_id": open_id if open_detail else None,
        "open_detail": open_detail,
        "all_accounts": crud.list_accounts(db),
    }


def _build_list_context(db: Session, filters: ListFilters, request: Request | None = None) -> dict:
    page = max(filters.page or 1, 1)
    sort = (
        filters.sort
        if filters.sort in ("date_desc", "date_asc", "amount_desc", "amount_asc")
        else "date_desc"
    )
    parsed_page_size = _parse_int(filters.page_size)
    page_size = parsed_page_size if parsed_page_size in ALLOWED_PAGE_SIZES else DEFAULT_PAGE_SIZE

    shared_filter_kwargs = list_filter_kwargs(filters)

    transactions, total = crud.list_transactions(
        db, page=page, page_size=page_size, sort=sort, **shared_filter_kwargs
    )
    total_amount = crud.get_transactions_total_amount(db, **shared_filter_kwargs)
    total_pages = max(1, math.ceil(total / page_size)) if total else 1

    extra = (
        _operations_context(db, filters, shared_filter_kwargs, transactions, total, total_amount)
        if request is not None and _other_way(request)
        else {}
    )
    return {
        **extra,
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
    if _other_way(request) and not any(key.startswith("f_") for key in request.query_params):
        # The other way opens on the month: a search or a link with filters keeps its own dates.
        period = period_containing(date.today(), crud.get_budget_start_day(db))
        filters.date_from = period.start.isoformat()
        filters.date_to = period.last_day.isoformat()
    filter_parent_id = _parse_int(filters.category) if filters.category not in (None, "", "uncategorized") else None
    filter_parent = db.get(Category, filter_parent_id) if filter_parent_id else None
    filter_subcategories = crud.get_child_categories(db, filter_parent.id) if filter_parent else []

    context = {
        "request": request,
        "accounts": crud.list_accounts(db),
        "filter_parent": filter_parent,
        "filter_subcategories": filter_subcategories,
        "initial_page": True,
        **_build_list_context(db, filters, request),  # inclut déjà "categories" et "payment_methods"
    }
    return templates.TemplateResponse("transactions/index.html", context)


@router.get("/list/content", response_class=HTMLResponse)
def transactions_list_content(
    request: Request,
    filters: ListFilters = Depends(_get_list_filters),
    db: Session = Depends(get_db),
):
    context = {"request": request, **_build_list_context(db, filters, request)}
    return templates.TemplateResponse("transactions/_content.html", context)


def _render_detail(request: Request, db: Session, transaction: Transaction, filters: ListFilters, template: str) -> str:
    """The detail panel of an operation as HTML: its read view, or its edit form."""
    top_level_categories = crud.get_top_level_categories(db)
    receipt_items = crud.get_receipt_items(db, transaction.id)
    context = {
        "request": request,
        "transaction": transaction,
        "accounts": crud.list_accounts(db),
        "parent_categories": top_level_categories,
        "filter_qs": _build_filter_qs(filters),
        "payment_methods": crud.get_payment_methods_dict(db),
        # Ticket detail (transactions/_receipt.html), shown in the same panel
        # — see routers/receipts.py for its actions (upload, lines).
        "receipt_items": receipt_items,
        "receipt_groups": group_items_by_family(receipt_items),
        "receipt_families": RECEIPT_FAMILIES,
        "raw_extracted_text": None,
    }
    return templates.get_template(template).render(context)


def _list_response(
    request: Request,
    db: Session,
    filters: ListFilters,
    success_message: str | None = None,
    detail: "Transaction | str | None" = None,
):
    """The refreshed list and, out of band, the detail panel.

    `detail` is the operation whose read view replaces the panel, "empty" for
    the placeholder (the operation is gone), or None to leave the panel alone.
    """
    context = {"request": request, **_build_list_context(db, filters, request)}
    if success_message:
        context["success_message"] = success_message
    if detail == "empty":
        context["detail_html"] = templates.get_template("transactions/_detail_empty.html").render(
            {"request": request}
        )
    elif detail is not None and not _other_way(request):
        context["detail_html"] = _render_detail(request, db, detail, filters, "transactions/_detail.html")
    return templates.TemplateResponse("transactions/_content.html", context)


def _get_transaction(db: Session, transaction_id: int) -> Transaction:
    transaction = db.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=404, detail=_t("Transaction introuvable"))
    return transaction


def _update_fields(db: Session, transaction: Transaction, **changes) -> Transaction:
    """crud.update_transaction with only some fields changed: the others keep their value."""
    values = dict(
        label=transaction.label,
        category=db.get(Category, transaction.category_id) if transaction.category_id else None,
        amount=transaction.amount,
        transaction_date=transaction.date,
        account=transaction.account,
        is_transfer=transaction.is_transfer,
        payment_method=transaction.payment_method,
        note=transaction.note,
        is_unexpected=transaction.is_unexpected,
    )
    values.update(changes)
    return crud.update_transaction(db, transaction, **values)


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
        raise HTTPException(status_code=404, detail=_t("Compte introuvable"))

    created = crud.create_manual_transaction(
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
    return _list_response(request, db, filters, _t("Opération ajoutée"), detail=created)


@router.get("/{transaction_id}/detail", response_class=HTMLResponse)
def transaction_detail(
    request: Request,
    transaction_id: int,
    filters: ListFilters = Depends(_get_list_filters),
    db: Session = Depends(get_db),
):
    transaction = _get_transaction(db, transaction_id)
    return HTMLResponse(_render_detail(request, db, transaction, filters, "transactions/_detail.html"))


@router.get("/{transaction_id}/edit", response_class=HTMLResponse)
def transaction_edit_form(
    request: Request,
    transaction_id: int,
    filters: ListFilters = Depends(_get_list_filters),
    db: Session = Depends(get_db),
):
    transaction = _get_transaction(db, transaction_id)
    return HTMLResponse(_render_detail(request, db, transaction, filters, "transactions/_edit.html"))


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
    # The edit modal sent "parent_category_id" (the name of its own select);
    # the list filter sent "f_category". Both are still accepted here: the
    # sub-category choice of the bulk panel of La Savane uses this fragment.
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
    transaction = _get_transaction(db, transaction_id)
    category = db.get(Category, int(category_id)) if category_id else None
    account = db.get(Account, int(account_id))
    if account is None:
        raise HTTPException(status_code=404, detail=_t("Compte introuvable"))

    crud.update_transaction(
        db,
        transaction,
        label=label.strip(),
        category=category,
        amount=_parse_signed_amount(amount),
        transaction_date=date.fromisoformat(transaction_date),
        account=account,
        # HTML checkbox: present only when ticked.
        is_transfer=is_transfer is not None,
        payment_method=payment_method if payment_method in crud.get_payment_methods_dict(db) else None,
        note=note,
        is_unexpected=is_unexpected is not None,
    )
    return _list_response(
        request, db, filters, _t("Opération « %(label)s » enregistrée.") % {"label": transaction.label},
        detail=transaction,
    )


@router.post("/{transaction_id}/set-unexpected", response_class=HTMLResponse)
def set_unexpected(
    request: Request,
    transaction_id: int,
    value: str = Form(""),
    filters: ListFilters = Depends(_get_list_filters),
    db: Session = Depends(get_db),
):
    """The "Unexpected expense" switch of the detail panel: saved as soon as it is flipped."""
    transaction = _get_transaction(db, transaction_id)
    _update_fields(db, transaction, is_unexpected=value == "1")
    return _list_response(request, db, filters, detail=transaction)


@router.post("/{transaction_id}/set-note", response_class=HTMLResponse)
def set_note(
    request: Request,
    transaction_id: int,
    note: str = Form(""),
    filters: ListFilters = Depends(_get_list_filters),
    db: Session = Depends(get_db),
):
    """The note field of the detail panel: saved when the field loses focus."""
    transaction = _get_transaction(db, transaction_id)
    _update_fields(db, transaction, note=note)
    return _list_response(request, db, filters)


@router.post("/{transaction_id}/set-category", response_class=HTMLResponse)
def set_category(
    request: Request,
    transaction_id: int,
    category_id: str = Form(""),
    filters: ListFilters = Depends(_get_list_filters),
    db: Session = Depends(get_db),
):
    """"Change the category" of the detail panel: one pick, saved at once."""
    transaction = _get_transaction(db, transaction_id)
    category = db.get(Category, int(category_id)) if category_id else None
    if category_id and category is None:
        raise HTTPException(status_code=404, detail=_t("Catégorie introuvable"))
    _update_fields(db, transaction, category=category)
    return _list_response(request, db, filters, detail=transaction)


@router.post("/{transaction_id}/mark-unexpected", response_class=HTMLResponse)
def mark_unexpected(transaction_id: int, db: Session = Depends(get_db)):
    # "Mark as unexpected" button (La Savane, self-dismissing toast — see
    # inbox/_unexpected_toast.html): the transaction is already saved at this
    # point (the tap comes AFTER the move to the next card), so there is no
    # card context to render here, just the state to set. hx-swap="none" on
    # the template side, nothing to send back.
    transaction = _get_transaction(db, transaction_id)
    crud.mark_transaction_unexpected(db, transaction)
    return HTMLResponse(content="", status_code=200)


@router.post("/{transaction_id}/unvalidate", response_class=HTMLResponse)
def unvalidate_transaction_detail(
    request: Request,
    transaction_id: int,
    filters: ListFilters = Depends(_get_list_filters),
    db: Session = Depends(get_db),
):
    transaction = _get_transaction(db, transaction_id)
    crud.unvalidate_transaction(db, transaction)
    return _list_response(request, db, filters, detail=transaction)


@router.post("/{transaction_id}/delete", response_class=HTMLResponse)
def delete_transaction_detail(
    request: Request,
    transaction_id: int,
    filters: ListFilters = Depends(_get_list_filters),
    db: Session = Depends(get_db),
):
    transaction = _get_transaction(db, transaction_id)
    crud.delete_transaction(db, transaction)
    return _list_response(request, db, filters, detail="empty")


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

    context = {"request": request, **_build_list_context(db, filters, request)}
    if not ids or (category is None and payment is None):
        # Rien à appliquer (aucune case cochée, ou ni catégorie ni mode de
        # paiement renseigné) : catégorie et mode de paiement sont chacun
        # facultatifs et indépendants, appliquer seulement l'un des deux
        # doit marcher normalement (voir crud.bulk_update_transactions).
        return templates.TemplateResponse("transactions/_content.html", context)

    transactions = [t for t in (db.get(Transaction, tid) for tid in ids) if t is not None]
    crud.bulk_update_transactions(db, transactions, category=category, payment_method=payment)

    context = {"request": request, **_build_list_context(db, filters, request)}
    context["success_message"] = ngettext(
        "%(n)s opération mise à jour", "%(n)s opérations mises à jour", len(transactions)
    ) % {"n": len(transactions)}
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

    context = {"request": request, **_build_list_context(db, filters, request)}
    if count:
        context["success_message"] = ngettext(
            "%(n)s opération remise dans La Savane", "%(n)s opérations remises dans La Savane", count
        ) % {"n": count}
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

    context = {"request": request, **_build_list_context(db, filters, request)}
    if count:
        context["success_message"] = ngettext(
            "%(n)s opération marquée comme virement", "%(n)s opérations marquées comme virement", count
        ) % {"n": count}
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

    context = {"request": request, **_build_list_context(db, filters, request)}
    if count:
        context["success_message"] = ngettext(
            "%(n)s opération marquée comme imprévu", "%(n)s opérations marquées comme imprévus", count
        ) % {"n": count}
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

    context = {"request": request, **_build_list_context(db, filters, request)}
    if count:
        context["success_message"] = ngettext(
            "%(n)s opération renvoyée dans La Savane (virement annulé)",
            "%(n)s opérations renvoyées dans La Savane (virement annulé)",
            count,
        ) % {"n": count}
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

    context = {"request": request, **_build_list_context(db, filters, request)}
    if count:
        context["success_message"] = ngettext(
            "%(n)s opération supprimée", "%(n)s opérations supprimées", count
        ) % {"n": count}
    return templates.TemplateResponse("transactions/_content.html", context)
