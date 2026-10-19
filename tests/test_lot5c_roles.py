"""Lot 5, group C: the reader's view ("Lecture seule") in the other way."""

from datetime import date

import pytest

from backend import answers, role_rights
from tests.test_lot5c_settings import other_way, page_of, text_of  # noqa: F401  (fixtures and helpers)


def test_what_a_role_allows_is_read_from_the_rules_of_the_application():
    viewer = dict(role_rights.capabilities("viewer"))
    editor = dict(role_rights.capabilities("editor"))
    admin = dict(role_rights.capabilities("admin"))

    assert list(viewer.values()) == [True, False, False, False]
    assert list(editor.values()) == [True, True, False, False]
    assert list(admin.values()) == [True, True, True, True]
    assert "Importer un relevé et gérer les utilisateurs" in viewer


def test_the_reader_is_told_what_they_can_do_and_who_can_file_the_rest():
    result = answers.reader_answer(14, "Alex")

    assert result.title == "Tu peux consulter, pas modifier."
    assert result.detail == "14 opérations attendent d'être rangées. Alex ou un éditeur peut s'en charger."
    assert answers.reader_answer(1, None).detail == "1 opération attend d'être rangée. Un éditeur peut s'en charger."
    assert "Rien n'attend" in answers.reader_answer(0, "Alex").detail
    assert answers.reader_lot_title(date(2026, 9, 1)) == "Le lot de septembre"
    assert answers.reader_lot_title(date(2026, 10, 1)) == "Le lot d'octobre"


def test_a_reader_gets_la_savane_without_a_single_write_action(clients, other_way):
    html = page_of(clients, "viewer", "/transactions/inbox")
    body = text_of(html)

    assert "Tu peux consulter, pas modifier." in body and "Ce que ce rôle permet" in body and "Oui" in body and "Non" in body
    for write in ("/transactions/lot/file", "inbox-lot-btn", "Ranger les", "btn-primary"):
        assert write not in html, write


def test_an_editor_and_an_administrator_keep_the_working_savane(clients, other_way):
    for role in ("editor", "admin"):
        body = text_of(page_of(clients, role, "/transactions/inbox"))

        assert "Tu peux consulter, pas modifier." not in body


def test_a_reader_sees_the_projects_without_the_gestures_that_write(clients, other_way):
    html = page_of(clients, "viewer", "/projects")
    body = text_of(html)

    assert "Holidays" in body and "À ce rythme" in body
    for write in ("/projects/create", "/spend", "/add", "/delete"):
        assert write not in html, write
    assert "Nouveau projet" not in body


def test_an_editor_keeps_the_gestures_of_the_projects(clients, other_way):
    html = page_of(clients, "editor", "/projects")

    assert "/projects/create" in html and "/spend" in html
