"""Fidelity of La Savane, bulk processing and Operations to the mock-ups.

Bulk processing: the filter panel (confidence chips with counters, account and
suggested-category filters), grouping of similar labels, "show the next ones",
the filing / sending-back actions and the bulk panel.

Operations: the filter bar and its drawn menus, the selection bar, the detail
panel (read view, edit form, quick gestures), the ticket detail.
"""

import re
from contextlib import contextmanager
from datetime import date
from decimal import Decimal

from backend import crud
from backend.database import SessionLocal
from backend.models import Transaction
from backend.routers import backlog

HTMX = {"HX-Request": "true"}


def _new_pending(label: str, amount: str = "-5.00", raw: str | None = None, **fields) -> int:
    """A throwaway operation waiting to be sorted; callers delete it afterwards."""
    with SessionLocal() as db:
        account = crud.list_accounts(db)[0]
        transaction = Transaction(
            date=fields.pop("when", date(2000, 1, 1)),
            label=label,
            raw_label=raw or label.upper(),
            amount=Decimal(amount),
            account_id=fields.pop("account_id", account.id),
            validated=False,
            **fields,
        )
        db.add(transaction)
        db.commit()
        return transaction.id


def _delete(*transaction_ids: int) -> None:
    with SessionLocal() as db:
        for transaction_id in transaction_ids:
            transaction = db.get(Transaction, transaction_id)
            if transaction is not None:
                crud.delete_transaction(db, transaction)
    backlog._cache["items"] = None


@contextmanager
def pending(*labels: str, **fields):
    """Throwaway pending operations; the suggestion cache is rebuilt around them."""
    backlog._cache["items"] = None
    ids = [_new_pending(label, **fields) for label in labels]
    backlog._cache["items"] = None
    try:
        yield ids
    finally:
        _delete(*ids)


def _rows(html: str) -> list[str]:
    """The `data-row-ids` of the rows of a list fragment, in display order."""
    return re.findall(r'data-row-ids="([^"]*)"', html)


def _content(client, **query) -> str:
    return client.get("/backlog/content", params=query, headers=HTMX).text


# --- the filter panel -------------------------------------------------------


def test_filter_panel_is_the_mock_up_panel_not_a_native_select(clients):
    html = clients["admin"].get("/backlog").text
    for text in (
        "Filtres",
        "Réinitialiser",
        "Rechercher un libellé",
        "Confiance de la suggestion",
        "Sans suggestion",
        "Catégorie suggérée",
        "Regrouper les libellés similaires",
        "Catégorisation en masse",
        "Appliquer à la sélection",
        "Mode de paiement (optionnel)",
    ):
        assert text in html, text
    # Every select of the mock-up is drawn: no native control on this screen.
    assert "<select" not in html
    assert 'href="/transactions/inbox"' in html


def test_chips_carry_the_counters_of_each_confidence_class(clients):
    with pending("Supermarket", raw="SUPERMARKET") as _ids:
        html = _content(clients["admin"])
        chips = re.search(r'id="backlog-chips".*?</div>', html, re.S).group(0)
        counts = [int(n) for n in re.findall(r'tabular-nums font-normal text-secondary">(\d+)<', chips)]
        assert len(counts) == 5
        all_, high, mid, low, none = counts
        assert all_ == high + mid + low + none
        assert high >= 1  # the new row matches four validated "SUPERMARKET" operations


def test_confidence_filter_splits_rows_by_class(clients):
    with pending("Supermarket", raw="SUPERMARKET") as (sure,):
        high = _rows(_content(clients["admin"], suggestion_filter="high"))
        none = _rows(_content(clients["admin"], suggestion_filter="none"))
        assert str(sure) in high
        assert str(sure) not in none
        everything = _rows(_content(clients["admin"]))
        assert set(high) | set(none) <= set(everything)


def test_account_and_category_filters_narrow_the_list(clients, demo):
    with pending("Supermarket", raw="SUPERMARKET") as (sure,):
        in_account = _rows(_content(clients["admin"], account=demo["account_id"]))
        assert str(sure) in in_account
        assert _rows(_content(clients["admin"], account=999999)) == []
        in_category = _rows(_content(clients["admin"], category=demo["category_id"]))
        assert str(sure) in in_category
        # An operation without suggestion has no suggested category.
        with pending("Zzz unknown", raw="ZZZ QQQ") as (unknown,):
            assert str(unknown) not in _rows(_content(clients["admin"], category=demo["category_id"]))


def test_search_filters_by_label(clients):
    with pending("Quokka bakery") as (row,):
        assert _rows(_content(clients["admin"], search="quokka")) == [str(row)]


def test_filters_are_read_from_the_address(clients):
    html = clients["admin"].get("/backlog?search=quokka&suggestion_filter=low").text
    assert "&#34;q&#34;: &#34;quokka&#34;" in html or '"q": "quokka"' in html
    assert "low" in html


# --- grouping ---------------------------------------------------------------


def test_similar_labels_are_grouped_with_a_counter(clients):
    with pending("Quokka Bakery") as (first,):
        second = _new_pending("quokka  bakery", "-7.00")
        backlog._cache["items"] = None
        try:
            single = _rows(_content(clients["admin"], search="quokka"))
            assert single == [str(first), str(second)]
            grouped = _content(clients["admin"], search="quokka", group="1")
            assert _rows(grouped) == [f"{first},{second}"]
            assert "×2" in grouped
            assert "2 opérations" in grouped
            # The amount of a group is the sum of its operations.
            assert "12,00" in grouped
        finally:
            _delete(second)


def test_normalized_label_ignores_case_accents_and_spacing():
    assert backlog._normalize_label("  Boulangerie   DUPAIN ") == backlog._normalize_label("boulangérie dupain")


def test_a_group_is_as_sure_as_its_least_sure_operation():
    rows = backlog._group_rows(
        [
            _item(1, "Shop", 95),
            _item(2, "shop", 72),
        ],
        group=True,
    )
    assert len(rows) == 1
    assert rows[0]["confidence"] == 72
    assert rows[0]["ids"] == [1, 2]


def _item(transaction_id: int, label: str, confidence: int | None) -> dict:
    suggestion = (
        None
        if confidence is None
        else {"category_id": 1, "category_top_id": 1, "category_path": "Food", "confidence": confidence}
    )
    return {
        "transaction_id": transaction_id,
        "label": label,
        "label_key": backlog._normalize_label(label),
        "account_id": 1,
        "amount": Decimal("-1.00"),
        "suggestion": suggestion,
    }


def test_confidence_classes_use_the_mock_up_thresholds():
    assert backlog.confidence_class(None) == "none"
    assert backlog.confidence_class(90) == "high"
    assert backlog.confidence_class(89) == "mid"
    assert backlog.confidence_class(70) == "mid"
    assert backlog.confidence_class(69) == "low"


# --- show the next ones -----------------------------------------------------


def test_the_list_shows_ten_rows_then_offers_the_next_ones(clients):
    labels = [f"Quokka row {n:02d}" for n in range(13)]
    with pending(*labels):
        first = _content(clients["admin"], search="quokka row")
        assert len(_rows(first)) == 10
        assert "10 sur 13" in first
        assert "Afficher les 3 suivantes" in first
        more = _content(clients["admin"], search="quokka row", limit=20)
        assert len(_rows(more)) == 13
        assert "Afficher les" not in more


# --- actions ----------------------------------------------------------------


def _payment_method() -> str:
    with SessionLocal() as db:
        return next(iter(crud.get_payment_methods_dict(db)))


def _category_of(transaction_id: int):
    with SessionLocal() as db:
        transaction = db.get(Transaction, transaction_id)
        return transaction.category_id, transaction.validated, transaction.payment_method, transaction.backlog_rejected_at


def test_filing_a_row_uses_its_own_suggestion(clients, demo):
    with pending("Supermarket", raw="SUPERMARKET") as (row,):
        response = clients["admin"].post("/backlog/validate", data={"ids": str(row)}, headers=HTMX)
        assert response.status_code == 200
        category_id, validated, _pm, _rejected = _category_of(row)
        assert validated and category_id == demo["subcategory_id"]
        assert str(row) not in _rows(response.text)
        assert "Opération « Supermarket » rangée dans" in response.text


def test_filing_a_group_files_every_operation_of_it(clients, demo):
    with pending("Quokka Bakery") as (first,):
        second = _new_pending("Quokka Bakery", "-3.00")
        backlog._cache["items"] = None
        try:
            response = clients["admin"].post(
                "/backlog/validate",
                data={"ids": f"{first},{second}", "category_id": demo["subcategory_id"], "group": "1"},
                headers=HTMX,
            )
            assert "2 opérations rangées dans" in response.text
            assert _category_of(first)[0] == demo["subcategory_id"]
            assert _category_of(second)[0] == demo["subcategory_id"]
        finally:
            _delete(second)


def test_sending_a_row_back_keeps_it_out_of_the_list(clients):
    with pending("Quokka bakery") as (row,):
        response = clients["admin"].post("/backlog/reject", data={"ids": str(row)}, headers=HTMX)
        assert str(row) not in _rows(response.text)
        assert "renvoyée dans La Savane" in response.text
        assert _category_of(row)[3] is not None
        assert _category_of(row)[1] is False  # nothing was categorized


def test_validate_everything_sure_files_only_what_is_sure_enough(clients, demo):
    with pending("Supermarket", raw="SUPERMARKET") as (sure,):
        with pending("Quokka bakery") as (unsure,):
            response = clients["admin"].post(
                "/backlog/bulk-validate", data={"min_confidence": 90, "search": "supermarket"}, headers=HTMX
            )
            assert "confiance ≥ 90 %" in response.text
            assert _category_of(sure)[1] is True
            assert _category_of(unsure)[1] is False


def test_send_back_everything_unsure_spares_rows_without_suggestion(clients):
    with pending("Quokka bakery") as (none,):
        clients["admin"].post("/backlog/bulk-reject", data={"max_confidence": 70, "search": "quokka"}, headers=HTMX)
        assert _category_of(none)[3] is None


def test_apply_to_the_selection_files_with_the_chosen_category_and_payment(clients, demo):
    payment_method = _payment_method()
    with pending("Quokka one", "Quokka two") as (one, two):
        response = clients["admin"].post(
            "/backlog/bulk-apply",
            data={
                "selected_ids": [one, two],
                "apply_category_id": demo["subcategory_id"],
                "apply_payment_method": payment_method,
            },
            headers=HTMX,
        )
        assert "2 opérations rangées dans" in response.text
        assert f"paiement {payment_method}" in response.text
        for row in (one, two):
            category_id, validated, payment, _rejected = _category_of(row)
            assert validated and category_id == demo["subcategory_id"] and payment == payment_method


def test_apply_without_category_keeps_rows_that_have_no_suggestion(clients, demo):
    with pending("Supermarket", raw="SUPERMARKET") as (sure,):
        with pending("Zzz unknown", raw="ZZZ QQQ") as (unknown,):
            response = clients["admin"].post(
                "/backlog/bulk-apply", data={"selected_ids": [sure, unknown]}, headers=HTMX
            )
            assert "1 sans suggestion gardée" in response.text
            assert _category_of(sure)[1] is True
            assert _category_of(unknown)[1] is False


def test_apply_with_a_payment_only_leaves_the_row_in_the_list(clients):
    payment_method = _payment_method()
    with pending("Zzz unknown", raw="ZZZ QQQ") as (row,):
        clients["admin"].post(
            "/backlog/bulk-apply",
            data={"selected_ids": [row], "apply_payment_method": payment_method},
            headers=HTMX,
        )
        category_id, validated, payment, _rejected = _category_of(row)
        assert category_id is None and not validated and payment == payment_method


def test_every_action_answers_with_the_out_of_band_fragments(clients):
    with pending("Quokka bakery") as (row,):
        html = clients["admin"].post("/backlog/reject", data={"ids": str(row)}, headers=HTMX).text
        for marker in ('id="backlog-chips"', 'id="backlog-visible"', 'id="backlog-sync"', 'id="backlog-last-d"'):
            assert marker in html
        assert 'hx-swap-oob="true"' in html


# --- Operations -------------------------------------------------------------


def _operation(clients, **query) -> str:
    return clients["admin"].get("/transactions/list", params=query).text


def test_operations_screen_draws_every_control(clients):
    html = _operation(clients)
    assert "<select" not in html
    for marker in (
        'id="transactions-filters"',
        'id="f_page_size"',
        'id="all-selected-ids-inputs"',
        'name="f_date_from"',
        'name="f_date_to"',
        'name="f_amount_min"',
        'name="f_amount_max"',
        'name="f_category"',
        'name="f_account"',
        'name="f_payment_method"',
        'name="f_sort"',
        'name="f_search"',
    ):
        assert marker in html, marker
    for text in ("+ de critères", "Nouvelle opération", "Réinitialiser", "Tout sélectionner"):
        assert text in html, text


def test_operations_filter_bar_is_one_line_of_drawn_menus_with_reset_on_the_right(clients):
    html = _operation(clients)
    form = html.split('id="transactions-filters"')[1]
    # The line wraps (flex-wrap) instead of squeezing its fields when « Autre montant… » opens.
    line = form.split("lg:flex-wrap lg:items-start")[1].split('x-show="adv"')[0]
    names = ('name="f_date_from"', 'name="f_date_to"', 'name="f_amount_min"', 'name="f_amount_max"', 'aria-label="Catégorie"')
    positions = [line.index(name) for name in names]
    assert positions == sorted(positions)
    # The reset link closes the same line, pushed to the right.
    assert line.index('href="/transactions/list"') > positions[-1]
    assert "lg:ml-auto" in line
    # The amounts are menus of steps, not free fields (the typed one only opens on « Autre montant… »).
    for text in ("Montant min", "Montant max", "Autre montant…", "10 €", "500 €"):
        assert text in line, text
    assert 'name="f_amount_min" :value="amin"' in line
    assert 'name="f_amount_max" :value="amax"' in line
    assert 'placeholder="Montant min"' not in line


def test_operations_amount_filters_keep_the_same_parameters(clients):
    page = clients["admin"].get("/transactions/list?f_amount_min=37&f_amount_max=200").text
    assert "&#34;amin&#34;: &#34;37&#34;" in page
    narrowed = clients["admin"].get("/transactions/list/content?f_amount_min=37&f_amount_max=200", headers=HTMX)
    assert narrowed.status_code == 200


def test_operations_summary_sits_under_the_title_and_follows_the_filters(clients):
    page = _operation(clients)
    assert page.count('id="operations-summary"') == 1
    assert "hx-swap-oob" not in page.split('id="operations-summary"')[1].split(">")[0]
    fragment = clients["admin"].get("/transactions/list/content?f_type=income", headers=HTMX).text
    assert 'id="operations-summary"' in fragment
    assert 'hx-swap-oob="true"' in fragment.split('id="operations-summary"')[1].split(">")[0]


def test_operations_list_has_the_selection_bar_with_every_bulk_action(clients):
    html = clients["admin"].get("/transactions/list/content", headers=HTMX).text
    for url in (
        "/transactions/bulk-apply",
        "/transactions/bulk-mark-transfer",
        "/transactions/bulk-unmark-transfer",
        "/transactions/bulk-mark-unexpected",
        "/transactions/bulk-unvalidate",
        "/transactions/bulk-delete",
    ):
        assert url in html, url
    assert "Retirer virement" in html
    assert "<select" not in html


def test_operations_page_size_menu_is_drawn_and_read_by_the_form(clients):
    fragment = clients["admin"].get("/transactions/list/content?f_page_size=50", headers=HTMX).text
    assert "Afficher : 25 par page" in fragment
    page = _operation(clients, f_page_size=50)
    assert 'id="f_page_size"' in page


def test_operation_detail_is_a_read_view_with_quick_gestures(clients):
    with pending("Quokka bakery", raw="CARTE QUOKKA BAKERY") as (row,):
        html = clients["admin"].get(f"/transactions/{row}/detail", headers=HTMX).text
        assert "Quokka bakery" in html
        assert "CARTE QUOKKA BAKERY" in html  # the bank label
        for text in ("Libellé bancaire", "Dépense imprévue", "Détail du ticket", "Changer la catégorie", "Modifier l'opération"):
            assert text in html, text
        assert "À trier" in html  # no category yet
        assert "Ranger dans La Savane" in html  # still pending
        assert "<select" not in html
        assert "text-danger" in html  # the negative amount, in its verdict colour
        assert f"/transactions/{row}/set-unexpected" in html


def test_operation_edit_form_is_drawn_and_keeps_its_field_names(clients):
    with pending("Quokka bakery") as (row,):
        html = clients["admin"].get(f"/transactions/{row}/edit", headers=HTMX).text
        assert "<select" not in html
        for name in ('name="label"', 'name="category_id"', 'name="payment_method"', 'name="account_id"',
                     'name="is_transfer"', 'name="is_unexpected"', 'name="amount"', 'name="date"', 'name="note"'):
            assert name in html, name
        assert "Inverser le signe" in html
        assert "Enregistrer" in html


def test_new_operation_form_is_drawn(clients):
    html = clients["admin"].get("/transactions/new", headers=HTMX).text
    assert "<select" not in html
    assert "Ajouter l'opération" in html and 'name="category_id"' in html


def test_flipping_the_unexpected_switch_saves_at_once_and_refreshes_the_panel(clients):
    with pending("Quokka bakery") as (row,):
        response = clients["admin"].post(f"/transactions/{row}/set-unexpected", data={"value": "1"}, headers=HTMX)
        assert response.status_code == 200
        with SessionLocal() as db:
            assert db.get(Transaction, row).is_unexpected is True
        # The panel is replaced out of band, with the switch now on.
        assert 'id="transaction-detail-content" hx-swap-oob="innerHTML"' in response.text
        assert 'aria-checked="true"' in response.text
        clients["admin"].post(f"/transactions/{row}/set-unexpected", data={"value": "0"}, headers=HTMX)
        with SessionLocal() as db:
            assert db.get(Transaction, row).is_unexpected is False


def test_the_note_is_saved_when_the_field_changes(clients):
    with pending("Quokka bakery") as (row,):
        clients["admin"].post(f"/transactions/{row}/set-note", data={"note": "Pierre me doit 5 euros"}, headers=HTMX)
        with SessionLocal() as db:
            assert db.get(Transaction, row).note == "Pierre me doit 5 euros"


def test_changing_the_category_from_the_panel_files_the_operation(clients, demo):
    with pending("Quokka bakery") as (row,):
        response = clients["admin"].post(
            f"/transactions/{row}/set-category", data={"category_id": demo["subcategory_id"]}, headers=HTMX
        )
        with SessionLocal() as db:
            transaction = db.get(Transaction, row)
            assert transaction.category_id == demo["subcategory_id"] and transaction.validated
        assert "Test food › Test groceries" in response.text  # the panel shows the new path
        assert "Ranger dans La Savane" not in response.text.split('id="transaction-detail-content"')[1]


def test_saving_the_edit_form_shows_the_read_view_again(clients, demo):
    with pending("Quokka bakery") as (row,):
        response = clients["admin"].post(
            f"/transactions/{row}/update",
            data={"label": "Quokka bakery 2", "amount": "-7,50", "date": "2000-01-02", "account_id": demo["account_id"],
                  "category_id": "", "payment_method": "", "note": ""},
            headers=HTMX,
        )
        assert "Opération « Quokka bakery 2 » enregistrée." in response.text
        assert 'id="transaction-detail-content" hx-swap-oob="innerHTML"' in response.text
        with SessionLocal() as db:
            assert db.get(Transaction, row).amount == Decimal("-7.50")


def test_deleting_an_operation_empties_the_panel(clients):
    row = _new_pending("Quokka bakery")
    response = clients["admin"].post(f"/transactions/{row}/delete", headers=HTMX)
    assert "Choisis une opération pour voir son détail." in response.text
    with SessionLocal() as db:
        assert db.get(Transaction, row) is None
    backlog._cache["items"] = None


def test_removing_the_ticket_detail_keeps_the_operation(clients):
    with pending("Quokka bakery") as (row,):
        clients["admin"].post(f"/transactions/receipts/{row}/items/add", data={"label": "Lait", "amount": "1,20"}, headers=HTMX)
        with SessionLocal() as db:
            assert len(crud.get_receipt_items(db, row)) == 1
        response = clients["admin"].post(f"/transactions/receipts/{row}/clear", headers=HTMX)
        assert response.status_code == 200
        with SessionLocal() as db:
            assert crud.get_receipt_items(db, row) == []
            assert db.get(Transaction, row) is not None


# --- La Savane --------------------------------------------------------------


def test_savane_shows_the_progress_rail_the_grid_and_the_session_panel(clients):
    html = clients["admin"].get("/transactions/inbox").text
    for marker in ('id="inbox-progress"', 'id="inbox-session"', 'id="inbox-counter"', 'id="transaction-card"',
                   'id="inbox-skip-btn"', 'id="inbox-previous-btn"', 'id="inbox-unexpected-btn"'):
        assert marker in html, marker
    for text in ("Journal", "Rangées", "Passées", "Restantes", "Raccourcis clavier", "À suivre"):
        assert text in html, text
    assert "Ou une autre catégorie" in html or "Choisis une catégorie" in html
    assert 'name="history"' in html  # the history really travels with every request


def test_the_history_accumulates_and_feeds_the_session_counters(clients):
    with pending("Quokka one", "Quokka two") as (one, two):
        client = clients["admin"]
        first = client.post(f"/transactions/{one}/skip", data={"history": ""}, headers=HTMX)
        assert f'name="history" value="{one}"' in first.text
        second = client.post(f"/transactions/{two}/skip", data={"history": str(one)}, headers=HTMX)
        assert f'value="{one},{two}"' in second.text
        assert 'id="inbox-session" hx-swap-oob="true"' in second.text
        assert 'id="inbox-progress"' in second.text and 'hx-swap-oob="true"' in second.text.split('id="inbox-progress"')[1][:60]
        session = second.text.split('id="inbox-session"')[1]
        assert ">2</dd>" in session  # two put aside


def test_filing_from_the_card_lists_the_operation_in_the_journal(clients, demo):
    with pending("Quokka journal") as (row,):
        response = clients["admin"].post(
            f"/transactions/{row}/finalize/{demo['subcategory_id']}", data={"history": ""}, headers=HTMX
        )
        journal = response.text.split('id="inbox-session"')[1]
        assert "Quokka journal" in journal
        assert "Test food › Test groceries" in journal
        assert "rangée sur" in response.text  # the sentence under the title


def test_the_card_validates_in_one_gesture_with_the_proposed_category(clients):
    html = clients["admin"].get("/transactions/inbox").text
    # « Valider » files straight away (finalize), the grid below is the other way.
    if 'id="inbox-validate-btn"' in html:
        tag = html.split('id="inbox-validate-btn"')[1].split(">")[0]
        assert "/finalize/" in tag
