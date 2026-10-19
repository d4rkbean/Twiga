"""Loads the demo data set into a blank database and walks the application over it.

Not collected by the normal run (the name does not match test_*.py): tests/
test_demo_data.py starts it in a child pytest against a database of its own,
because it empties the database it runs on.
"""

import os
from datetime import date, timedelta
from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text

from tests.conftest import ROOT
from tests.test_pages import PAGES, request

PASSWORD = os.environ.get("DEMO_PASSWORD", "demo-test-password")


@pytest.fixture(scope="session")
def demo():
    """Overrides the conftest fixture of the same name: the schema, then the demo household."""
    from backend.database import SessionLocal, engine
    from backend.models import Category, ReceiptItem, Rule, Transaction, User
    from tools import demo_data

    assert engine.url.database.endswith("_test"), "refusing to reset a database that is not a test one"
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    command.upgrade(config, "head")

    with SessionLocal() as db:
        demo_data.run(db, PASSWORD)
        by_name = {name: db.scalars(select(Category).where(Category.name == name)).first().id for name in ("Alimentation", "Courses")}
        users = {user.username: user.id for user in db.scalars(select(User))}
        return {
            "user_admin": users["alex"],
            "user_editor": users["sam"],
            "user_viewer": users["lea"],
            "account_id": db.scalars(select(Transaction.account_id)).first(),
            "category_id": by_name["Alimentation"],
            "parent_id": by_name["Alimentation"],
            "subcategory_id": by_name["Courses"],
            "transaction_id": db.scalars(select(ReceiptItem.transaction_id)).first(),
            "pending_transaction_id": db.scalars(select(Transaction.id).where(Transaction.validated.is_(False))).first(),
            "rule_id": db.scalars(select(Rule.id)).first(),
        }


@pytest.mark.parametrize("page", PAGES, ids=lambda page: page.template)
def test_page_answers_with_the_demo_data(clients, demo, variant, page):
    response = request(clients["admin"], page, demo)
    if page.template == "/":
        assert response.status_code == 307
    elif page.template == "/login":
        assert response.status_code == 307
    else:
        assert response.status_code == 200, response.text[:500]
        assert response.content, "empty response"


def test_the_screens_show_the_household(clients, variant):
    admin = clients["admin"]
    assert "Compte joint" in admin.get("/accounts").text
    assert "VIR SEPA VERS LIVRET" in admin.get("/transactions/inbox").text
    assert "Loyer" in admin.get("/transactions/list").text
    assert "Vacances en Bretagne" in admin.get("/projects").text
    assert "0004506" in admin.get("/checks").text
    assert "SPOTIFY" in admin.get("/recurring").text.upper()
    assert "releve_compte-courant" in admin.get("/imports/new").text


def test_the_household(demo):
    from backend import auth, crud, savane
    from backend.database import SessionLocal
    from backend.dates import shift_month
    from backend.models import (
        Account, Budget, CapEntry, Category, ImportLog, PendingCheck, Project, ReceiptItem, Rule,
        RuleSuggestion, Transaction, User,
    )

    with SessionLocal() as db:
        users = {user.username: user for user in db.scalars(select(User))}
        assert set(users) == {"alex", "sam", "lea"}
        assert (users["alex"].role, users["sam"].role, users["lea"].role) == ("admin", "editor", "viewer")
        assert [users[name].display_name for name in ("alex", "sam", "lea")] == ["Alex", "Sam", "Léa"]
        assert users["lea"].last_login is None and users["alex"].last_login is not None
        assert auth.verify_password(db, "alex", PASSWORD) is not None
        assert auth.verify_password(db, "alex", PASSWORD + "x") is None

        balances = {account.name: balance for account, balance in crud.get_account_balances(db)}
        assert set(balances) == {"Compte courant", "Compte joint", "Livret"}
        assert Decimal("2000") < balances["Compte courant"] < Decimal("6000")
        assert Decimal("1000") < balances["Compte joint"] < Decimal("6000")
        assert Decimal("12300") < balances["Livret"] < Decimal("12500")
        assert all(account.balance > 0 for account in db.scalars(select(Account)))  # opening balances

        # Two levels, never "Parent:Child"; Revenus is out of the budgets.
        categories = list(db.scalars(select(Category)))
        assert not [category for category in categories if ":" in category.name]
        assert {category.name for category in categories if category.parent_id is None} == {
            "Alimentation", "Logement", "Transport", "Santé", "Loisirs", "Sorties", "Épargne", "Retraits", "Revenus",
        }
        assert all(category.parent is None or category.parent.parent_id is None for category in categories)
        assert db.scalars(select(Category).where(Category.name == "Revenus")).one().excluded_from_budget

        # Six months of operations, up to today.
        assert db.scalar(select(func.max(Transaction.date))) <= date.today()
        assert db.scalar(select(func.min(Transaction.date))) < date.today() - timedelta(days=150)
        salaries = db.scalar(
            select(func.count()).select_from(Transaction).where(Transaction.raw_label.like("VIR SEPA SALAIRE%"))
        )
        assert salaries >= 10
        assert db.scalar(select(func.count()).select_from(Transaction).where(Transaction.is_transfer.is_(True))) >= 18
        assert db.scalar(select(func.count()).select_from(Transaction).where(Transaction.is_unexpected.is_(True))) >= 2
        assert db.scalar(select(func.count()).select_from(Transaction).where(Transaction.payment_method.is_not(None))) > 300

        # La Savane: a lot, questions, a possible transfer, a label filed 7 times out of 8.
        split = savane.pending_split(db)
        assert 8 <= len(split["lot"]) and len(split["questions"]) >= 4
        assert 12 <= crud.count_pending_transactions(db) <= 25
        bookshop = [t for t in split["questions"] if "LIBRAIRIE LE PHARE" in t.raw_label]
        assert bookshop, "the bookshop must be a question"
        suggestion = crud.suggest_category_with_confidence(db, bookshop[0])
        assert suggestion["category"].name == "Culture"
        assert savane.history_counts(savane.history_index(db), bookshop[0], suggestion["category"].id) == (7, 8)
        assert any(crud.looks_like_transfer(t.raw_label) for t in split["questions"])

        # Rules, proposals, payment methods.
        assert db.scalar(select(func.count()).select_from(Rule)) >= 10
        assert db.scalar(select(func.count()).select_from(Rule).where(Rule.payment_method.is_not(None))) >= 3
        assert db.scalar(select(func.count()).select_from(RuleSuggestion).where(RuleSuggestion.dismissed.is_(False))) == 3

        # Budgets of the current month and the two before, a Cap fixed for last month only.
        first = date.today().replace(day=1)
        for offset in (0, -1, -2):
            month = shift_month(first, offset)
            assert db.scalar(select(func.count()).select_from(Budget).where(Budget.month == month)) >= 5
        last = shift_month(first, -1)
        entry = db.scalars(select(CapEntry).where(CapEntry.month == last)).one()
        assert entry.intention and entry.reflection_unexpected and entry.reflection_regret
        assert entry.reflection_proud and entry.reflection_worked_well
        assert db.scalars(select(CapEntry).where(CapEntry.month == first)).first() is None

        # Projects: ahead, behind, reached.
        today = date.today()
        states = set()
        for project in db.scalars(select(Project)):
            effort = crud.compute_project_effort(db, project.id, today)
            states.add(crud.project_rhythm(project.target_amount, project.current_amount, project.target_date, effort, today)["state"])
        assert states == {"early", "late", "done"}

        # Cheques: three waiting (one issued 12 days ago), two matched.
        waiting = crud.get_outstanding_pending_checks(db)
        assert len(waiting) == 3 and max((today - check.issued_date).days for check in waiting) == 12
        assert len(crud.get_matched_pending_checks(db)) == 2
        assert db.scalar(select(func.count()).select_from(PendingCheck)) == 5

        # A detailed receipt that adds up, and a list of imports.
        receipt_id = db.scalars(select(ReceiptItem.transaction_id)).first()
        receipt = db.get(Transaction, receipt_id)
        items = crud.get_receipt_items(db, receipt_id)
        assert len(items) >= 15 and sum(item.amount for item in items) == -receipt.amount
        assert len({item.family for item in items}) >= 8
        assert db.scalar(select(func.count()).select_from(ImportLog)) >= 6


def test_the_marker_and_the_guards(demo, monkeypatch):
    from backend.database import SessionLocal
    from backend.models import Account, Transaction
    from tools import demo_data

    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(Transaction))

        # A database that holds operations is never filled again...
        with pytest.raises(demo_data.DemoRefused, match="already holds"):
            demo_data.run(db, PASSWORD)
        assert db.scalar(select(func.count()).select_from(Transaction)) == before

        # ...but a pure demo database can be reset, and gives the same household again.
        assert demo_data.demo_blocker(db) is None
        summary = demo_data.run(db, PASSWORD, reset=True)
        assert summary["operations"] == before

        # Anything that changed the users, the accounts or the operations blocks the reset.
        account = db.scalars(select(Account)).first()
        db.add(Transaction(date=date.today(), label="Real", raw_label="REAL", amount=Decimal("-1.00"), account_id=account.id))
        db.commit()
        with pytest.raises(demo_data.DemoRefused, match="changed"):
            demo_data.run(db, PASSWORD, reset=True)
        assert db.scalar(select(func.count()).select_from(Transaction)) == before + 1

        # No marker, no reset.
        main = db.scalars(select(Account).where(Account.name == demo_data.MAIN_ACCOUNT)).one()
        main.notes = None
        db.commit()
        with pytest.raises(demo_data.DemoRefused, match="marker"):
            demo_data.run(db, PASSWORD, reset=True)

    # The password is mandatory, and is not read from anywhere else.
    monkeypatch.delenv("DEMO_PASSWORD", raising=False)
    assert demo_data.main([]) == 2
