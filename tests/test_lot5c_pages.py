"""Lot 5, group C: the setting pages of the other way (Comptes, Catégories, Règles,
Modes de paiement, Abonnements, Chèques, Utilisateurs), Mon profil, Connexion and
the reader's view. Each screen keeps the gestures of the Classic one."""

import re

import pytest

from backend import answers
from tests.test_lot5c_settings import other_way, page_of, text_of  # noqa: F401  (fixtures and helpers)

HX = {"HX-Request": "true"}


# --- Comptes --------------------------------------------------------------------


def test_the_accounts_sentence_counts_accounts_and_pairs_to_confirm():
    assert answers.accounts_answer(3, 2)["phrase"] == "3 comptes, 2 virements internes à confirmer."
    assert answers.accounts_answer(1, 1)["phrase"] == "1 compte, 1 virement interne à confirmer."
    assert answers.accounts_answer(3, 0)["phrase"] == "3 comptes, aucun virement interne à confirmer."


def test_the_accounts_screen_keeps_create_edit_delete_diagnostic_and_transfers(clients, other_way):
    html = page_of(clients, "admin", "/accounts")
    body = text_of(html)

    for text in ("Ajouter un compte", "Détecter les virements internes", "Opérations suspectes", "Total"):
        assert text in body, text
    for hook in ('id="accounts-head"', 'id="accounts-content"', 'id="detect-transfers-content"', "/accounts/create", "/edit", "Voir le diagnostic de solde"):
        assert hook in html, hook


def test_an_account_can_be_edited_and_deleted_from_its_row(clients, other_way, demo):
    account_id = demo["account_id"]
    edit = clients["admin"].get(f"/accounts/{account_id}/edit", headers=HX)
    ask = clients["admin"].get(f"/accounts/{account_id}/delete-confirm", headers=HX)

    assert edit.status_code == 200 and "Supprimer ce compte" in text_of(edit.text) and f"/accounts/{account_id}/update" in edit.text
    assert ask.status_code == 200 and "opération" in text_of(ask.text)  # it has operations: it explains instead of deleting


def test_the_accounts_head_refreshes_the_sentence(clients, other_way):
    response = clients["admin"].get("/accounts/head", headers=HX)

    assert response.status_code == 200
    assert 'id="accounts-head"' in response.text and "comptes" in text_of(response.text)


def test_a_reader_sees_the_accounts_without_the_gestures_that_write(clients, other_way):
    body = text_of(page_of(clients, "viewer", "/accounts"))

    assert "Comptes" in body and "Ajouter un compte" not in body and "Tout confirmer" not in body
