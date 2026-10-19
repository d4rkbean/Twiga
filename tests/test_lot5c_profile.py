"""Lot 5, group C: Mon profil and Connexion in the other way."""

import pytest

from backend import answers, crud
from backend.database import SessionLocal
from tests.test_lot5c_settings import other_way, page_of, text_of  # noqa: F401  (fixtures and helpers)


# --- Mon profil -------------------------------------------------------------------


def test_the_display_sentence_names_theme_density_and_amounts():
    assert answers.profile_answer("system", "normal", False).title == "Thème automatique, affichage normal, montants visibles."
    assert answers.profile_answer("dark", "compact", True).title == "Thème sombre, affichage compact, montants masqués."
    assert answers.profile_answer("light", "comfortable", False).title.startswith("Thème clair, affichage aéré")
    words = answers.profile_words()
    assert set(words) == {"theme", "density", "privacy"} and set(words["theme"]) == {"light", "system", "dark"}


def test_the_profile_previews_the_display_and_keeps_the_account_gestures(clients, other_way):
    html = page_of(clients, "editor", "/profile")
    body = text_of(html)

    for text in ("Enregistrer mon affichage", "Ton affichage", "Thème", "Densité", "Masquer les montants à l'ouverture", "Solde total",
                 "Ton compte", "Informations", "Mot de passe", "Changer le mot de passe", "Se déconnecter", "Interface"):
        assert text in body, text
    for hook in ("/profile/preferences", "/profile/update", "/settings/change-password", "/logout", "pref-preview", 'aria-label="Aperçu"'):
        assert hook in html, hook
    assert "Sessions ouvertes" in body and "Cet appareil" in body  # the block of open sessions (tests/test_sessions.py)
    assert "/profile/sessions/close" not in html or "Fermer les autres sessions" in body


def test_every_password_field_of_the_profile_has_its_eye(clients, other_way):
    html = page_of(clients, "editor", "/profile")

    assert html.count(":aria-label=\"show ? 'Masquer le mot de passe' : 'Afficher le mot de passe'\"") == 3
    for name, suffix in (("current_password", "current"), ("new_password", "new"), ("confirm_password", "confirm")):
        assert f'id="password-field-profile-{suffix}"' in html and f'name="{name}"' in html
    # The fields are bound to the form, which keeps the button off until all is in order.
    assert html.count('x-model="cur"') == 1 and html.count('x-model="pw"') == 1 and html.count('x-model="pw2"') == 1


def test_the_profile_is_open_to_every_role(clients, other_way):
    for role in ("admin", "editor", "viewer"):
        assert page_of(clients, role, "/profile")


# --- Connexion --------------------------------------------------------------------


def login_html(clients):
    clients["anonymous"].cookies.set("twiga_ui", "other_way")
    response = clients["anonymous"].get("/login")
    assert response.status_code == 200
    return response.text


@pytest.fixture
def login_tiles():
    def set_to(value):
        with SessionLocal() as db:
            crud.get_or_create_app_state(db).show_login_accounts = value
            db.commit()

    yield set_to
    set_to(False)


def test_the_login_is_the_classic_form_unless_the_administrator_shows_the_accounts(clients, other_way, login_tiles):
    login_tiles(False)
    html = login_html(clients)
    body = text_of(html)

    assert 'data-ui="other_way"' in html
    assert "Bonjour !" in body and "Qui est là ?" not in body
    assert "Nom d'utilisateur" in body and "Se connecter" in body and "Choisir son compte" not in body
    assert "test_admin" not in html and "test_editor" not in html  # the household is not named on a public page


def test_with_the_setting_on_the_household_is_offered_as_tiles(clients, other_way, login_tiles):
    login_tiles(True)
    html = login_html(clients)
    body = text_of(html)

    assert "Bonjour ! Qui est là ?" in body and "Choisir son compte" in body and "Un autre compte" in body
    assert "test_admin" in html and "Administrateur" in body
    assert 'hx-post="/login"' in html and "Se connecter" in body  # the same form, with the messages of the application


def test_a_wrong_password_keeps_the_application_message(clients, other_way):
    response = clients["anonymous"].post("/login", data={"username": "test_admin", "password": "wrong-password"}, headers={"HX-Request": "true"})

    assert response.status_code == 401 and "incorrect" in text_of(response.text)
