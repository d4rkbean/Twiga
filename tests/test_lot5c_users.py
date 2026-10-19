"""Lot 5, group C: Utilisateurs in the other way (who has access, and to what)."""

from backend import answers
from tests.test_lot5c_settings import other_way, page_of, text_of  # noqa: F401  (fixtures and helpers)

HX = {"HX-Request": "true"}


def test_the_sentence_counts_people_and_names_who_never_opened_their_account():
    result = answers.users_answer({"admin": 1, "editor": 1, "viewer": 1}, ["Léa"], ["Alex"])

    assert result["phrase"] == "3 personnes ont accès. Léa n'a jamais ouvert son compte."
    assert result["detail"] == (
        "1 administrateur, 1 éditeur, 1 en lecture seule. "
        "Il doit toujours rester au moins un administrateur actif : pour l'instant, c'est Alex."
    )
    assert answers.users_answer({"admin": 2, "editor": 0, "viewer": 0}, [], ["Alex", "Sam"])["phrase"] == "2 personnes ont accès."
    assert "n'ont jamais ouvert leur compte" in answers.users_answer({"admin": 1, "editor": 1, "viewer": 1}, ["A", "B"], ["X"])["phrase"]


def test_the_screen_keeps_add_role_active_password_and_delete(clients, other_way):
    html = page_of(clients, "admin", "/users")
    body = text_of(html)

    assert "personnes ont accès" in body
    for text in ("Ajouter un utilisateur", "Utilisateurs existants", "Ce que chaque rôle peut faire", "Actif", "Réinitialiser",
                 "Administrateur", "Éditeur", "Lecture seule", "Seul un administrateur voit cette page."):
        assert text in body, text
    for hook in ('id="users-content"', "/users/create", "/role", "/password", "/active", "/delete"):
        assert hook in html, hook


def test_a_role_change_answers_with_the_whole_block(clients, other_way, demo):
    changed = clients["admin"].post(f"/users/{demo['user_viewer']}/role", data={"role": "viewer"}, headers=HX)

    assert changed.status_code == 200 and 'id="users-content"' in changed.text


def test_the_users_list_fragment_carries_the_sentence(clients, other_way):
    response = clients["admin"].get("/users/list", headers=HX)

    assert response.status_code == 200 and "ont accès" in text_of(response.text)
