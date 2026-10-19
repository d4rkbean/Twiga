"""Lot 5, group C: every screen of the group renders in English (the catalog is complete and
its placeholders fit the sentences), in the other way."""

import pytest

from backend.database import SessionLocal
from backend.models import User
from tests.test_lot5c_settings import other_way, page_of, text_of  # noqa: F401  (fixtures and helpers)

PAGES = [
    ("/projects", "Adjust"),
    ("/imports/new", "One file is enough"),
    ("/settings", "Everything is in place"),
    ("/accounts", "accounts"),
    ("/categories", "categories"),
    ("/rules", "Test a rule"),
    ("/payment-methods", "payment modes"),
    ("/recurring", "subscription"),
    ("/checks", "payment"),
    ("/users", "have access"),
    ("/profile", "Save my display"),
]


@pytest.fixture
def english(demo):
    with SessionLocal() as db:
        db.query(User).update({User.language: "en"})
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(User).update({User.language: "fr"})
        db.commit()


@pytest.mark.parametrize("path, marker", PAGES)
def test_the_screen_speaks_english(clients, other_way, english, path, marker):
    html = page_of(clients, "admin", path)
    body = text_of(html)

    assert marker in body, (path, marker)
    assert "Ajouter un" not in body and "Enregistrer" not in body  # no French left on the screen


def test_the_import_recap_and_the_reader_speak_english(clients, other_way, english):
    csv = "Date;Libellé;Montant\n01/10/2026;CB EPICERIE;-12,50\n"
    response = clients["admin"].post("/imports/recap", files={"file": ("releve.csv", csv.encode())}, headers={"HX-Request": "true"})
    body = text_of(response.text)

    assert "to import" in body and "Adjust" in body and "operations" in body or "operation" in body
    reader = text_of(page_of(clients, "viewer", "/transactions/inbox"))
    assert "You can look, not change." in reader and "What this role allows" in reader
