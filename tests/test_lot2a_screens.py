"""La Savane, bulk processing and operations after the "Girafe" redesign (lot 2a).

Checks what the new markup promises: a true minus sign, one amber action per
screen, no emoji in the interface, ink amounts, the type filter as a segmented
control that still filters.
"""

from decimal import Decimal

from backend.formatting import format_amount_as

MINUS = "−"


def test_negative_amounts_use_the_true_minus_sign():
    assert format_amount_as(Decimal("-48"), "fr") == f"{MINUS}48,00 €"
    assert format_amount_as(Decimal("-1234.5"), "en-US") == f"{MINUS}€1,234.50"
    assert format_amount_as(Decimal("12"), "fr") == "12,00 €"


def test_inbox_has_at_most_one_amber_action_and_no_emoji(clients):
    html = clients["admin"].get("/transactions/inbox").text
    # Valider is the only amber button; Passer and the others are secondary.
    assert html.count("btn-primary") <= 1
    assert 'id="inbox-skip-btn"' in html
    assert "btn btn-secondary" in html
    assert "⏭" not in html  # the old "next track" emoji on Passer
    # The shortcut targets read by inbox-shortcuts.js are still there.
    assert 'id="transaction-card"' in html
    assert "shortcut-category-btn" in html or 'id="inbox-validate-btn"' in html


def test_inbox_card_border_carries_the_account_not_the_confidence(clients):
    html = clients["admin"].get("/transactions/inbox").text
    assert "border-success" not in html
    assert "border-warning" not in html
    assert "border-color: #" in html


def test_operations_amounts_are_ink_with_a_minus_sign(clients):
    html = clients["admin"].get(
        "/transactions/list/content", headers={"HX-Request": "true"}
    ).text
    assert f"{MINUS}750,00" in html
    # A negative amount is not a verdict: no red, no green on the list rows.
    assert "text-danger" not in html
    assert "text-success" not in html
    # Uncategorized operations carry a word, not a bare gray label.
    assert "À trier" in html or "badge-neutral" in html


def test_operations_type_filter_is_a_segmented_control_that_filters(clients):
    page = clients["admin"].get("/transactions/list").text
    # The four tabs of the mock-up; "Virements" moved to the "Tous types" menu.
    for tab in ("Toutes", "Dépenses", "Recettes", "À trier"):
        assert f">{tab}</button>" in page
    assert page.count('name="f_type"') == 1
    income = clients["admin"].get(
        "/transactions/list/content?f_type=income", headers={"HX-Request": "true"}
    ).text
    assert "Salary" in income
    assert "Rent" not in income


def test_operations_keeps_the_ids_read_by_the_scripts(clients):
    html = clients["admin"].get("/transactions/list").text
    for marker in ('id="transactions-filters"', 'id="f_page_size"', 'id="all-selected-ids-inputs"'):
        assert marker in html


def test_bulk_processing_page_renders_filters_and_rows(clients):
    html = clients["admin"].get("/backlog").text
    assert 'id="backlog-search-input"' in html
    assert 'id="backlog-chips"' in html
    assert 'data-row-ids=' in html
