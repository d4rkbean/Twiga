"""The guided tour of each screen, in both interfaces.

Every screen of the inventory declares its steps in a `tour_steps` block
(backend/tours.py). Here: the steps are valid and point at elements of the page
that is rendered with the demo data; a reader keeps only the steps that explain
what a reader can do; what an account has been offered is remembered per screen
and per account; the texts are translated; Aide offers the tour of the open
screen next to the welcome tour.
"""

import json
import re
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

from backend import auth
from backend.database import SessionLocal
from backend.icons import available as icon_names
from backend.models import User
from backend.tours import SCREEN_TOURS
from tests.conftest import ROLES
from tests.test_amber import render
from tests.test_no_emoji import PICTOGRAPH
from tests.test_pages import PAGES

SCREENS = sorted(SCREEN_TOURS)
ADMIN_ONLY = {"import", "users"}  # their pages answer 403 to the other roles
POSITIONS = {"top", "bottom", "left", "right", "center"}
TARGET = re.compile(r'^(#[A-Za-z][\w-]*|\[data-tour="[a-z0-9-]+"\])$')
# Steps per screen: 3 to 6, except Le Cap where every step of the assistant
# brings its own (the tour skips the ones that are not on screen).
MAX_STEPS = {"cap": 9}
SCREEN_PAGES = {page.template: page for page in PAGES if not page.htmx}


class Page(HTMLParser):
    """The ids and data-tour names of a page, and its tour root."""

    def __init__(self):
        super().__init__()
        self.anchors: set[str] = set()
        self.tour_attrs: dict[str, str] = {}

    def handle_starttag(self, tag, attrs):
        attributes = {name: value or "" for name, value in attrs}
        if attributes.get("id"):
            self.anchors.add("#" + attributes["id"])
        if attributes.get("data-tour"):
            self.anchors.add(f'[data-tour="{attributes["data-tour"]}"]')
        if "data-screen-steps" in attributes:
            self.tour_attrs = attributes


def read(html: str) -> tuple[Page, dict]:
    page = Page()
    page.feed(html)
    steps = json.loads(page.tour_attrs.get("data-screen-steps") or "[]")
    return page, {"screen": page.tour_attrs.get("data-screen", ""), "steps": steps}


def tour_of(clients, demo, variant, screen, role="admin"):
    html = render(clients, demo, SCREEN_PAGES[SCREEN_TOURS[screen]], variant, role).text
    return read(html), html


@pytest.mark.parametrize("screen", SCREENS)
def test_every_screen_has_a_valid_tour(clients, demo, variant, screen):
    (page, tour), _html = tour_of(clients, demo, variant, screen)
    steps = tour["steps"]

    assert tour["screen"] == screen
    assert 3 <= len(steps) <= MAX_STEPS.get(screen, 6), f"{variant} {screen}: {len(steps)} steps"
    assert len({step["title"] for step in steps}) == len(steps), "two steps share a title"
    for step in steps:
        where = f"{variant} {screen} {step['title']!r}"
        assert step["icon"] in icon_names(), f"{where}: unknown icon {step['icon']!r}"
        assert step["position"] in POSITIONS, where
        assert 0 < len(step["title"]) <= 40, where
        assert step["text"].startswith("<p>") and len(re.sub("<[^>]+>", "", step["text"])) <= 320, where
        assert not PICTOGRAPH.search(step["title"] + step["text"]), f"{where}: emoji"
        assert TARGET.match(step["target"]), f"{where}: target {step['target']!r}"
        if step.get("altTarget"):
            assert TARGET.match(step["altTarget"]), where
        if not step.get("optional"):
            found = step["target"] in page.anchors or step.get("altTarget") in page.anchors
            assert found, f"{where}: {step['target']} is not in the rendered page"


def test_every_screen_of_the_inventory_has_a_page():
    assert all(path in SCREEN_PAGES for path in SCREEN_TOURS.values())


@pytest.mark.parametrize("screen", [screen for screen in SCREENS if screen not in ADMIN_ONLY])
def test_a_reader_keeps_only_what_a_reader_can_do(clients, demo, variant, screen):
    (page, viewer), _ = tour_of(clients, demo, variant, screen, role="viewer")

    assert viewer["screen"] == screen
    assert len(viewer["steps"]) >= 2, f"{variant} {screen}: nothing left for a reader"
    assert not any(step.get("write") for step in viewer["steps"])
    for step in viewer["steps"]:
        if not step.get("optional"):
            assert step["target"] in page.anchors or step.get("altTarget") in page.anchors, (variant, screen, step["title"])


def test_the_write_steps_are_dropped_for_a_reader(clients, demo, variant):
    (_p, admin), _ = tour_of(clients, demo, variant, "budgets")
    (_p, viewer), _ = tour_of(clients, demo, variant, "budgets", role="viewer")

    assert any(step.get("write") for step in admin["steps"])
    assert len(viewer["steps"]) < len(admin["steps"])


@pytest.fixture
def forget(demo):
    """Every account back to "no screen offered", before and after."""

    def reset():
        with SessionLocal() as db:
            db.query(User).update({User.tours_seen: None})
            db.commit()

    reset()
    yield
    reset()


def tour_attribute(html: str, name: str) -> str:
    page = Page()
    page.feed(html)
    return page.tour_attrs.get(name, "")


def seen_flag(clients, demo, variant, role, screen="dashboard"):
    html = render(clients, demo, SCREEN_PAGES[SCREEN_TOURS[screen]], variant, role).text
    return tour_attribute(html, "data-screen-seen")


def stored(role, demo):
    with SessionLocal() as db:
        return db.get(User, demo[f"user_{role}"]).tours_seen


def test_a_screen_is_remembered_per_screen_and_per_account(clients, demo, variant, forget):
    assert seen_flag(clients, demo, variant, "admin") == "false"

    response = clients["admin"].post("/profile/screen-tour-seen", data={"screen": "dashboard"})
    assert response.status_code == 204

    assert seen_flag(clients, demo, variant, "admin") == "true"
    assert seen_flag(clients, demo, variant, "admin", "budgets") == "false"  # another screen
    assert seen_flag(clients, demo, variant, "editor") == "false"  # another account
    assert list(stored("admin", demo)) == ["dashboard"]
    assert stored("editor", demo) is None


def test_the_first_offer_is_kept_when_it_is_repeated(clients, demo, forget):
    clients["admin"].post("/profile/screen-tour-seen", data={"screen": "cap"})
    first = stored("admin", demo)["cap"]
    clients["admin"].post("/profile/screen-tour-seen", data={"screen": "cap"})

    assert stored("admin", demo)["cap"] == first


@pytest.mark.parametrize("role", ROLES)
def test_every_role_can_remember_its_own_screens(clients, demo, forget, role):
    assert clients[role].post("/profile/screen-tour-seen", data={"screen": "rules"}).status_code == 204
    assert list(stored(role, demo)) == ["rules"]


def test_an_unknown_screen_is_refused(clients, demo, forget):
    for screen in ("nowhere", "", "../etc"):
        response = clients["admin"].post("/profile/screen-tour-seen", data={"screen": screen})
        assert response.status_code == 422
    assert stored("admin", demo) is None


def test_the_route_needs_a_valid_account(app, clients, demo, forget):
    anonymous = clients["anonymous"].post("/profile/screen-tour-seen", data={"screen": "cap"})
    forged = TestClient(app, follow_redirects=False)
    forged.cookies.set(auth.SESSION_COOKIE_NAME, "not-a-session")

    assert anonymous.status_code in (302, 303, 307, 401, 403)
    assert forged.post("/profile/screen-tour-seen", data={"screen": "cap"}).status_code in (302, 303, 307, 401, 403)
    assert all(stored(role, demo) is None for role in ROLES)


def test_the_screen_tour_is_not_a_welcome_tour(clients, demo, variant, forget):
    clients["admin"].post("/profile/screen-tour-seen", data={"screen": "dashboard"})
    html = render(clients, demo, SCREEN_PAGES["/dashboard"], variant).text

    assert tour_attribute(html, "data-pending") == "true"  # the welcome tour is its own memory
    assert "twiga-tour-invite" in html and "Découvrir cet écran ?" in html


def test_the_page_without_a_tour_has_no_screen_tour(clients, demo, variant):
    html = render(clients, demo, SCREEN_PAGES["/accounts/detect-transfers"], variant).text

    assert tour_attribute(html, "data-screen") == ""
    assert tour_attribute(html, "data-screen-steps") == "[]"
    assert "data-help-screen-tour" not in html
    assert "Revoir la visite de bienvenue" in html


def test_aide_offers_the_tour_of_the_open_screen(clients, demo, variant):
    html = render(clients, demo, SCREEN_PAGES["/dashboard"], variant).text

    # Aide has one entry per dialog; the other way carries the layout dialog too.
    assert html.count("data-help-screen-tour") == (1 if variant == "classic" else 2)
    assert "window.startScreenTour()" in html and "Visite de cet écran" in html
    assert "Revoir la visite de bienvenue" in html and "window.startTwigaTour()" in html
    assert "Raccourcis clavier" in html and "À propos de Twiga" in html


def test_the_tour_script_keeps_the_rules_of_the_brief():
    from tests.conftest import ROOT

    script = (ROOT / "frontend/static/js/tour.js").read_text(encoding="utf-8")
    css = (ROOT / "frontend/static/css/tour.css").read_text(encoding="utf-8")

    assert "prefers-reduced-motion" in script and "prefers-reduced-motion: reduce" in css
    assert "scrollIntoView" in script  # the target is brought on screen (mobile)
    assert "screen-tour-seen" in script and "twiga_screen_tours" in script  # server, then local fallback
    assert "Découvrir" not in script  # the texts come from the template


@pytest.fixture
def english(demo):
    with SessionLocal() as db:
        db.query(User).update({User.language: "en"})
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(User).update({User.language: "fr"})
        db.commit()


# Names that are the same in both languages.
PROPER_NAMES = {"Budgets", "Panorama", "Import", "Cap"}


@pytest.mark.parametrize("screen", SCREENS)
def test_the_tour_is_translated(clients, demo, variant, screen):
    (_p, french), _ = tour_of(clients, demo, variant, screen)
    with SessionLocal() as db:
        db.query(User).update({User.language: "en"})
        db.commit()
    try:
        (_p, english_tour), _ = tour_of(clients, demo, variant, screen)
    finally:
        with SessionLocal() as db:
            db.query(User).update({User.language: "fr"})
            db.commit()

    assert len(english_tour["steps"]) == len(french["steps"])
    for fr, en in zip(french["steps"], english_tour["steps"]):
        assert en["text"] != fr["text"], f"{variant} {screen}: text not translated: {fr['title']!r}"
        assert en["title"] != fr["title"] or fr["title"] in PROPER_NAMES, f"{variant} {screen}: {fr['title']!r}"
        assert not re.search(r"[éèêàçùô]", en["title"] + en["text"]), f"{variant} {screen}: French left in {en['title']!r}"


def test_the_invitation_and_the_help_are_translated(clients, demo, variant, english):
    html = render(clients, demo, SCREEN_PAGES["/dashboard"], variant).text

    assert "Discover this screen?" in html and "Later" in html
    assert "Tour of this screen" in html and "Replay the welcome tour" in html
    assert "Découvrir cet écran" not in html
