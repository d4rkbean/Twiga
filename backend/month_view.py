"""Where the month stands, pillar by pillar: the figures behind "Mon mois" of the other way.

The Classic screen shows what the plan consumed (crud.get_pillar_actuals) next
to what La Savane would add. The other way's screen answers a sharper question:
which pillar is the tightest, and what does tidying La Savane change? So every
amount is split in two, *sorted* (a validated expense, or one tagged unexpected)
and *still to sort* (what waits in La Savane), and a pillar's share counts both:
"86 % of its budget, tidying included".

Operations that wait without an envelope to join ("hors budget": no category
proposed, or one that no budget carries) are listed one by one under their
pillar, so that the sum of the lines always reaches the gauge above them.

Pure data, no HTML: the sentence is `answers.month_answer`, the page is
`other_way/cap/mid.html`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend import crud
from backend.answers import ALMOST_AT, EXCEEDED_AT, WATCH_AT, Verdict, verdict
from backend.budget_month import BudgetPeriod, period_containing
from backend.models import Category, Transaction
from backend.pillars import PILLAR_ORDER

ZERO = Decimal("0.00")
_RANK = {"ok": 0, "watch": 1, "almost": 2, "exceeded": 3}


@dataclass
class Line:
    """A budgeted category inside a pillar."""

    category: Category
    budget: Decimal
    spent: Decimal
    pending: Decimal
    pending_ops: list[Transaction] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        return self.spent + self.pending

    @property
    def percent(self) -> Decimal:
        return self.total / self.budget * 100 if self.budget else ZERO

    @property
    def verdict(self) -> Verdict:
        return verdict(self.percent)

    @property
    def rest(self) -> Decimal:
        return self.budget - self.total

    @property
    def spent_width(self) -> float:
        return min(100.0, float(self.spent / self.budget * 100)) if self.budget else 0.0

    @property
    def pending_width(self) -> float:
        if not self.budget:
            return 0.0
        return max(0.0, min(100.0 - self.spent_width, float(self.pending / self.budget * 100)))


@dataclass
class Pillar:
    code: str
    planned: Decimal
    spent: Decimal = ZERO
    pending: Decimal = ZERO
    lines: list[Line] = field(default_factory=list)
    # Operations in La Savane that no envelope of this pillar takes.
    loose: list[Transaction] = field(default_factory=list)
    # The expenses tagged unexpected (the Imprévus pillar is made of events).
    events: list[Transaction] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        return self.spent + self.pending

    @property
    def percent(self) -> Decimal:
        return self.total / self.planned * 100 if self.planned else ZERO

    @property
    def verdict(self) -> Verdict:
        return verdict(self.percent)

    @property
    def spent_width(self) -> float:
        return min(100.0, float(self.spent / self.planned * 100)) if self.planned else 0.0

    @property
    def pending_width(self) -> float:
        if not self.planned:
            return 0.0
        return max(0.0, min(100.0 - self.spent_width, float(self.pending / self.planned * 100)))

    @property
    def loose_total(self) -> Decimal:
        return sum((-t.amount for t in self.loose), ZERO)


@dataclass
class MonthView:
    period: BudgetPeriod
    today: date
    day: int
    days: int
    rhythm: int
    days_left: int
    entry: object | None
    pillars: list[Pillar]  # tightest first
    income_planned: Decimal | None
    income_real: Decimal
    planned_total: Decimal
    spent_total: Decimal
    pending_total: Decimal
    savings_planned: Decimal | None
    savings_so_far: Decimal
    left: Decimal
    fixed: dict


def _rank(pillar: Pillar) -> tuple:
    return (_RANK[pillar.verdict.key], pillar.percent)


def build_month_view(db: Session, today: date | None = None) -> MonthView:
    today = today or date.today()
    start_day = crud.get_budget_start_day(db)
    period = period_containing(today, start_day)
    start, end = period.start, period.last_day
    entry = crud.get_cap_entry_for_month(db, period.month)

    envelopes = crud.get_budget_envelopes(db, start, end)
    budget_categories = {item["category"].id: item["category"] for item in envelopes}
    children = _children_by_parent(db)

    transactions = list(
        db.execute(
            select(Transaction)
            .where(
                Transaction.date >= start,
                Transaction.date <= end,
                Transaction.amount < 0,
                Transaction.is_transfer.is_(False),
            )
            .options(selectinload(Transaction.category).selectinload(Category.parent))
            .order_by(Transaction.date)
        )
        .scalars()
        .all()
    )
    sums = crud.get_pillar_budget_sums(db, period.month)
    planned = {
        "essentiel": sums["essentiel"],
        "choix": sums["choix"],
        "imprevu": entry.planned_imprevu if entry is not None else ZERO,
    }
    pillars = {code: Pillar(code, planned[code]) for code in PILLAR_ORDER}

    # Sorted: validated, or tagged unexpected (an event, whatever its category).
    pending_ops = []
    for transaction in transactions:
        pillar = crud.resolve_transaction_pillar(transaction)
        if transaction.validated or transaction.is_unexpected:
            pillars[pillar].spent += -transaction.amount
            if transaction.is_unexpected:
                pillars[pillar].events.append(transaction)
        else:
            pending_ops.append(transaction)

    # Still to sort: into the envelope La Savane would choose, else "hors budget".
    suggestions = crud.suggest_categories_for_transactions(db, pending_ops)
    pending_by_budget: dict[int, Decimal] = {}
    pending_ops_by_budget: dict[int, list[Transaction]] = {}
    for transaction in pending_ops:
        suggestion = suggestions.get(transaction.id)
        owner = None
        suggested = None
        if suggestion is not None:
            suggested = suggestion["category"]
            if suggested.id in budget_categories:
                owner = suggested
            elif suggested.parent_id in budget_categories:
                owner = budget_categories[suggested.parent_id]
            if owner is not None and crud.resolve_category_pillar(suggested) != crud.resolve_budget_pillar(
                owner, children.get(owner.id, [])
            ):
                owner = None
        if owner is not None:
            pending_by_budget[owner.id] = pending_by_budget.get(owner.id, ZERO) - transaction.amount
            pending_ops_by_budget.setdefault(owner.id, []).append(transaction)
            pillars[crud.resolve_budget_pillar(owner, children.get(owner.id, []))].pending += -transaction.amount
        else:
            code = crud.resolve_category_pillar(suggested) if suggested is not None else crud.resolve_category_pillar(None)
            pillars[code].loose.append(transaction)
            pillars[code].pending += -transaction.amount

    for item in envelopes:
        owner = item["category"]
        code = crud.resolve_budget_pillar(owner, children.get(owner.id, []))
        pillars[code].lines.append(
            Line(
                owner,
                item["budget"],
                item["spent"],
                pending_by_budget.get(owner.id, ZERO),
                pending_ops_by_budget.get(owner.id, []),
            )
        )
    for pillar in pillars.values():
        pillar.lines.sort(key=lambda line: line.percent, reverse=True)

    ordered = sorted(pillars.values(), key=_rank, reverse=True)
    income_real = crud.get_income_total(db, start, today)
    planned_total = sum(planned.values(), ZERO)
    spent_total = sum((p.spent for p in pillars.values()), ZERO)
    pending_total = sum((p.pending for p in pillars.values()), ZERO)
    income_reference = entry.planned_income if entry is not None else income_real
    days = (period.end - period.start).days
    day = (today - period.start).days + 1
    return MonthView(
        period=period,
        today=today,
        day=day,
        days=days,
        rhythm=round(day / days * 100),
        days_left=days - day,
        entry=entry,
        pillars=ordered,
        income_planned=entry.planned_income if entry is not None else None,
        income_real=income_real,
        planned_total=planned_total,
        spent_total=spent_total,
        pending_total=pending_total,
        savings_planned=(entry.planned_income - planned_total) if entry is not None else None,
        savings_so_far=income_reference - spent_total - pending_total,
        left=planned_total - spent_total - pending_total,
        fixed=_fixed_charges(db, period, today),
    )


def _children_by_parent(db: Session) -> dict[int, list[Category]]:
    children: dict[int, list[Category]] = {}
    for category in db.execute(select(Category)).scalars().all():
        if category.parent_id is not None:
            children.setdefault(category.parent_id, []).append(category)
    return children


def _fixed_charges(db: Session, period: BudgetPeriod, today: date) -> dict:
    """The monthly charges that come out by themselves (rent, power, internet...).

    The recurring-payments detection already knows them (crud.detect_recurring_patterns);
    here we keep the active monthly ones and say, for this budget month, which
    were already taken and which are still expected.
    """
    overview = crud.get_recurring_patterns_overview(db, today)
    items = []
    for pattern in overview["recurring_patterns"]:
        if pattern["frequency"] != "monthly" or pattern["activity_status"] != "active":
            continue
        if pattern.get("status") == "ignored":
            continue
        taken = period.start <= pattern["last_date"] <= period.last_day
        items.append(
            {
                "label": pattern["last_label"],
                "account": pattern["last_account"],
                "amount": pattern["amount"],
                "day": pattern["last_date"].day if taken else pattern["next_expected"].day,
                "taken": taken,
                "category": pattern["category"],
            }
        )
    items.sort(key=lambda item: (not item["taken"], item["day"]))
    taken_items = [item for item in items if item["taken"]]
    categories = {item["category"].name for item in taken_items if item["category"] is not None}
    return {
        "items": items,
        "total": sum((item["amount"] for item in items), ZERO),
        "taken_count": len(taken_items),
        "all_taken": bool(items) and len(taken_items) == len(items),
        "category": next(iter(categories)) if len(categories) == 1 else None,
    }
