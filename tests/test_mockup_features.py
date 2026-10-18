"""Features shown by the redesign mock-ups: La Savane "À suivre" queue and the
"Imprévu" toggle, the filtered operations export, the Panorama "Enveloppes"
card, the live panel of Le Cap and the "Save now" backup.
"""

from datetime import date, datetime
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


# --- 3. Panorama: the "Enveloppes" card --------------------------------------


def _month_bounds() -> tuple[date, date]:
    from backend.dates import month_range

    today = date.today()
    return month_range(today.year, today.month)


def test_envelopes_add_what_is_still_in_la_savane_to_each_budget(demo):
    start, end = _month_bounds()
    with SessionLocal() as db:
        envelopes = crud.get_budget_envelopes(db, start, end)
        food = next(item for item in envelopes if item["category"].id == demo["subcategory_id"])
        # "Carrefour city" (23.50) is proposed in the groceries sub-category by
        # the CARREFOUR rule, which carries the budget.
        assert food["pending"] == Decimal("23.50")
        expected = (food["spent"] + Decimal("23.50")) / food["budget"] * 100
        assert food["projected_percentage"] == expected
        assert food["projected_percentage"] > food["percentage"]
        # The flagged-unexpected pharmacy and the transfers never count.
        assert food["pending"] < Decimal("30.00")
        # The envelopes follow the chosen account.
        savings = next(a for a in crud.list_accounts(db) if a.name == "Savings book")
        for item in crud.get_budget_envelopes(db, start, end, savings.id):
            assert item["pending"] == 0


def test_panorama_shows_one_envelopes_card_instead_of_budgets_at_risk(clients):
    html = clients["admin"].get("/dashboard").text
    assert "Enveloppes" in html
    assert "Budgets à risque" not in html
    assert "Test groceries" in html
    assert "à trier" in html
    assert "Avec le tri : " in html
    # The verdict is doubled with a word and links to "Mon mois".
    section = html.split('id="tour-budget-section"')[1].split("</section>")[0]
    assert "dans la cible" in section or "à surveiller" in section or "presque atteint" in section
    assert 'href="/cap/mid"' in section
    assert "amount-blur" in section


def test_panorama_envelopes_follow_the_account_filter(clients):
    from backend.models import Account

    with SessionLocal() as db:
        savings_id = db.query(Account).filter(Account.name == "Savings book").one().id
    html = clients["admin"].get(
        f"/dashboard/content?account_id={savings_id}", headers={"HX-Request": "true"}
    ).text
    section = html.split('id="tour-budget-section"')[1].split("</section>")[0]
    assert "Test groceries" in section
    assert "Avec le tri" not in section  # nothing of this account waits in La Savane


# --- 4. Le Cap: the live panel -------------------------------------------------


def _fixer_html(clients) -> str:
    response = clients["admin"].post("/cap/step2", data={})
    assert response.status_code == 200
    return response.text


def test_cap_fixer_step_has_a_live_panel_computed_in_the_browser(clients):
    html = _fixer_html(clients)
    assert "en direct" in html
    assert 'aria-label="Le plan en direct"' in html
    for text in ("Ressources du mois", "Total réparti", "Épargne qui reste", "Tu répartis plus que tes ressources."):
        assert text in html
    # The panel reads the form's own Alpine state: no new request behind it.
    panel = html.split('aria-label="Le plan en direct"')[1]
    assert "hx-get" not in panel and "hx-post" not in panel
    assert "x-text=\"fmt(totalDepenses)\"" in panel
    assert "x-text=\"fmt(savings)\"" in panel
    assert 'x-show="couvert < 0"' in panel


def test_cap_fixer_panel_compares_with_the_month_before_per_pillar(clients):
    html = _fixer_html(clients)
    assert "pilier par pilier" in html
    # The three pillars, and last month's real figures embedded for the page script.
    for code in ("essentiel", "choix", "imprevu"):
        assert f"code: '{code}'" in html
    assert "precedent:" in html
    assert "du plan" in html and "dans la cible" in html


def test_cap_fixer_form_fields_are_unchanged(clients):
    html = _fixer_html(clients)
    form = html.split('hx-post="/cap/save"')[1].split("</form>")[0]
    for name in ("planned_income", "planned_imprevu", "savings_withdrawal", "intention", "amount_"):
        assert f'name="{name}' in form
    assert html.count("btn-primary") <= 1


# --- 5. Settings: "Sauvegarder maintenant" -----------------------------------


def _set_last_backup(value):
    from backend.models import AppState

    with SessionLocal() as db:
        state = crud.get_or_create_app_state(db)
        state.last_backup_at = value
        db.commit()
        assert db.get(AppState, 1).last_backup_at == value


def test_settings_data_section_shows_when_no_backup_was_made(clients):
    _set_last_backup(None)
    html = clients["admin"].get("/settings").text
    assert "Sauvegarder maintenant" in html
    assert "Aucune sauvegarde pour l'instant" in html
    assert 'action="/export/backup"' in html
    # A secondary action: the only amber button of the screen is not this one.
    button = html.split('id="backup-form"')[1].split("</form>")[0]
    assert "btn-secondary" in button and "btn-primary" not in button


def test_backup_downloads_the_full_export_and_records_the_date(clients):
    _set_last_backup(None)
    response = clients["admin"].post("/export/backup")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert "attachment" in response.headers["content-disposition"]
    backup = response.json()
    # The very same document as the full JSON export, the one restore reads.
    reference = clients["admin"].get("/export/json").json()
    assert backup.keys() == reference.keys()
    assert len(backup["transactions"]) == len(reference["transactions"])

    from backend.models import AppState

    with SessionLocal() as db:
        saved = db.get(AppState, 1).last_backup_at
    assert saved is not None
    assert (datetime.now() - saved).total_seconds() < 60

    status = clients["admin"].get("/export/backup/status").text
    assert "Dernière sauvegarde : le " in status
    assert saved.strftime("%d/%m/%Y") in status
    assert f" à {saved.strftime('%H:%M')}" in status
    assert "Aucune sauvegarde" not in status
    assert "Dernière sauvegarde" in clients["admin"].get("/settings").text


def test_backup_is_refused_to_non_admins_and_leaves_the_date_alone(clients):
    _set_last_backup(None)
    for role in ("editor", "viewer"):
        assert clients[role].post("/export/backup").status_code == 403
    assert clients["anonymous"].post("/export/backup").status_code in (303, 401, 403)
    from backend.models import AppState

    with SessionLocal() as db:
        assert db.get(AppState, 1).last_backup_at is None


def test_settings_hide_the_backup_button_from_non_admins(clients):
    for role in ("editor", "viewer"):
        assert "Sauvegarder maintenant" not in clients[role].get("/settings").text
