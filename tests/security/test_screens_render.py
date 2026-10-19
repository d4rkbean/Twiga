"""The main screens still render for a signed-in administrator: a safety net for
the dependency upgrades and the middlewares of the security hardening."""

import pytest

SCREENS = (
    "/dashboard",
    "/transactions/inbox",
    "/transactions/list",
    "/backlog",
    "/categories",
    "/accounts",
    "/payment-methods",
    "/budgets",
    "/cap",
    "/projects",
    "/rules",
    "/recurring",
    "/checks",
    "/reports",
    "/imports/new",
    "/users",
    "/settings",
    "/profile",
)


@pytest.mark.parametrize("path", SCREENS)
def test_a_main_screen_renders_for_an_administrator(signed_in, path):
    response = signed_in["admin"].get(path)

    assert response.status_code == 200, (path, response.status_code)
    assert "text/html" in response.headers["content-type"]


def test_the_sign_in_page_renders_for_a_visitor(signed_in):
    response = signed_in["anonymous"].get("/login")

    assert response.status_code == 200
