"""La Savane of the other way (lot 5a): the lot, the questions, the reasons, the review.

Pure sentences (backend/answers.py), the helpers of backend/savane.py, and the
screen itself through the routes it keeps: the lot filed in one gesture, a line
taken out of it, the budget alert, the rule offered after « Oui ».
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from markupsafe import Markup

from backend import answers, crud, savane
from backend.models import Category, RuleSuggestion, Transaction
from tests.conftest import switch_variant

HTMX = {"HX-Request": "true"}


# --- The sentences ---------------------------------------------------------


def test_the_headline_names_the_lot_and_the_questions():
    answer = answers.savane_answer(lot=8, questions=6, filed=0)
    assert "8 sur 14" in answer.title
    assert "6 autres" in answer.detail

    only_lot = answers.savane_answer(lot=3, questions=0, filed=0)
    assert "3" in only_lot.title and "d'un geste" in only_lot.detail

    last = answers.savane_answer(lot=1, questions=0, filed=0)
    assert "celle-ci" in last.title


def test_the_headline_after_the_lot_counts_the_questions_then_the_visit():
    assert answers.savane_answer(lot=0, questions=6, filed=8).title == "Il reste 6 questions."
    assert answers.savane_answer(lot=0, questions=1, filed=8).title == "Il reste 1 question."
    done = answers.savane_answer(lot=0, questions=0, filed=14)
    assert done.title == "Tout est rangé." and "14 opérations" in done.detail
    clean = answers.savane_answer(lot=0, questions=0, filed=0)
    assert clean.title == "Rien à ranger."


def test_next_text_says_what_follows():
    assert "6 questions" in answers.next_text(lot=8, questions=6)
    assert answers.next_text(lot=2, questions=0) == "Après le lot, le bilan du mois."
    assert "5 autres" in answers.next_text(lot=0, questions=6)
    assert answers.next_text(lot=0, questions=1) == "Après celle-ci, le bilan du mois."
    assert "quand tout est rangé" in answers.next_text(lot=0, questions=0)


def test_the_reason_goes_from_the_rule_to_the_history_to_the_look_alike():
    assert answers.suggestion_reason(in_category=0, total=0, rule_keyword="ORANGE") == "Ta règle « ORANGE » le range là."
    assert answers.suggestion_reason(in_category=7, total=8) == "Déjà rangée là 7 fois sur 8."
    assert (
        answers.suggestion_reason(in_category=0, total=0, based_on_label="Librairie", confidence=64)
        == "Ressemble à « Librairie » (64 %)."
    )
    assert "pas de piste" in answers.suggestion_reason(in_category=0, total=0)


def test_amounts_in_a_sentence_are_blurred_and_values_escaped():
    answer = answers.masse_answer(
        count=8, categories=4, amount="360,24 €", min_confidence=95, pending=14
    )
    assert answer.title == "Le lot tient en 4 catégories."
    assert 'class="amount-blur">360,24 €</span>' in answer.detail
    assert "95 % et plus" in answer.detail

    # What a user typed stays a plain string (the template escapes it); only our
    # own markup is trusted.
    operations = answers.operations_answer(total=2, net="1 €", todo=0, period="Mars", search="<b>x</b>")
    assert not isinstance(operations.title, Markup) and isinstance(operations.detail, Markup)


def test_the_bulk_headline_covers_the_empty_states():
    assert answers.masse_answer(count=0, categories=0, amount="0 €", min_confidence=None, pending=5).title == "Rien de sûr à ranger en masse."
    assert answers.masse_answer(count=0, categories=0, amount="0 €", min_confidence=None, pending=0).title == "Tout est rangé."
    searching = answers.masse_answer(count=0, categories=0, amount="0 €", min_confidence=None, pending=5, searching=True)
    assert searching.title == "Rien de sûr ne correspond."


def test_the_operations_headline_follows_the_selection_the_search_then_the_month():
    selected = answers.operations_answer(total=25, net="+2 882,16 €", todo=14, period="Septembre 2026", selected=3, selected_sum="−45,60 €")
    assert "3 opérations choisies" in selected.title and "amount-blur" in selected.title
    searching = answers.operations_answer(total=5, net="−10 €", todo=14, period="Septembre 2026", search="orange")
    assert "5 opérations pour « orange »" in searching.title
    nothing = answers.operations_answer(total=0, net="0 €", todo=0, period="Septembre 2026", search="zzz")
    assert nothing.title == "Rien ne correspond à « zzz »."
    todo = answers.operations_answer(total=25, net="+2 882,16 €", todo=14, period="Septembre 2026")
    assert todo.title == "14 opérations attendent encore une catégorie."
    assert "Septembre 2026 : 25 opérations" in todo.detail
    calm = answers.operations_answer(total=25, net="+2 882,16 €", todo=0, period="Septembre 2026")
    assert calm.title == "25 opérations, tout est rangé."


# --- Labels ----------------------------------------------------------------


def test_a_bank_label_is_cleaned_of_its_wrapping():
    assert savane.clean_bank_label("CB LIBRAIRIE 06/09") == "Librairie"
    assert savane.clean_bank_label("CB SUPERMARCHE DU QUARTIER 15/09 CB*1264") == "Supermarche du Quartier"
    assert savane.clean_bank_label("VIR SEPA 12345") == ""


def test_label_proposals_come_from_the_history_then_the_cleaned_label():
    transaction = Transaction(label="CB LIBRAIRIE 06/09", raw_label="CB LIBRAIRIE 06/09")
    proposals = savane.label_proposals(transaction, "La Librairie")
    assert [p["source"] for p in proposals] == ["history", "cleaned"]
    assert proposals[0]["text"] == "La Librairie" and proposals[1]["text"] == "Librairie"
    # The label already in place is never offered back.
    renamed = Transaction(label="Librairie", raw_label="CB LIBRAIRIE 06/09")
    assert [p["text"] for p in savane.label_proposals(renamed, "Librairie")] == []


# --- The lot, the history and the review -------------------------------------


@pytest.fixture
def shop(demo):
    """A merchant filed 3 times in one category, another filed 3 + 1 times, and
    one waiting operation of each: the first is sure, the second is a question."""
    from backend.database import SessionLocal

    created: list[int] = []
    with SessionLocal() as db:
        account = crud.list_accounts(db)[0]
        parent = crud.create_category(db, "Lot5a parent", None)
        sure_cat = crud.create_category(db, "Lot5a sure", parent)
        other_cat = crud.create_category(db, "Lot5a other", parent)
        today = date.today()

        def add(raw, category, validated, days):
            row = Transaction(
                date=today - timedelta(days=days), label=raw.title(), raw_label=raw, amount=Decimal("-10.00"),
                account_id=account.id, category_id=category.id if category else None, validated=validated,
            )
            db.add(row)
            db.flush()
            created.append(row.id)
            return row

        for days in (40, 30, 20):
            add(f"CB ZEBRAMARKET {days}/01", sure_cat, True, days)
        # The odd one out is the oldest: the proposal follows the most recent filing.
        add("CB ZEBRABOOKS 15/01", other_cat, True, 60)
        for days in (45, 35, 25):
            add(f"CB ZEBRABOOKS {days}/01", sure_cat, True, days)
        sure = add("CB ZEBRAMARKET 02/02", None, False, 3)
        doubtful = add("CB ZEBRABOOKS 03/02", None, False, 2)
        db.commit()
        from backend.routers import backlog

        backlog._cache["items"] = None  # the screen keeps its suggestions between requests
        ids = {"sure": sure.id, "doubtful": doubtful.id, "sure_cat": sure_cat.id, "other_cat": other_cat.id, "parent": parent.id}
    yield ids
    from backend.routers import backlog

    backlog._cache["items"] = None
    with SessionLocal() as db:
        db.query(Transaction).filter(Transaction.id.in_(created)).delete(synchronize_session=False)
        db.query(RuleSuggestion).filter(RuleSuggestion.category_id.in_([ids["sure_cat"], ids["other_cat"]])).delete(
            synchronize_session=False
        )
        db.query(Category).filter(Category.id.in_([ids["sure_cat"], ids["other_cat"]])).delete(synchronize_session=False)
        db.query(Category).filter(Category.id == ids["parent"]).delete(synchronize_session=False)
        db.commit()


def test_history_counts_how_often_a_merchant_was_filed_there(shop):
    from backend.database import SessionLocal

    with SessionLocal() as db:
        index = savane.history_index(db)
        books = db.get(Transaction, shop["doubtful"])
        assert savane.history_counts(index, books, shop["sure_cat"]) == (3, 4)
        assert savane.history_counts(index, books, shop["other_cat"]) == (1, 4)
        market = db.get(Transaction, shop["sure"])
        assert savane.history_counts(index, market, shop["sure_cat"]) == (3, 3)
        assert savane.history_counts(index, market, None) == (0, 0)


def test_a_history_that_disagrees_makes_a_question_not_a_lot_line(shop):
    from backend.database import SessionLocal

    with SessionLocal() as db:
        split = savane.pending_split(db)
        lot_ids = {item["transaction"].id for item in split["lot"]}
        question_ids = {t.id for t in split["questions"]}
        assert shop["sure"] in lot_ids
        assert shop["doubtful"] in question_ids
        item = next(i for i in split["lot"] if i["transaction"].id == shop["sure"])
        assert item["path"] == "Lot5a parent › Lot5a sure" and item["confidence"] >= savane.SURE_CONFIDENCE


def test_filing_the_lot_files_only_what_is_in_it(shop):
    from backend.database import SessionLocal

    with SessionLocal() as db:
        filed, _ = savane.file_lot(db, [shop["sure"], shop["doubtful"]])
        assert [t.id for t in filed] == [shop["sure"]]
        assert db.get(Transaction, shop["sure"]).validated is True
        assert db.get(Transaction, shop["sure"]).category_id == shop["sure_cat"]
        assert db.get(Transaction, shop["doubtful"]).validated is False


def test_leaving_the_lot_makes_the_line_a_question(shop):
    from backend.database import SessionLocal

    with SessionLocal() as db:
        savane.leave_lot(db, db.get(Transaction, shop["sure"]))
        split = savane.pending_split(db)
        assert shop["sure"] not in {i["transaction"].id for i in split["lot"]}
        assert shop["sure"] in {t.id for t in split["questions"]}
        # It goes behind the questions that were never seen.
        assert split["questions"][-1].id == shop["sure"]


def test_the_review_adds_what_the_visit_filed_to_the_pillar_it_belongs_to(demo):
    from backend.database import SessionLocal

    with SessionLocal() as db:
        today = date.today()
        account = crud.list_accounts(db)[0]
        category = db.query(Category).filter(Category.name == "Test housing").one()
        filed = Transaction(
            date=today, label="Review probe", raw_label="REVIEW PROBE", amount=Decimal("-40.00"),
            account_id=account.id, category_id=category.id, validated=True,
        )
        db.add(filed)
        db.commit()
        try:
            review = savane.pillar_review(db, [filed], today)
            by_code = {p["code"]: p for p in review["pillars"]}
            pillar = crud.resolve_transaction_pillar(filed)
            assert by_code[pillar]["delta"] == Decimal("40.00")
            assert sum(p["delta"] for p in review["pillars"]) == Decimal("40.00")
            assert {"left", "goal", "percent"} <= set(review["savings"])
        finally:
            db.delete(filed)
            db.commit()


# --- The screen ------------------------------------------------------------


@pytest.fixture
def other_way(monkeypatch, demo):
    monkeypatch.setenv("ENABLE_OTHER_WAY", "true")
    switch_variant("other_way")
    yield
    switch_variant("classic")


def test_the_page_shows_the_answer_the_lot_and_the_question(clients, other_way, shop):
    html = clients["editor"].get("/transactions/inbox").text
    assert 'id="inbox-head"' in html and 'id="inbox-board"' in html
    assert "Ranger les" in html and 'id="inbox-lot-btn"' in html
    assert 'id="inbox-lot-ids"' in html and f'name="ids" value="{shop["sure"]}"' in html
    assert 'id="transaction-card"' in html and 'id="nav-history"' in html and 'id="nav-qdone"' in html
    # Exactly one amber fill while a lot waits: the question's « Oui » is not it.
    assert html.count("btn-primary") == 1


def test_classic_keeps_its_own_inbox(clients, demo):
    switch_variant("classic")
    html = clients["editor"].get("/transactions/inbox").text
    assert 'id="inbox-board"' not in html and 'id="inbox-upcoming"' in html


def test_the_lot_is_filed_in_one_gesture_and_the_questions_follow(clients, other_way, shop):
    admin = clients["admin"]
    response = admin.post(
        "/transactions/lot/file", data={"ids": [shop["sure"]], "history": "", "qdone": "0"}, headers=HTMX
    )
    assert response.status_code == 200
    html = response.text
    assert 'id="inbox-board"' in html and 'hx-swap-oob="true"' in html
    assert "1 opération rangée d'un geste" in html
    assert 'data-stage="decision"' in html or 'data-stage="lot"' in html
    from backend.database import SessionLocal

    with SessionLocal() as db:
        assert db.get(Transaction, shop["sure"]).validated is True


def test_touching_a_line_of_the_lot_asks_about_it(clients, other_way, shop):
    html = clients["admin"].post(
        f"/transactions/{shop['sure']}/leave-lot", data={"history": "", "qdone": "0"}, headers=HTMX
    ).text
    assert 'id="transaction-card"' in html
    assert "Zebramarket" in html
    # The line is no longer offered in the lot.
    assert f'name="ids" value="{shop["sure"]}"' not in html


def test_a_question_gives_the_reason_for_its_suggestion(clients, other_way, shop):
    admin = clients["admin"]
    admin.post(f"/transactions/{shop['sure']}/leave-lot", data={"history": "", "qdone": "0"}, headers=HTMX)
    # Put the doubtful one in front: skip everything else that waits.
    from backend.database import SessionLocal
    from datetime import datetime

    with SessionLocal() as db:
        for row in db.query(Transaction).filter(Transaction.validated.is_(False), Transaction.is_transfer.is_(False)):
            if row.id != shop["doubtful"]:
                row.skipped_at = datetime.now()
        db.commit()
    try:
        html = admin.get("/transactions/inbox").text
        assert "Déjà rangée là 3 fois sur 4." in html
        assert "Plutôt Lot5a parent › Lot5a sure ?" in html
        assert 'id="inbox-validate-btn"' in html
    finally:
        with SessionLocal() as db:
            for row in db.query(Transaction).filter(Transaction.skipped_at.is_not(None), Transaction.label != "Bakery"):
                row.skipped_at = None
            db.commit()


def test_oui_files_the_proposal_with_the_label_and_the_payment_shown(clients, other_way, shop):
    admin = clients["admin"]
    html = admin.post(
        f"/transactions/{shop['sure']}/finalize/{shop['sure_cat']}",
        data={"label": "Zebra market", "history": "", "qdone": "0", "payment_method": "", "unexpected": ""},
        headers=HTMX,
    ).text
    assert 'id="inbox-board"' in html
    from backend.database import SessionLocal

    with SessionLocal() as db:
        row = db.get(Transaction, shop["sure"])
        assert row.validated and row.label == "Zebra market" and row.category_id == shop["sure_cat"]


def test_undo_brings_the_last_filing_back_as_the_question(clients, other_way, shop):
    admin = clients["admin"]
    admin.post(
        f"/transactions/{shop['sure']}/finalize/{shop['sure_cat']}",
        data={"history": "", "qdone": "0"}, headers=HTMX,
    )
    html = admin.post("/transactions/undo", data={"history": str(shop["sure"]), "qdone": "1"}, headers=HTMX).text
    assert 'id="transaction-card"' in html and "Zebramarket" in html
    from backend.database import SessionLocal

    with SessionLocal() as db:
        assert db.get(Transaction, shop["sure"]).validated is False


def test_a_budget_alert_is_only_offered_for_the_category_of_the_question():
    parent = Category(id=1, name="Food")
    child = Category(id=2, name="Groceries", parent=parent)
    alerts = [{"category_id": 1, "percentage": 86.0}, {"category_id": 9, "percentage": 95.0}]
    assert savane.budget_alert_for(alerts, child)["percentage"] == 86.0
    assert savane.budget_alert_for(alerts, Category(id=3, name="Other")) is None
    assert savane.budget_alert_for(alerts, None) is None
