"""Smoke test: every GET page and HTMX fragment answers, for each role.

The list below is the inventory of the GET routes of the application. A test
fails when a route is added to (or removed from) the application without
updating it, so a new page cannot slip past the suite.
"""

from datetime import date
from typing import NamedTuple
from urllib.parse import urlencode

import pytest
from fastapi.routing import APIRoute

from tests.conftest import ROLES

TODAY = date.today()
MONTH_START = TODAY.replace(day=1)


class Page(NamedTuple):
    template: str  # route path, as declared in the routers
    query: dict | None = None
    htmx: bool = False  # a fragment loaded by HTMX (sent with the HX-Request header)
    public: bool = False  # reachable without being logged in


PAGES = [
    Page("/"),
    Page("/login", public=True),
    Page("/health", public=True),
    Page("/static/sw.js", public=True),
    Page("/design-system"),
    Page("/settings"),
    Page("/profile"),
    Page("/profile/password"),
    Page("/payment-methods"),
    Page("/payment-methods/head", htmx=True),
    # Inbox (La Savane) and operations
    Page("/transactions/inbox"),
    Page("/transactions/{transaction_id}/categories", htmx=True),
    Page("/transactions/subcategories", {"parent_category_id": "{category_id}"}, htmx=True),
    Page("/transactions/list"),
    Page("/transactions/list/content", htmx=True),
    Page("/transactions/new", htmx=True),
    Page("/transactions/{transaction_id}/detail", htmx=True),
    Page("/transactions/{transaction_id}/edit", htmx=True),
    Page("/transactions/receipts/{transaction_id}/section", htmx=True),
    # Backlog
    Page("/backlog"),
    Page("/backlog/content", htmx=True),
    # Dashboard
    Page("/dashboard"),
    Page("/dashboard/content", htmx=True),
    Page(
        "/dashboard/category-transactions",
        {"category_id": "{category_id}", "start": MONTH_START.isoformat(), "end": TODAY.isoformat(),
         "label": "Month", "type": "expense"},
        htmx=True,
    ),
    Page("/dashboard/sidebar-balance", htmx=True),
    Page("/dashboard/shell-balance", htmx=True),
    Page("/dashboard/sidebar-pending", htmx=True),
    # Accounts
    Page("/accounts"),
    Page("/accounts/content", htmx=True),
    Page("/accounts/suspicious", htmx=True),
    Page("/accounts/head", htmx=True),
    Page("/accounts/{account_id}/row", htmx=True),
    Page("/accounts/{account_id}/edit", htmx=True),
    Page("/accounts/{account_id}/delete-confirm", htmx=True),
    Page("/accounts/detect-transfers"),
    Page("/accounts/detect-transfers/content", htmx=True),
    # Categories
    Page("/categories"),
    Page("/categories/content", htmx=True),
    Page("/categories/head", htmx=True),
    Page("/categories/pillars", htmx=True),
    Page("/categories/{category_id}/row", htmx=True),
    Page("/categories/{category_id}/edit", htmx=True),
    Page("/categories/{category_id}/delete-confirm", htmx=True),
    Page("/categories/{parent_id}/add-subcategory-form", htmx=True),
    Page("/categories/{parent_id}/add-subcategory-button", htmx=True),
    # Budgets
    Page("/budgets"),
    Page("/budgets/content", {"month": TODAY.month, "year": TODAY.year}, htmx=True),
    # Le Cap
    Page("/cap"),
    Page("/cap/mid"),
    Page("/cap/reopen", htmx=True),
    # Projects, recurring, checks, rules
    Page("/projects"),
    Page("/recurring"),
    Page("/recurring/content", htmx=True),
    Page("/checks"),
    Page("/checks/list", htmx=True),
    Page("/rules"),
    Page("/rules/list", htmx=True),
    Page("/rules/head", htmx=True),
    Page("/rules/{rule_id}/row", htmx=True),
    Page("/rules/{rule_id}/edit", htmx=True),
    # Reports
    Page("/reports"),
    Page("/reports/content", htmx=True),
    Page("/reports/transactions", {"type": "expense"}, htmx=True),
    Page("/reports/category-trend", {"category_id": "{category_id}"}, htmx=True),
    Page("/reports/category-sheet", {"category_id": "{category_id}"}, htmx=True),
    Page("/reports/export.csv"),
    Page("/reports/transactions/export.csv"),
    # Search, export, import, users
    Page("/search/quick", {"q": "super"}, htmx=True),
    Page("/export/json"),
    Page("/export/transactions.csv"),
    Page("/export/restore/progress", htmx=True),
    Page("/export/backup/status", htmx=True),
    Page("/imports/new"),
    Page("/imports/step1", htmx=True),
    Page("/imports/back", {"import_id": "0" * 32, "format": "csv"}, htmx=True),
    Page("/users"),
    Page("/users/list", htmx=True),
]

# Pages that only an administrator may read (backend/auth.py, _ADMIN_ONLY_PREFIXES).
ADMIN_ONLY_PREFIXES = ("/imports", "/users")

# Routes FastAPI adds by itself; AuthMiddleware keeps them away from visitors.
FRAMEWORK_PATHS = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


def url_for(page: Page, demo: dict[str, int]) -> str:
    path = page.template.format(**demo)
    if page.query:
        path += "?" + urlencode({key: str(value).format(**demo) for key, value in page.query.items()})
    return path


def request(client, page: Page, demo: dict[str, int]):
    headers = {"HX-Request": "true"} if page.htmx else {}
    return client.get(url_for(page, demo), headers=headers)


def test_inventory_matches_the_routes(app):
    declared = {
        route.path
        for route in app.routes
        if isinstance(route, APIRoute) and "GET" in route.methods
    } - FRAMEWORK_PATHS
    listed = {page.template for page in PAGES}
    assert declared - listed == set(), "GET routes missing from PAGES"
    assert listed - declared == set(), "PAGES entries that are not GET routes anymore"


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("page", PAGES, ids=lambda page: page.template)
def test_page_answers_for_each_role(clients, demo, variant, role, page):
    response = request(clients[role], page, demo)

    if page.template.startswith(ADMIN_ONLY_PREFIXES) and role != "admin":
        assert response.status_code == 403
    elif page.template == "/":
        assert response.status_code == 307
        assert response.headers["location"] == "/transactions/inbox"
    elif page.template == "/login":
        # Already logged in: sent on to the dashboard.
        assert response.status_code == 307
        assert response.headers["location"] == "/dashboard"
    else:
        assert response.status_code == 200, response.text[:500]
        assert response.content, "empty response"


@pytest.mark.parametrize("page", PAGES, ids=lambda page: page.template)
def test_page_requires_a_login(clients, demo, page):
    response = request(clients["anonymous"], page, demo)

    if page.public:
        assert response.status_code == 200
    elif page.htmx:
        # An expired session inside a fragment asks HTMX for a full redirect.
        assert response.status_code == 200
        assert response.headers["HX-Redirect"] == "/login"
    else:
        assert response.status_code == 303
        assert response.headers["location"] == "/login"


@pytest.mark.parametrize(
    "role, method, path",
    [
        ("viewer", "POST", "/categories"),
        ("viewer", "POST", "/transactions/new"),
        ("editor", "POST", "/accounts"),
        ("editor", "POST", "/settings/cap-income-source"),
        ("editor", "DELETE", "/categories/1"),
    ],
)
def test_write_actions_are_refused_beyond_the_role(clients, role, method, path):
    response = clients[role].request(method, path, headers={"HX-Request": "true"})
    assert response.status_code == 403


@pytest.mark.parametrize(
    "path, expected",
    [
        ("/transactions/inbox", "Pharmacy"),  # the oldest operation not skipped
        ("/transactions/list", "Supermarket"),
        ("/accounts", "Checking account"),
        ("/categories", "Test groceries"),
        ("/rules", "CARREFOUR"),
        ("/projects", "Holidays"),
    ],
)
def test_demo_data_reaches_the_pages(clients, path, expected):
    # Guards the smoke test itself: a 200 on an empty page proves little.
    assert expected in clients["admin"].get(path).text
