"""What La Savane of the other way needs on top of the queue: the lot, the reasons, the review.

Classic goes through the queue one operation at a time. The other way splits it
in two: the **lot** (the operations Twiga recognizes for sure, filed in one
gesture) and the **questions** (everything else, one at a time). The split, the
reason given with each suggestion ("Déjà rangée là 7 fois sur 8"), the labels
offered for a rename and the review of the pillars at the end of a visit all
live here, read-only on the data except for `file_lot` and `leave_lot`.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import crud
from backend.budget_month import period_containing
from backend.models import Category, Transaction

# A suggestion at least this sure belongs to the lot. Same threshold as the
# « ≥ 90 % » class of the bulk screen (routers/backlog.py).
SURE_CONFIDENCE = 90

# ...provided the history does not contradict it: a merchant filed in that
# category less than this share of the time is a question, however well its
# label matches (a bookshop that was once filed under Press is asked about).
SURE_HISTORY_SHARE = 0.9

# How many operations of the history are read to count how often a label was
# filed in a category; the most recent ones first.
HISTORY_LIMIT = 5000


def category_path(category: Category | None) -> str:
    """"Parent › Child" for a sub-category, the bare name for a top-level one."""
    if category is None:
        return ""
    return f"{category.parent.name} › {category.name}" if category.parent else category.name


def category_top(category: Category | None) -> Category | None:
    return crud.resolve_top_level_category(category)


# --- The lot and the questions ---------------------------------------------


def pending_split(db: Session) -> dict:
    """The waiting queue, split into the lot and the questions, both in queue order.

    The lot holds the operations whose suggestion is sure (SURE_CONFIDENCE, a
    rule of the user, or a history that agrees with it) and that were not left
    aside: leaving an operation out of the lot stamps it as
    skipped, which is also what « Passer » does, so it moves to the end of the
    questions and never comes back into the lot by itself.
    """
    pending = list(db.execute(crud._pending_queue_stmt()).scalars().all())
    suggestions = crud.suggest_categories_for_transactions(db, pending)
    index = history_index(db)
    lot: list[dict] = []
    questions: list[Transaction] = []
    for transaction in pending:
        suggestion = suggestions.get(transaction.id)
        sure = (
            suggestion is not None
            and suggestion["confidence"] >= SURE_CONFIDENCE
            and transaction.skipped_at is None
        )
        if sure and not suggestion.get("rule_keyword"):
            in_category, total = history_counts(index, transaction, suggestion["category"].id)
            sure = total == 0 or in_category / total >= SURE_HISTORY_SHARE
        if sure:
            category = suggestion["category"]
            top = category_top(category)
            lot.append(
                {
                    "transaction": transaction,
                    "category": category,
                    "path": category_path(category),
                    "top_id": top.id if top else category.id,
                    "confidence": suggestion["confidence"],
                    "payment_method": transaction.payment_method,
                }
            )
        else:
            questions.append(transaction)
    return {
        "lot": lot,
        "questions": questions,
        "lot_total": sum((item["transaction"].amount for item in lot), Decimal("0.00")),
        "min_confidence": min((item["confidence"] for item in lot), default=None),
    }


def file_lot(db: Session, ids: list[int]) -> tuple[list[Transaction], list[dict]]:
    """File the given operations of the lot in the category Twiga proposes.

    Only operations that are in the lot right now are filed: an id that left it
    (filed elsewhere, left aside) is ignored. The payment method is the one a
    rule proposes for that very category, as « Oui » does on a single card.
    Returns the filed operations and the rule suggestions this created.
    """
    wanted = set(ids)
    split = pending_split(db)
    filed: list[Transaction] = []
    rule_suggestions: list[dict] = []
    seen: set[tuple[str, int]] = set()
    for item in split["lot"]:
        transaction = item["transaction"]
        if transaction.id not in wanted:
            continue
        category = item["category"]
        rule = crud.find_matching_rule(db, transaction.raw_label)
        payment = rule.payment_method if rule is not None and rule.category_id == category.id else None
        maybe_rule = crud.maybe_rule_suggestion(db, transaction, category)
        crud.categorize_transaction(db, transaction, category, payment_method=payment)
        filed.append(transaction)
        if maybe_rule:
            key = (maybe_rule["keyword"].strip().lower(), maybe_rule["category_id"])
            if key not in seen:
                seen.add(key)
                rule_suggestions.append(maybe_rule)
    return filed, rule_suggestions


def leave_lot(db: Session, transaction: Transaction) -> Transaction:
    """Take an operation out of the lot: it becomes a question, to decide by hand."""
    return crud.skip_transaction(db, transaction)


# --- Why Twiga proposes a category -----------------------------------------


def history_index(db: Session) -> dict[frozenset[str], Counter]:
    """How often each merchant was filed in each category, from the filed history.

    A merchant is the set of significant words of the bank label (dates, card
    numbers and bank wrapping dropped), so "CB LIBRAIRIE 06/09" and "CB
    LIBRAIRIE 21/08" are the same merchant. Read-only.
    """
    stmt = (
        select(Transaction.raw_label, Transaction.category_id)
        .where(
            Transaction.validated.is_(True),
            Transaction.category_id.is_not(None),
            Transaction.is_transfer.is_(False),
        )
        .order_by(Transaction.id.desc())
        .limit(HISTORY_LIMIT)
    )
    index: dict[frozenset[str], Counter] = {}
    for raw_label, category_id in db.execute(stmt).all():
        words = crud._significant_words(raw_label or "")
        if words:
            index.setdefault(words, Counter())[category_id] += 1
    return index


def history_counts(index: dict[frozenset[str], Counter], transaction: Transaction, category_id: int | None) -> tuple[int, int]:
    """(times this merchant was filed in `category_id`, times it was filed at all)."""
    counter = index.get(crud._significant_words(transaction.raw_label or ""))
    if not counter or category_id is None:
        return 0, 0
    return counter[category_id], sum(counter.values())


# --- Labels offered for a rename -------------------------------------------

_SMALL_WORDS = {"de", "du", "des", "la", "le", "les", "et", "au", "aux", "en", "sur", "chez"}
_DATE = re.compile(r"\b\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?\b")


def clean_bank_label(raw_label: str) -> str:
    """The bank label without its wrapping: no card prefix, date or number, in words."""
    text = _DATE.sub(" ", raw_label or "")
    words = []
    for word in re.split(r"[^\w']+", text):
        if not word or any(char.isdigit() for char in word):
            continue
        if word.upper() in crud._GENERIC_RULE_TERMS or word.upper() in {"PAIEMENT", "ACHAT", "FACTURE"}:
            continue
        words.append(word.lower())
    if not words:
        return ""
    cleaned = [word if i and word in _SMALL_WORDS else word.capitalize() for i, word in enumerate(words)]
    return " ".join(cleaned)


def label_proposals(transaction: Transaction, based_on_label: str | None = None) -> list[dict]:
    """Up to two labels to put in place of the current one: from the history, then cleaned.

    Each is {"text", "source"} with source "history" or "cleaned"; the current
    label is never offered back.
    """
    current = (transaction.label or transaction.raw_label or "").strip().lower()
    proposals: list[dict] = []
    seen = {current}
    for text, source in ((based_on_label, "history"), (clean_bank_label(transaction.raw_label), "cleaned")):
        text = (text or "").strip()
        if text and text.lower() not in seen:
            seen.add(text.lower())
            proposals.append({"text": text, "source": source})
    return proposals


# --- Budget alert of a category --------------------------------------------


def budget_alert_for(alerts: list[dict], category: Category | None) -> dict | None:
    """The budget alert (≥ 80 % consumed) of the top-level category of `category`, if any."""
    top = category_top(category)
    if top is None:
        return None
    return next((alert for alert in alerts if alert["category_id"] == top.id), None)


# --- The review at the end of a visit --------------------------------------


def pillar_review(db: Session, filed: list[Transaction], today: date | None = None) -> dict:
    """Where the pillars of the month stand now that the visit is done.

    For each spending pillar: what is spent, the plan, the share of the plan,
    and how much of the spending this visit filed (so the bar can show what it
    just added). Savings: what is left of the income once everything is filed,
    against the goal of the month's cap when there is one. The plan is the cap
    of the month if it was fixed, else the budgets of the month.
    """
    today = today or date.today()
    period = period_containing(today, crud.get_budget_start_day(db))
    start, end = period.start, period.last_day
    actuals = crud.get_pillar_actuals(db, start, end)
    entry = crud.get_cap_entry_for_month(db, period.month)
    if entry is not None:
        planned = {
            "essentiel": entry.planned_essentiel,
            "choix": entry.planned_choix,
            "imprevu": entry.planned_imprevu,
        }
    else:
        planned = crud.get_pillar_budget_sums(db, period.month)

    added = {code: Decimal("0.00") for code in crud.PILLAR_ORDER}
    for transaction in filed:
        if transaction.amount < 0 and not transaction.is_transfer and start <= transaction.date <= end:
            added[crud.resolve_transaction_pillar(transaction)] += -transaction.amount

    pillars = []
    for code in crud.PILLAR_ORDER:
        plan = planned.get(code) or Decimal("0.00")
        spent = actuals.get(code, Decimal("0.00"))
        delta = added[code]
        percent = round(spent / plan * 100) if plan > 0 else None
        before = max(spent - delta, Decimal("0.00"))
        before_width = min(round(before / plan * 100), 100) if plan > 0 else 0
        delta_width = (
            max(0, min(round(spent / plan * 100), 100) - before_width) if plan > 0 else 0
        )
        pillars.append(
            {
                "code": code,
                "spent": spent,
                "planned": plan,
                "percent": percent,
                "delta": delta,
                "before_width": before_width,
                "delta_width": delta_width,
            }
        )

    income = crud.get_income_total(db, start, end)
    left = income - sum(actuals.values(), Decimal("0.00"))
    goal = entry.savings_goal if entry is not None else None
    savings = {
        "left": left,
        "goal": goal,
        "percent": round(left / goal * 100) if goal and goal > 0 else None,
    }
    return {"pillars": pillars, "savings": savings, "month": period.month, "label": period.label}
