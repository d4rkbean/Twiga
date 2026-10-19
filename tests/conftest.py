"""Test fixtures: a throwaway PostgreSQL database, built by the real Alembic
migrations and filled with a small demo data set, plus one HTTP client per role.

PostgreSQL is mandatory (crud.py relies on date_trunc, extract, ilike), so the
suite runs against the db-test service of docker-compose.yml: use tools/test.sh.
"""

import os
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

# Must be set before backend.* is imported: authentication and the style guide
# route are read from the environment at import time.
os.environ["AUTH_ENABLED"] = "true"
os.environ["SHOW_DESIGN_SYSTEM"] = "true"

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent

ROLES = ("admin", "editor", "viewer")


def _month_start(offset: int) -> date:
    """First day of the current month shifted by `offset` months (0 or negative)."""
    today = date.today()
    index = today.year * 12 + today.month - 1 + offset
    return date(index // 12, index % 12 + 1, 1)


def _seed_demo_data(db) -> dict[str, int]:
    from backend import crud
    from backend.models import (
        Budget,
        CapEntry,
        PendingCheck,
        Project,
        ProjectMovement,
        ReceiptItem,
        RecurringPattern,
        Rule,
        RuleSuggestion,
        Transaction,
    )

    ids: dict[str, int] = {}

    for role in ROLES:
        ids[f"user_{role}"] = crud.create_user(db, f"test_{role}", "test-password", role).id

    checking = crud.create_account(db, "Checking account", "courant", Decimal("1200.00"))
    savings = crud.create_account(db, "Savings book", "livret", Decimal("5000.00"))
    ids["account_id"] = checking.id

    food = crud.create_category(db, "Test food", None)
    groceries = crud.create_category(db, "Test groceries", food)
    housing = crud.create_category(db, "Test housing", None)
    income = crud.create_category(db, "Test income", None)
    income.excluded_from_budget = True
    salary = crud.create_category(db, "Test salary", income)
    db.commit()
    ids["category_id"] = food.id
    ids["parent_id"] = food.id
    ids["subcategory_id"] = groceries.id

    def add_transaction(label, amount, when, account=checking, category=None, **fields):
        transaction = Transaction(
            date=when,
            label=label,
            raw_label=label.upper(),
            amount=Decimal(amount),
            account_id=account.id,
            category_id=category.id if category else None,
            **fields,
        )
        db.add(transaction)
        db.flush()
        return transaction

    # Four months of categorized history for the dashboard, reports and budgets.
    for offset in (0, -1, -2, -3):
        start = _month_start(offset)
        add_transaction("Salary", "2400.00", start + timedelta(days=1), category=salary, validated=True)
        add_transaction("Rent", "-750.00", start + timedelta(days=2), category=housing, validated=True)
        add_transaction(
            "Supermarket", "-86.40", start + timedelta(days=4), category=groceries, validated=True,
            payment_method="card",
        )

    # Operations still to sort in La Savane (the inbox): current and previous
    # month, one matching a rule, one skipped, one flagged as unexpected.
    today = date.today()
    pending = add_transaction("Carrefour city", "-23.50", today, validated=False)
    add_transaction("Mystery debit", "-12.00", today - timedelta(days=1), validated=False)
    add_transaction("Pharmacy", "-9.90", today - timedelta(days=2), validated=False, is_unexpected=True)
    add_transaction(
        "Bakery", "-3.20", _month_start(-1) + timedelta(days=6), validated=False,
        skipped_at=datetime.utcnow(),
    )
    ids["pending_transaction_id"] = pending.id

    # A validated transfer between the two accounts, and a receipt with lines.
    add_transaction("Transfer out", "-300.00", today, validated=True, is_transfer=True)
    add_transaction("Transfer in", "300.00", today, account=savings, validated=True, is_transfer=True)
    receipt = add_transaction(
        "Hypermarket", "-64.80", today - timedelta(days=3), category=groceries, validated=True,
        note="Monthly shopping",
    )
    db.add_all([
        ReceiptItem(transaction_id=receipt.id, label="Milk", amount=Decimal("-1.20"), family="fresh", sort_order=0),
        ReceiptItem(transaction_id=receipt.id, label="Bread", amount=Decimal("-2.40"), family="bakery", sort_order=1),
    ])
    ids["transaction_id"] = receipt.id

    rule = Rule(keyword="CARREFOUR", category_id=groceries.id)
    db.add(rule)
    db.add(RuleSuggestion(keyword="PHARMACY", category_id=food.id, occurrences=3))
    db.flush()
    ids["rule_id"] = rule.id

    db.add(Budget(category_id=groceries.id, month=_month_start(0), amount=Decimal("300.00")))
    db.add(CapEntry(
        month=_month_start(-1),
        planned_income=Decimal("2400.00"),
        planned_essentiel=Decimal("1200.00"),
        planned_choix=Decimal("600.00"),
        planned_imprevu=Decimal("200.00"),
        intention="Spend less on takeaway",
    ))
    project = Project(
        name="Holidays", target_amount=Decimal("1500.00"), target_date=today + timedelta(days=200),
        current_amount=Decimal("400.00"),
    )
    db.add(project)
    db.flush()
    db.add(ProjectMovement(project_id=project.id, date=today, amount=Decimal("400.00"), note="First deposit"))
    db.add(RecurringPattern(
        label_pattern="STREAMING", amount=Decimal("-11.99"), frequency_days=30, status="active",
        category_id=housing.id,
    ))
    db.add(PendingCheck(
        check_number="0001234", payment_method="cheque", amount=Decimal("-150.00"),
        issued_date=today - timedelta(days=5), recipient="Plumber",
        category_id=housing.id, account_id=checking.id,
    ))
    db.commit()
    return ids


@pytest.fixture(scope="session")
def demo():
    """Builds the schema with Alembic, seeds the demo data, returns the ids."""
    from backend.database import SessionLocal, engine

    # Dropping the schema below is only acceptable on a throwaway database.
    assert engine.url.database.endswith("_test"), (
        f"refusing to reset database {engine.url.database!r}: run the suite with tools/test.sh"
    )
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    command.upgrade(config, "head")

    with SessionLocal() as db:
        return _seed_demo_data(db)


@pytest.fixture(scope="session")
def app(demo):
    from backend.main import app

    return app


@pytest.fixture(scope="session")
def clients(app, demo):
    """One logged-in client per role, plus an anonymous one, keyed by role name."""
    from fastapi.testclient import TestClient

    from backend import auth, crud
    from backend.database import SessionLocal

    # The context manager runs the startup hook, which loads the session
    # secret: tokens must be signed after it.
    with TestClient(app, follow_redirects=False) as anonymous:
        built = {"anonymous": anonymous}
        for role in ROLES:
            with SessionLocal() as db:
                token = auth.open_session(db, crud.get_user(db, demo[f"user_{role}"]), "pytest")
            client = TestClient(app, follow_redirects=False)
            client.cookies.set(auth.SESSION_COOKIE_NAME, token)
            built[role] = client
        yield built


VARIANTS = ("classic", "other_way")


def switch_variant(variant: str) -> None:
    """Puts every demo account on an interface variant (the account wins over
    the cookie, see backend/preferences.py)."""
    from backend.database import SessionLocal
    from backend.models import User

    with SessionLocal() as db:
        db.query(User).update({User.ui_variant: variant})
        db.commit()


@pytest.fixture(params=VARIANTS)
def variant(request, demo, monkeypatch):
    """Runs the test once per interface: the three demo accounts are switched to
    the variant (and the other way is enabled), then put back on Classic."""
    if request.param == "other_way":
        monkeypatch.setenv("ENABLE_OTHER_WAY", "true")
    switch_variant(request.param)
    yield request.param
    switch_variant("classic")
