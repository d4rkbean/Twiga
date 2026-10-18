"""The contract of the HTMX fragments, in both interfaces.

A page of the other way may replace a template (and a fragment with it): the
`id`s that HTMX swaps into must keep existing, or an action silently does
nothing. For every GET page of the inventory (tests/test_pages.py), for each
role and each interface, this renders the page and checks that

- every `hx-target="#id"` names an element of the rendered page, or, for a
  request the element sends with `hx-get`, an element of the fragment that
  route returns (a fragment may also swap into the page that hosts it);
- every `hx-swap-oob` fragment lands on an element that exists in a page.

Requests that write (`hx-post`, `hx-delete`...) are not played: their target
must already be in the page.
"""

import re
from html.parser import HTMLParser

import pytest

from tests.conftest import ROLES
from tests.test_pages import ADMIN_ONLY_PREFIXES, PAGES, request

# Answers that are not an HTML page or fragment (files, redirects, the style
# guide, which shows every component with fake targets).
NOT_HTML = {"/", "/login", "/health", "/static/sw.js", "/design-system", "/export/json", "/export/restore/progress"}
HTML_PAGES = [
    page for page in PAGES
    if page.template not in NOT_HTML and not page.template.endswith((".csv", ".js")) and not page.public
]

ID = re.compile(r"#([A-Za-z_][\w-]*)")


class Contract(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids: set[str] = set()
        self.targets: list[tuple[str, str | None]] = []  # (id, hx-get on the same element)
        self.oob: list[str] = []

    def handle_starttag(self, tag, attrs):
        attributes = {name: value or "" for name, value in attrs}
        element_id = attributes.get("id")
        if element_id:
            self.ids.add(element_id)
        target = attributes.get("hx-target", "")
        if target.startswith("#"):
            found = ID.match(target)
            if found:
                self.targets.append((found.group(1), attributes.get("hx-get") or None))
        if "hx-swap-oob" in attributes:
            named = ID.search(attributes["hx-swap-oob"])
            landing = named.group(1) if named else element_id
            if landing:
                self.oob.append(landing)


def parse(html: str) -> Contract:
    contract = Contract()
    contract.feed(html)
    return contract


def answer(clients, demo, role, page):
    response = request(clients[role], page, demo)
    if page.template.startswith(ADMIN_ONLY_PREFIXES) and role != "admin":
        assert response.status_code == 403
        return None
    assert response.status_code == 200, page.template
    return response.text


_union: dict[tuple[str, str], set[str]] = {}


def every_id(clients, demo, variant, role) -> set[str]:
    """Ids of every page and fragment the role can open, in this interface."""
    if (variant, role) not in _union:
        ids: set[str] = set()
        for page in HTML_PAGES:
            html = answer(clients, demo, role, page)
            if html is not None:
                ids |= parse(html).ids
        _union[(variant, role)] = ids
    return _union[(variant, role)]


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("page", HTML_PAGES, ids=lambda page: page.template)
def test_every_swap_target_exists(clients, demo, variant, role, page):
    html = answer(clients, demo, role, page)
    if html is None:
        return
    contract = parse(html)
    missing = []
    for target, route in contract.targets:
        if target in contract.ids:
            continue
        if route and route.startswith("/"):
            fragment = clients[role].get(route, headers={"HX-Request": "true"})
            if fragment.status_code == 200 and target in parse(fragment.text).ids:
                continue
        if page.htmx and target in every_id(clients, demo, variant, role):
            continue  # a fragment swaps into the page that hosts it
        missing.append(f"#{target}" + (f" (hx-get {route})" if route else ""))
    assert not missing, f"{variant} {role} {page.template}: no element for {missing}"


@pytest.mark.parametrize("role", ROLES)
def test_every_out_of_band_swap_lands_on_an_element(clients, demo, variant, role):
    known = every_id(clients, demo, variant, role)
    lost = {}
    for page in HTML_PAGES:
        html = answer(clients, demo, role, page)
        if html is None:
            continue
        for landing in parse(html).oob:
            if landing not in known:
                lost.setdefault(page.template, []).append(landing)
    assert not lost, f"{variant} {role}: hx-swap-oob without a landing element: {lost}"


def test_the_contract_is_not_vacuous(clients, demo, variant):
    # The inventory holds pages that target elements: if the parser stopped
    # seeing them, the tests above would pass on nothing.
    totals = [len(parse(answer(clients, demo, "admin", page) or "").targets) for page in HTML_PAGES]
    assert sum(totals) > 20
