"""Lot 5, group C: Modes de paiement in the other way (tiles and a detection)."""

from backend import answers, crud
from backend.database import SessionLocal
from backend.payment_methods import detection_examples
from tests.test_lot5c_settings import other_way, page_of, text_of  # noqa: F401  (fixtures and helpers)

HX = {"HX-Request": "true"}


def test_the_sentence_counts_the_modes_and_the_operations_without_one():
    assert answers.payments_answer(8, 12).title == "8 modes de paiement. 12 opérations n'ont pas encore le leur."
    assert answers.payments_answer(8, 1).title == "8 modes de paiement. 1 opération n'a pas encore le sien."
    assert answers.payments_answer(1, 0).title == "1 mode de paiement. Toutes les opérations ont le leur."
    assert "« CARTE SUPERMARCHE » devient CB" in answers.payments_answer(8, 0).detail


def test_the_detection_examples_group_the_words_by_mode_in_priority_order():
    examples = dict((name, words) for words, name in detection_examples())

    assert list(examples)[0] == "CB" and "CARTE" in examples["CB"]
    assert "VIREMENT" in examples["Virement"] and "REMBOURSEMENT" in examples["Virement"]  # two rules, one mode


def test_operations_without_a_mode_are_counted(demo):
    with SessionLocal() as db:
        assert crud.count_transactions_without_payment_method(db) >= 1


def test_the_screen_keeps_add_rename_delete_and_the_detection(clients, other_way):
    html = page_of(clients, "admin", "/payment-methods")
    body = text_of(html)

    for text in ("Détecter les modes de paiement manquants", "Ajouter un mode", "Tes modes de paiement", "Comment Twiga reconnaît le mode",
                 "Modifier le mode de paiement", "Oui, supprimer"):
        assert text in body, text
    for hook in ('id="payments-head"', "/payment-methods/create", "/update", "/delete", "/settings/detect-payment-methods"):
        assert hook in html, hook


def test_the_head_refreshes_the_sentence(clients, other_way):
    response = clients["admin"].get("/payment-methods/head", headers=HX)

    assert response.status_code == 200 and 'id="payments-head"' in response.text


def test_a_reader_sees_the_modes_without_the_gestures_that_write(clients, other_way):
    body = text_of(page_of(clients, "viewer", "/payment-methods"))

    assert "Tes modes de paiement" in body
    for hidden in ("Détecter les modes", "Ajouter un mode", "Oui, supprimer", "Modifier le mode de paiement"):
        assert hidden not in body, hidden
