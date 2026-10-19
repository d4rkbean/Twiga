"""Lot 5, group C: the settings hub of the other way."""

from datetime import date, timedelta
from types import SimpleNamespace

from backend import answers, settings_hub
from tests.test_lot5c_settings import other_way, page_of, text_of  # noqa: F401  (fixtures and helpers)


def test_all_is_in_place_then_the_one_thing_that_waits():
    waiting = answers.settings_answer({"number": "0004816", "days": 12}, 0, 3, 8, 6)

    assert waiting.title == "Tout est en place. Le chèque n° 0004816 attend son débit depuis 12 jours."
    assert waiting.detail.startswith("3 comptes, 8 catégories, 6 règles de rangement.")
    assert waiting.action[0] == "/checks"
    assert answers.settings_answer({"number": None, "days": 1}, 0, 1, 1, 1).title.endswith(
        "Un paiement attend son débit depuis 1 jour."
    )
    suggested = answers.settings_answer(None, 2, 3, 8, 6)
    assert "2 règles proposées attendent ton avis." in suggested.title and suggested.action[0] == "/rules"
    quiet = answers.settings_answer(None, 0, 3, 8, 6)
    assert quiet.title == "Tout est en place." and quiet.action is None


def test_the_oldest_waiting_payment_is_the_one_that_is_named():
    today = date(2026, 10, 19)
    checks = [
        SimpleNamespace(check_number="B", issued_date=today - timedelta(days=3)),
        SimpleNamespace(check_number="A", issued_date=today - timedelta(days=12)),
    ]

    assert settings_hub.oldest_outstanding_check(checks, today) == {"number": "A", "days": 12}
    assert settings_hub.oldest_outstanding_check([], today) is None


def test_the_search_examples_start_from_a_rule_and_end_with_a_person():
    assert settings_hub.search_examples(["LOYER"], ["Sam"]) == ["loyer", "sauvegarde", "abonnement", "Sam"]
    assert settings_hub.search_examples([], []) == ["sauvegarde", "abonnement"]


def test_the_hub_is_arranged_by_use_and_keeps_every_gesture(clients, other_way):
    html = page_of(clients, "admin", "/settings")
    body = text_of(html)

    for heading in ("Ce qui change souvent", "De temps en temps", "Zone sensible"):
        assert heading in body
    assert body.index("Ce qui change souvent") < body.index("De temps en temps") < body.index("Zone sensible")
    for gesture in (
        "Chercher un réglage", "Modes de paiement", "Abonnements récurrents", "Catégorisation en masse", "Budgets",
        "Importer un relevé", "Nouvelle catégorie", "Langue et formats", "Exporter en CSV", "Exporter en JSON complet",
        "Sauvegarder maintenant", "Restaurer depuis une sauvegarde JSON", "Début du mois budgétaire",
        "Revoir la visite guidée", "Tout supprimer", "Afficher les comptes sur la page de connexion",
    ):
        assert gesture in body, gesture
    for endpoint in ("/settings/cap-income-source", "/settings/budget-start-day", "/profile/preferences",
                     "/export/restore", "/settings/delete-all-transactions", "/settings/login-accounts"):
        assert endpoint in html, endpoint


def test_an_editor_and_a_reader_see_the_hub_without_the_gestures_they_cannot_use(clients, other_way):
    for role in ("editor", "viewer"):
        body = text_of(page_of(clients, role, "/settings"))

        assert "Ce qui change souvent" in body
        for hidden in ("Nouvelle catégorie", "Tout supprimer", "Sauvegarder maintenant", "Afficher les comptes sur la page de connexion"):
            assert hidden not in body, (role, hidden)


def test_the_login_tiles_setting_is_off_by_default_and_belongs_to_the_administrator(clients, other_way):
    from backend import crud
    from backend.database import SessionLocal

    with SessionLocal() as db:
        assert crud.get_or_create_app_state(db).show_login_accounts is False

    assert clients["editor"].post("/settings/login-accounts", data={"show": "on"}).status_code == 403
    assert clients["admin"].post("/settings/login-accounts", data={"show": "on"}).status_code == 200
    with SessionLocal() as db:
        assert crud.get_or_create_app_state(db).show_login_accounts is True
    clients["admin"].post("/settings/login-accounts", data={})
    with SessionLocal() as db:
        assert crud.get_or_create_app_state(db).show_login_accounts is False
