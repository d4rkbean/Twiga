"""Lot 5, group C: Règles in the other way (proposals first, a live count, a test)."""

import pytest

from backend import answers, crud
from backend.database import SessionLocal
from backend.models import Rule, RuleSuggestion
from tests.test_lot5c_settings import other_way, page_of, text_of  # noqa: F401  (fixtures and helpers)

HX = {"HX-Request": "true"}


def test_the_sentence_puts_the_proposals_first():
    assert answers.rules_answer(4, 8)["phrase"] == "4 règles attendent ton avis."
    assert answers.rules_answer(1, 8)["phrase"] == "1 règle attend ton avis."
    assert "Une proposition ignorée ne revient plus" in answers.rules_answer(4, 8)["detail"]
    assert answers.rules_answer(0, 8)["phrase"] == "8 règles rangent tes opérations."
    assert answers.rules_answer(0, 0)["phrase"] == "Aucune règle pour l'instant."


def test_a_keyword_counts_the_operations_it_catches(demo):
    with SessionLocal() as db:
        assert crud.count_transactions_matching_keyword(db, "supermarket") >= 1  # case aside
        assert crud.count_transactions_matching_keyword(db, "no-such-label-anywhere") == 0
        assert crud.count_transactions_matching_keyword(db, "  ") == 0


@pytest.fixture
def restore_suggestions(demo):
    """"Tout créer" consumes the shared demo's proposals: put them back afterwards."""
    with SessionLocal() as db:
        before = [(s.keyword, s.category_id, s.occurrences) for s in crud.list_pending_rule_suggestions(db)]
        rule_ids = {rule.id for rule in db.query(Rule).all()}
    yield
    with SessionLocal() as db:
        for rule in db.query(Rule).filter(Rule.id.notin_(rule_ids)).all():
            db.delete(rule)
        db.query(RuleSuggestion).delete()
        for keyword, category_id, occurrences in before:
            db.add(RuleSuggestion(keyword=keyword, category_id=category_id, occurrences=occurrences))
        db.commit()


def test_create_all_turns_every_proposal_into_a_rule(restore_suggestions):
    with SessionLocal() as db:
        waiting = crud.count_pending_rule_suggestions(db)
        before = db.query(Rule).count()

        assert waiting >= 1
        assert crud.create_rules_from_suggestions(db) == waiting
        assert db.query(Rule).count() == before + waiting
        assert crud.count_pending_rule_suggestions(db) == 0


def test_the_rules_screen_keeps_every_gesture(clients, other_way):
    html = page_of(clients, "admin", "/rules")
    body = text_of(html)

    for text in ("Tout créer", "Ajouter une règle", "En attente de validation", "Tester une règle", "Les plus utilisées d'abord", "Présent dans"):
        assert text in body, text
    for hook in ('id="rules-head"', 'id="rules-content"', "/rules/create-all", "/rules/create", "/rules/test", "/rules/count"):
        assert hook in html, hook


def test_the_panel_of_a_rule_counts_what_it_catches_and_can_delete(clients, other_way, demo):
    panel = clients["admin"].get(f"/rules/{demo['rule_id']}/edit", headers=HX)
    body = text_of(panel.text)

    assert panel.status_code == 200
    for text in ("Mot-clé", "Catégorie", "Sous-catégorie", "Mode de paiement", "Supprimer cette règle", "Enregistrer"):
        assert text in body, text
    assert "/rules/count" in panel.text


def test_the_live_count_and_the_test_answer_in_place(clients, other_way):
    count = clients["admin"].post("/rules/count", data={"keyword": "SUPERMARKET"}, headers=HX)
    none = clients["admin"].post("/rules/count", data={"keyword": "zzzz-nothing"}, headers=HX)
    tested = clients["admin"].post("/rules/test", data={"label": "CARREFOUR MARKET PARIS"}, headers=HX)

    assert "Cette règle touche" in text_of(count.text)
    assert "Aucune opération" in text_of(none.text)
    assert "Règle correspondante" in text_of(tested.text)


def test_a_reader_sees_the_rules_without_the_gestures_that_write(clients, other_way):
    body = text_of(page_of(clients, "viewer", "/rules"))

    assert "Règles" in body and "Tout créer" not in body and "Ajouter une règle" not in body and "Créer" not in body
