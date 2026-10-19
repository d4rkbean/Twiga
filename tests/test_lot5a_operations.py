"""Operations of the other way (lot 5a): search first, a row that opens in place."""

from datetime import date
from decimal import Decimal

from backend import crud
from tests.conftest import switch_variant
from tests.test_lot5a_savane import other_way  # noqa: F401  (fixture)

HTMX = {"HX-Request": "true"}
MONTH_START = date.today().replace(day=1).isoformat()


def test_counters_and_breakdown_follow_the_filters(demo):
    from backend.database import SessionLocal

    with SessionLocal() as db:
        everything = crud.count_transactions(db)
        expenses = crud.count_transactions(db, type_filter="expense")
        income = crud.count_transactions(db, type_filter="income")
        transfers = crud.count_transactions(db, type_filter="transfer")
        assert expenses + income + transfers == everything
        assert crud.count_transactions(db, search="zzz-nothing") == 0

        breakdown = crud.get_expense_breakdown(db, type_filter="income")  # the type is ignored
        assert breakdown and all(entry["total"] > Decimal("0") for entry in breakdown)
        totals = [entry["total"] for entry in breakdown]
        assert totals == sorted(totals, reverse=True)
        assert sum(totals) == crud.get_expense_total(db, date(2000, 1, 1), date(2100, 1, 1))


def test_the_page_opens_on_the_month_and_carries_the_screen(clients, other_way):
    html = clients["editor"].get("/transactions/list").text
    assert 'id="ops-head"' in html and 'id="ops-pills"' in html and 'id="ops-side"' in html
    assert 'id="transactions-filters"' in html and 'id="transactions-content"' in html and 'id="ops-sync"' in html
    assert "opsBoardB(" in html
    assert MONTH_START in html  # the bare page is the current month
    assert html.count("btn-primary") <= 2  # « Ranger les N à trier » (and « Ranger dans… », hidden)


def test_a_search_keeps_all_the_dates(clients, other_way):
    html = clients["editor"].get("/transactions/list?f_search=super").text
    assert MONTH_START not in html.split("opsBoardB(")[1].split(")\"")[0]


def test_a_row_opens_in_place_and_keeps_its_filters(clients, other_way, demo):
    transaction_id = demo["transaction_id"]
    html = clients["admin"].get(f"/transactions/list/content?f_open={transaction_id}", headers=HTMX).text
    assert 'id="tx-open"' in html
    assert f"/transactions/{transaction_id}/set-category?f_open={transaction_id}" in html
    assert f"/transactions/{transaction_id}/update?f_open={transaction_id}" in html
    assert f"receipt-section-{transaction_id}" in html  # the ticket, as in Classic
    closed = clients["admin"].get("/transactions/list/content", headers=HTMX).text
    assert 'id="tx-open"' not in closed


def test_an_action_answers_the_list_and_its_out_of_band_parts(clients, other_way, demo):
    transaction_id = demo["transaction_id"]
    response = clients["admin"].post(
        f"/transactions/{transaction_id}/set-category?f_open={transaction_id}",
        data={"category_id": str(demo["category_id"])},
        headers=HTMX,
    )
    assert response.status_code == 200
    for landing in ("ops-head", "ops-pills", "ops-side", "ops-sync"):
        assert f'id="{landing}"' in response.text, landing
    assert 'id="tx-open"' in response.text


def test_bulk_apply_answers_in_the_other_way_too(clients, other_way, demo):
    response = clients["admin"].post(
        "/transactions/bulk-apply",
        data={"selected_ids": [demo["transaction_id"]], "category_id": str(demo["category_id"]), "payment_method": ""},
        headers=HTMX,
    )
    assert response.status_code == 200 and 'id="ops-side"' in response.text


def test_the_new_operation_form_is_the_other_ways(clients, other_way):
    html = clients["admin"].get("/transactions/new", headers=HTMX).text
    assert 'hx-post="/transactions/create' in html and "resetTransactionDetail" not in html


def test_classic_operations_are_untouched(clients, demo):
    switch_variant("classic")
    html = clients["editor"].get("/transactions/list").text
    assert "opsBoard(" in html and "opsBoardB" not in html and 'id="ops-head"' not in html
