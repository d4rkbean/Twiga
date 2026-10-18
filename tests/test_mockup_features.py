"""Features shown by the redesign mock-ups: La Savane "À suivre" queue and the
"Imprévu" toggle, the filtered operations export, the Panorama "Enveloppes"
card, the live panel of Le Cap and the "Save now" backup.
"""

from datetime import date
from decimal import Decimal

from backend import crud
from backend.database import SessionLocal
from backend.models import Category, Transaction


def _new_pending(label: str, amount: str = "-5.00", **fields) -> int:
    """A throwaway operation waiting in La Savane; callers delete it afterwards."""
    with SessionLocal() as db:
        account = crud.list_accounts(db)[0]
        transaction = Transaction(
            date=date(2000, 1, 1),  # oldest date: first in the queue
            label=label,
            raw_label=label.upper(),
            amount=Decimal(amount),
            account_id=account.id,
            validated=False,
            **fields,
        )
        db.add(transaction)
        db.commit()
        return transaction.id


def _delete(transaction_id: int) -> None:
    with SessionLocal() as db:
        transaction = db.get(Transaction, transaction_id)
        if transaction is not None:
            crud.delete_transaction(db, transaction)


# --- 1. La Savane: "À suivre" and "Imprévu" ---------------------------------


def test_inbox_shows_the_upcoming_queue_in_presentation_order(clients):
    first = _new_pending("Zzz first in line")
    try:
        html = clients["admin"].get("/transactions/inbox").text
        assert 'id="inbox-upcoming"' in html
        assert "À suivre" in html
        assert "Zzz first in line" in html
        # The queue is read-only: no button posts from a row.
        assert "hx-post" not in html.split('id="inbox-upcoming-list"')[1].split("</ul>")[0]
        with SessionLocal() as db:
            upcoming = crud.get_upcoming_pending_transactions(db, 8)
            assert upcoming[0].id == crud.get_next_pending_transaction(db).id == first
            # Same order as the cards: labels appear in the page in queue order.
            labels = [t.label for t in upcoming]
        positions = [html.index(label) for label in labels]
        assert positions == sorted(positions)
    finally:
        _delete(first)


def test_upcoming_list_is_refreshed_out_of_band_after_a_skip(clients):
    first = _new_pending("Zzz first in line")
    second = _new_pending("Zzz second in line")
    try:
        response = clients["admin"].post(f"/transactions/{first}/skip", data={"history": ""})
        assert response.status_code == 200
        assert 'id="inbox-upcoming-list"' in response.text
        assert 'id="inbox-upcoming-list" hx-swap-oob="true"' in response.text
        assert 'id="inbox-upcoming-count" hx-swap-oob="true"' in response.text
        # The skipped one goes to the back of the queue, the next one is current.
        assert "Zzz second in line" in response.text
    finally:
        _delete(first)
        _delete(second)


def test_inbox_card_has_the_unexpected_toggle_and_its_shortcut(clients):
    html = clients["admin"].get("/transactions/inbox").text
    assert 'id="inbox-unexpected-btn"' in html
    assert 'name="unexpected"' in html
    # Still a single amber button on the screen.
    assert html.count("btn-primary") <= 1
    # The help dialog documents the shortcut.
    assert "Marquer comme imprévu" in html
    script = clients["admin"].get("/static/js/inbox-shortcuts.js").text
    assert "inbox-unexpected-btn" in script


def test_finalize_with_the_unexpected_toggle_keeps_the_category(clients, demo):
    pending = _new_pending("Zzz unexpected repair")
    try:
        category_id = demo["subcategory_id"]
        response = clients["admin"].post(
            f"/transactions/{pending}/finalize/{category_id}",
            data={"unexpected": "1", "history": ""},
        )
        assert response.status_code == 200
        with SessionLocal() as db:
            transaction = db.get(Transaction, pending)
            assert transaction.is_unexpected is True
            assert transaction.validated is True
            assert transaction.category_id == category_id
    finally:
        _delete(pending)


def test_finalize_without_the_toggle_pressed_clears_the_flag(clients, demo):
    pending = _new_pending("Zzz not unexpected", is_unexpected=True)
    try:
        # The toggle is rendered pressed because the operation was flagged.
        with SessionLocal() as db:
            assert db.get(Transaction, pending).is_unexpected is True
        response = clients["admin"].post(
            f"/transactions/{pending}/finalize/{demo['subcategory_id']}",
            data={"unexpected": "", "history": ""},
        )
        assert response.status_code == 200
        with SessionLocal() as db:
            assert db.get(Transaction, pending).is_unexpected is False
    finally:
        _delete(pending)


def test_finalize_without_the_field_leaves_the_flag_alone(clients, demo):
    pending = _new_pending("Zzz untouched", is_unexpected=True)
    try:
        clients["admin"].post(
            f"/transactions/{pending}/finalize/{demo['subcategory_id']}", data={"history": ""}
        )
        with SessionLocal() as db:
            assert db.get(Transaction, pending).is_unexpected is True
    finally:
        _delete(pending)


# --- 2. Operations: the "Exporter" button -----------------------------------


def _csv_rows(response) -> list[list[str]]:
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    lines = response.text.lstrip("﻿").splitlines()
    return [line.split(";") for line in lines]


def test_operations_page_has_a_secondary_export_button(clients):
    html = clients["admin"].get("/transactions/list").text
    assert 'id="transactions-export"' in html
    assert 'href="/export/transactions.csv' in html
    # It reads the filter form at click time and is not amber.
    assert "new FormData(document.getElementById('transactions-filters'))" in html
    export_tag = html.split('id="transactions-export"')[1].split(">")[0]
    assert "btn-primary" not in export_tag


def test_export_without_filters_keeps_every_operation(clients):
    rows = _csv_rows(clients["admin"].get("/export/transactions.csv"))
    assert rows[0][:4] == ["date", "libelle_simplifie", "libelle_brut", "montant"]
    labels = {row[1] for row in rows[1:]}
    assert {"Salary", "Rent", "Supermarket", "Transfer in"} <= labels


def test_export_only_contains_the_filtered_operations(clients):
    rows = _csv_rows(
        clients["admin"].get("/export/transactions.csv?f_search=rent&f_type=expense")
    )
    body = rows[1:]
    assert body, "the filter must keep the rent operations"
    assert {row[1] for row in body} == {"Rent"}
    # The same filters designate the same operations in the list.
    listing = clients["admin"].get(
        "/transactions/list/content?f_search=rent&f_type=expense",
        headers={"HX-Request": "true"},
    ).text
    assert "Rent" in listing and "Salary" not in listing


def test_export_follows_the_type_amount_and_account_filters(clients, demo):
    transfers = _csv_rows(clients["admin"].get("/export/transactions.csv?f_type=transfer"))
    assert {row[1] for row in transfers[1:]} == {"Transfer out", "Transfer in"}
    # Amount filters compare the absolute value, like the list does.
    big = _csv_rows(clients["admin"].get("/export/transactions.csv?f_type=transfer&f_amount_min=400"))
    assert len(big) == 1
    small = _csv_rows(clients["admin"].get("/export/transactions.csv?f_type=transfer&f_amount_max=400"))
    assert {row[1] for row in small[1:]} == {"Transfer out", "Transfer in"}
    one_account = _csv_rows(
        clients["admin"].get(f"/export/transactions.csv?f_account={demo['account_id']}&f_search=salary")
    )
    assert {row[1] for row in one_account[1:]} == {"Salary"}
    assert {row[6] for row in one_account[1:]} == {"Checking account"}


def test_export_amounts_use_the_ascii_hyphen(clients):
    response = clients["admin"].get("/export/transactions.csv?f_search=rent")
    assert "-750.00" in response.text
    assert "−" not in response.text  # the typographic minus is for the screen only


def test_export_with_no_match_is_just_the_header(clients):
    rows = _csv_rows(clients["admin"].get("/export/transactions.csv?f_search=zzzzznomatch"))
    assert len(rows) == 1
