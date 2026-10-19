"""The feedback fragment returned by HTMX actions, and the settings-group screens
that were redrawn around it.

Replies used to be built by hand in Python (`'<p class="...">...</p>'`); they now
all go through frontend/templates/_flash.html. These tests pin the contract: the
verdict is in the text, the role tells assistive technology how urgent it is,
and nothing typed by a user reaches the page unescaped.
"""

import io

from tests.conftest import ROLES  # noqa: F401  (keeps the fixtures importable)


def test_flash_escapes_what_the_user_typed():
    from backend.templating import flash_html

    html = flash_html("error", '<script>alert(1)</script>')

    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_flash_kinds_carry_a_role_and_a_color():
    from backend.templating import flash_html

    assert 'role="alert"' in flash_html("error", "Refused")
    assert "text-danger" in flash_html("error", "Refused")
    assert 'role="status"' in flash_html("success", "Saved")
    assert "text-success" in flash_html("success", "Saved")


def test_a_wrong_login_answers_with_an_alert(clients):
    response = clients["anonymous"].post(
        "/login", data={"username": "nobody", "password": "wrong-password"}, headers={"HX-Request": "true"}
    )

    assert response.status_code == 401
    assert 'role="alert"' in response.text
    assert "text-danger" in response.text


def test_saving_the_cap_setting_answers_with_a_status(clients):
    response = clients["admin"].post(
        "/settings/cap-income-source",
        data={"income_source": "recettes_precedent"},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert 'role="status"' in response.text
    assert "text-success" in response.text


def test_a_refused_profile_update_answers_with_an_alert(clients):
    # The name of another account is taken: the refusal comes back as an alert.
    response = clients["editor"].post(
        "/profile/update",
        data={"display_name": "", "username": "test_viewer"},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 400
    assert 'role="alert"' in response.text


def test_the_settings_page_lists_its_sections_and_places(clients):
    html = clients["admin"].get("/settings").text

    for place in ("/accounts", "/categories", "/payment-methods", "/rules", "/recurring", "/checks", "/users"):
        assert f'href="{place}"' in html
    for section in ("gerer", "comptes", "categories", "regles", "cap", "preferences", "utilisateurs", "donnees"):
        assert f'id="s-{section}"' in html
        assert f'href="#s-{section}"' in html


def test_the_import_wizard_shows_its_stepper(clients, demo):
    csv = "Date;Label;Amount\n03/10/2026;SUPERMARKET;-12,50\n05/10/2026;SALARY;1500,00\n"
    response = clients["admin"].post(
        "/imports/preview",
        files={"file": ("statement.csv", io.BytesIO(csv.encode()), "text/csv")},
        data={"account_id": str(demo["account_id"])},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert 'aria-current="step"' in response.text
    assert 'name="date_column"' in response.text


def test_the_projects_page_draws_a_ring_per_project(clients):
    html = clients["admin"].get("/projects").text

    assert 'role="img"' in html
    assert "pathLength" in html
