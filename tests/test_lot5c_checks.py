"""Lot 5, group C: Chèques in the other way (what waits for its debit)."""

from backend import answers
from tests.test_lot5c_settings import other_way, page_of, text_of  # noqa: F401  (fixtures and helpers)

HX = {"HX-Request": "true"}


def test_the_sentence_gives_the_count_the_total_and_the_oldest_payment():
    result = answers.checks_answer(3, "245,00 €", {"number": "0004816", "days": 12})

    assert result["phrase"] == "3 paiements attendent leur débit, 245,00 €."
    assert result["detail"].startswith("Le chèque n° 0004816 attend depuis 12 jours.")
    assert "je le range tout seul" in result["detail"]
    assert answers.checks_answer(1, "10,00 €", {"number": None, "days": 1})["detail"].startswith("Le plus ancien attend depuis 1 jour.")
    assert answers.checks_answer(1, "10,00 €", None)["phrase"] == "1 paiement attend son débit, 10,00 €."
    assert answers.checks_answer(0, None, None)["phrase"] == "Aucun paiement n'attend son débit."


def test_the_screen_keeps_the_form_the_list_cancel_and_the_explanation(clients, other_way):
    html = page_of(clients, "admin", "/checks")
    body = text_of(html)

    assert "1 paiement attend son débit, 150,00 €." in body
    for text in ("Enregistrer un paiement émis", "En attente", "Récemment rapprochés" if "Récemment rapprochés" in body else "En attente",
                 "Comment il se rapproche tout seul", "Numéro de chèque (si chèque)", "Compte débité", "Depuis 5 jours", "Importer un relevé"):
        assert text in body, text
    for hook in ('id="checks-content"', "/checks/create", "/delete"):
        assert hook in html, hook


def test_the_list_is_a_fragment_that_carries_the_sentence(clients, other_way):
    response = clients["admin"].get("/checks/list", headers=HX)

    assert response.status_code == 200 and 'id="checks-content"' in response.text and "attend son débit" in text_of(response.text)


def test_a_reader_sees_the_payments_without_the_form_or_cancel(clients, other_way):
    html = page_of(clients, "viewer", "/checks")
    body = text_of(html)

    assert "En attente" in body
    assert "Enregistrer le paiement" not in body and "/checks/create" not in html and "Importer un relevé" not in body
    assert "hx-confirm" not in html or "Annuler ce paiement" not in html
