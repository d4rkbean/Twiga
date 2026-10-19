"""The budget month: the reference period every screen counts "this month" on."""

import re
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

import pytest

from backend import crud
from backend.budget_month import BUDGET_START_DAYS, budget_months_within, period_containing, period_of_month, period_spanning
from backend.dates import month_label, month_range
from backend.database import SessionLocal
from backend.models import Transaction


# --- The reference function --------------------------------------------------


def test_start_on_the_first_is_the_calendar_month():
    for year in (2023, 2024, 2025, 2026):
        for month in range(1, 13):
            period = period_of_month(year, month, 1)
            assert (period.start, period.last_day) == month_range(year, month)
            assert period.month == date(year, month, 1)
            assert period.label == month_label(year, month)
            assert period_containing(period.start, 1) == period
            assert period_containing(period.last_day, 1) == period


def test_a_date_before_the_start_day_belongs_to_the_previous_month():
    period = period_containing(date(2026, 3, 9), 10)
    assert period.month == date(2026, 2, 1)
    assert (period.start, period.last_day) == (date(2026, 2, 10), date(2026, 3, 9))
    assert period.end == date(2026, 3, 10)


def test_the_start_day_itself_opens_the_new_month():
    period = period_containing(date(2026, 3, 10), 10)
    assert period.month == date(2026, 3, 1)
    assert period.start == date(2026, 3, 10)
    assert period_containing(date(2026, 3, 9), 10).month == date(2026, 2, 1)


def test_february_is_short_with_the_first_and_never_loses_a_day():
    assert period_of_month(2026, 2, 1).last_day == date(2026, 2, 28)
    assert period_of_month(2028, 2, 1).last_day == date(2028, 2, 29)
    # Starting on the 15th, February spans 28 days from the 15th to the 14th.
    february = period_of_month(2026, 2, 15)
    assert (february.start, february.last_day) == (date(2026, 2, 15), date(2026, 3, 14))
    assert (february.end - february.start).days == monthrange(2026, 2)[1]


@pytest.mark.parametrize("start_day", BUDGET_START_DAYS)
def test_periods_tile_the_calendar_without_gap_or_overlap(start_day):
    day = date(2025, 11, 1)
    previous = period_containing(day, start_day)
    while day < date(2027, 2, 1):
        current = period_containing(day, start_day)
        assert current.start <= day <= current.last_day
        if current != previous:
            assert current.start == previous.end
        previous = current
        day += timedelta(days=1)


def test_year_end_and_year_start():
    january = period_containing(date(2027, 1, 3), 15)
    assert january.month == date(2026, 12, 1)
    assert (january.start, january.end) == (date(2026, 12, 15), date(2027, 1, 15))
    assert january.shifted(1).month == date(2027, 1, 1)
    assert january.shifted(-1).month == date(2026, 11, 1)
    assert january.shifted(-1).end == january.start


def test_shifted_keeps_the_start_day():
    period = period_containing(date(2026, 1, 20), 10)
    assert period.shifted(-1).start == date(2025, 12, 10)
    assert period.shifted(-1).last_day == date(2026, 1, 9)
    assert period.shifted(2).start == date(2026, 3, 10)


def test_period_spanning_recognises_only_whole_budget_months():
    assert period_spanning(date(2026, 2, 10), date(2026, 3, 9), 10) is not None
    assert period_spanning(date(2026, 2, 1), date(2026, 2, 28), 10) is None
    assert period_spanning(date(2026, 2, 1), date(2026, 2, 28), 1) is not None
    assert period_spanning(date(2026, 2, 1), date(2026, 2, 27), 1) is None


def test_budget_months_within_picks_the_months_starting_in_the_range():
    # With the 1st: every month from the range start to its end, as before.
    assert budget_months_within(date(2026, 1, 1), date(2026, 3, 31), 1) == (date(2026, 1, 1), date(2026, 3, 1))
    assert budget_months_within(date(2026, 1, 15), date(2026, 3, 31), 1) == (date(2026, 2, 1), date(2026, 3, 1))
    # With the 10th: one budget month runs 10 March to 9 April and is named March.
    assert budget_months_within(date(2026, 3, 10), date(2026, 4, 9), 10) == (date(2026, 3, 1), date(2026, 3, 1))
    assert budget_months_within(date(2026, 1, 1), date(2026, 3, 31), 10) == (date(2026, 1, 1), date(2026, 3, 1))


# --- Screens ------------------------------------------------------------------


@pytest.fixture
def start_day():
    """Sets the household's start day for one test and puts it back to the 1st."""

    def set_day(day: int) -> None:
        with SessionLocal() as db:
            crud.get_cap_settings(db).budget_start_day = day
            db.commit()

    yield set_day
    set_day(1)


@pytest.fixture
def lone_expense():
    """Adds one expense on a date and removes it at the end of the test."""
    ids = []

    def add(when: date, amount: str, label: str) -> None:
        with SessionLocal() as db:
            account = crud.list_accounts(db)[0]
            transaction = Transaction(
                date=when, label=label, raw_label=label.upper(), amount=-Decimal(amount),
                account_id=account.id, validated=True,
            )
            db.add(transaction)
            db.commit()
            ids.append(transaction.id)

    yield add
    with SessionLocal() as db:
        for transaction_id in ids:
            db.query(Transaction).filter(Transaction.id == transaction_id).delete()
        db.commit()


def _panorama(clients, period: str) -> str:
    return clients["admin"].get(f"/dashboard?period={period}").text


def test_panorama_with_the_first_is_the_calendar_month(clients):
    today = date.today()
    html = _panorama(clients, "mois")
    assert month_label(today.year, today.month) in html
    with SessionLocal() as db:
        assert crud.get_budget_start_day(db) == 1
    start, end = month_range(today.year, today.month)
    period = period_containing(today, 1)
    assert (period.start, period.last_day) == (start, end)


def _period_expense(html: str) -> Decimal:
    return Decimal(re.search(r"periodExpense = ([0-9.]+)", html).group(1))


def test_panorama_with_the_10th_counts_the_9th_in_the_previous_month(clients, start_day, lone_expense):
    today = date.today()
    start_day(10)
    current = period_containing(today, 10)
    previous = current.shifted(-1)
    lone_expense(current.start - timedelta(days=1), "7777.00", "Day before the budget month")

    this_month = _panorama(clients, "mois")
    assert current.label in this_month
    last_month = _panorama(clients, "mois-dernier")
    assert previous.label in last_month

    with SessionLocal() as db:
        assert _period_expense(this_month) == crud.get_expense_total(db, current.start, current.last_day)
        assert _period_expense(last_month) == crud.get_expense_total(db, previous.start, previous.last_day)
    assert _period_expense(last_month) >= Decimal("7777.00")
    assert _period_expense(this_month) < Decimal("7777.00")


def test_reports_month_follows_the_start_day(clients, start_day):
    today = date.today()
    start_day(10)
    current = period_containing(today, 10)
    html = clients["admin"].get("/reports").text
    assert current.label in html
    assert clients["admin"].get(f"/reports?period_type=mois&month={current.month.month}&year={current.month.year}").status_code == 200


def test_budgets_page_opens_on_the_budget_month(clients, start_day):
    today = date.today()
    start_day(15)
    current = period_containing(today, 15)
    html = clients["admin"].get("/budgets").text
    assert current.label in html


def test_budget_progress_reads_the_budget_of_the_named_month(start_day):
    from backend.models import Budget, Category

    start_day(10)
    with SessionLocal() as db:
        category = db.query(Category).filter(Category.name == "Test housing").one()
        db.add_all([
            Budget(category_id=category.id, month=date(2031, 3, 1), amount=Decimal("111.00")),
            Budget(category_id=category.id, month=date(2031, 4, 1), amount=Decimal("222.00")),
        ])
        db.commit()
        try:
            march = period_of_month(2031, 3, 10)
            rows = crud.get_budget_progress(db, march.start, march.last_day)
            assert [row["budget"] for row in rows if row["category"].id == category.id] == [Decimal("111.00")]
        finally:
            db.query(Budget).filter(Budget.month.in_([date(2031, 3, 1), date(2031, 4, 1)])).delete()
            db.commit()
