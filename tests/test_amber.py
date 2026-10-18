"""One solid amber fill per screen.

Amber is the colour of the primary action: a screen with two amber buttons has
no primary action. The shell's "Importer" button (frontend/templates/_header.html)
is amber unless the screen sets `demote_import` because it has its own.

An amber fill is an element carrying `btn-primary` or `bg-accent`. Not counted:
the progress stripes of the import stepper (`h-1`), the confirmation dialog
(only shown on demand) and anything collapsed behind `x-show`, `hidden` or a
`<template>` (a form that opens on a click is not on the screen yet).
"""

from html.parser import HTMLParser

import pytest

from tests.test_pages import PAGES, request

AMBER_CLASSES = {"btn-primary", "bg-accent"}
# Void elements never get an end tag: they must not be pushed on the stack.
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class AmberCounter(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack: list[bool] = []  # one entry per open element: does it hide its content?
        self.dialog_depth = 0
        self.fills: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in VOID:
            return
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        hidden = (
            tag in {"template", "script", "style"}
            or "x-show" in attributes
            or "x-cloak" in attributes
            or "hidden" in classes
            or "display: none" in (attributes.get("style") or "")
        )
        is_fill = bool(AMBER_CLASSES & set(classes)) and "h-1" not in classes
        if is_fill and not any(self.stack) and not self.dialog_depth and not hidden:
            self.fills.append(f"<{tag} class=\"{attributes.get('class')}\">")
        self.stack.append(hidden)
        if tag == "dialog":
            self.dialog_depth += 1

    def handle_endtag(self, tag):
        if tag in VOID or not self.stack:
            return
        self.stack.pop()
        if tag == "dialog":
            self.dialog_depth -= 1


def amber_fills(html: str) -> list[str]:
    counter = AmberCounter()
    counter.feed(html)
    return counter.fills


# The style guide shows every button variant on purpose.
NOT_SCREENS = {"/", "/health", "/design-system", "/export/json", "/export/restore/progress"}
FULL_PAGES = [
    page for page in PAGES
    if not page.htmx and not page.template.endswith((".csv", ".js")) and page.template not in NOT_SCREENS
]


@pytest.mark.parametrize("page", FULL_PAGES, ids=lambda page: page.template)
def test_a_screen_has_at_most_one_amber_fill(clients, demo, page):
    client = clients["anonymous"] if page.public else clients["admin"]
    html = request(client, page, demo).text
    fills = amber_fills(html)
    assert len(fills) <= 1, f"{page.template}: {len(fills)} amber fills: {fills}"


@pytest.mark.parametrize("page", FULL_PAGES, ids=lambda page: page.template)
def test_a_screen_with_its_own_primary_action_demotes_importer(clients, demo, page):
    if page.public:
        pytest.skip("the login page has no shell")
    html = request(clients["admin"], page, demo).text
    shell_import = html[html.index('id="tour-import"'):][:600]
    amber_import = "bg-accent text-on-accent" in shell_import
    # Buttons that only appear once a form is opened or a step is reached
    # count here: the screen owns an amber action, so Importer must stay quiet.
    if "btn-primary" in html:
        assert not amber_import, f"{page.template} has its own btn-primary: add demote_import"
