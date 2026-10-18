"""The other way ("L'autre voie"): the template facade and the shell.

Two interfaces behind one `templates` object (backend/templating.py). The
shell of the other way (frontend/templates/other_way/) is a top bar, a bottom
bar and a Plus menu; every template it does not override is the Classic one.
"""

import json
import re

import pytest

from backend import preferences
from backend.templating import templates
from tests.conftest import ROLES, ROOT, switch_variant


@pytest.fixture
def other_way(monkeypatch, demo):
    monkeypatch.setenv("ENABLE_OTHER_WAY", "true")
    switch_variant("other_way")
    yield
    switch_variant("classic")


def page_of(clients, role: str, path: str) -> str:
    response = clients[role].get(path)
    assert response.status_code == 200, path
    return response.text


def shell_of(html: str) -> str:
    """The top bar and the menus it opens (everything before the content), plus the bottom bar."""
    return html[: html.index("<main")] + html[html.rindex('<nav id="tour-b-bottom-nav"'):][:3000]


def top_nav(html: str) -> str:
    return re.search(r'<nav id="tour-b-nav".*?</nav>', html, re.S).group(0)


def current_in(fragment: str) -> list[str]:
    """Labels of the links and buttons flagged aria-current="page"."""
    found = re.findall(r'<(?:a|button)\b[^>]*aria-current="page"[^>]*>(.*?)</(?:a|button)>', fragment, re.S)
    return [re.sub(r"<[^>]+>|\s+", " ", label).strip() for label in found]


# --- The facade -----------------------------------------------------------


def test_each_interface_looks_templates_up_in_its_own_folders():
    classic = templates.for_variant("classic").env.get_template("base.html")
    other_way = templates.for_variant("other_way").env.get_template("base.html")

    assert classic.filename.endswith("frontend/templates/base.html")
    assert other_way.filename.endswith("frontend/templates/other_way/base.html")
    # A template the other way does not override is the Classic one.
    fallback = templates.for_variant("other_way").env.get_template("accounts/index.html")
    assert fallback.filename == templates.for_variant("classic").env.get_template("accounts/index.html").filename


def test_both_environments_share_the_same_filters_and_globals():
    classic, other_way = templates.classic.env, templates.other_way.env

    assert set(classic.filters) == set(other_way.filters)
    assert set(classic.globals) == set(other_way.globals)
    assert templates.env is classic


def test_the_variant_of_the_request_picks_the_shell(clients, other_way):
    html = page_of(clients, "admin", "/dashboard")

    assert 'data-ui="other_way"' in html
    assert 'id="tour-b-nav"' in html and 'id="tour-b-bottom-nav"' in html
    assert 'id="tour-sidebar-savane"' not in html and 'id="tour-import"' not in html


def test_classic_keeps_its_sidebar(clients, demo):
    switch_variant("classic")
    html = page_of(clients, "admin", "/dashboard")

    assert 'data-ui="classic"' in html
    assert 'id="tour-sidebar-savane"' in html and 'id="tour-import"' in html
    assert "tour-b-" not in html


def test_the_other_way_stays_classic_until_it_is_enabled(clients, demo, monkeypatch):
    monkeypatch.delenv("ENABLE_OTHER_WAY", raising=False)
    switch_variant("other_way")
    try:
        html = page_of(clients, "admin", "/dashboard")
    finally:
        switch_variant("classic")

    assert 'data-ui="classic"' in html and "tour-b-" not in html


def test_a_screen_without_an_override_is_the_classic_screen(clients, demo, monkeypatch):
    switch_variant("classic")
    classic = page_of(clients, "admin", "/accounts")
    monkeypatch.setenv("ENABLE_OTHER_WAY", "true")
    switch_variant("other_way")
    try:
        other = page_of(clients, "admin", "/accounts")
    finally:
        switch_variant("classic")

    content = lambda html: re.sub(r"\s+", " ", html[html.index("<main"): html.index("</main>")])
    assert content(other) == content(classic)


def test_a_fragment_can_be_overridden_by_the_other_way(clients, other_way):
    response = clients["admin"].get("/search/quick", params={"q": "super"}, headers={"HX-Request": "true"})

    assert response.status_code == 200
    assert "Supermarket" in response.text
    assert "shadow-lg" not in response.text  # the Classic card chrome is gone: the sheet is the card


def test_python_built_fragments_follow_the_variant(monkeypatch):
    from backend.templating import flash_html

    preferences.set_current("other_way", "system", "normal")
    try:
        assert "Saved" in flash_html("success", "Saved")
    finally:
        preferences.set_current("classic", "system", "normal")


def test_the_login_page_follows_the_cookie(clients, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("ENABLE_OTHER_WAY", "true")
    with TestClient(clients["anonymous"].app, follow_redirects=False) as anonymous:
        anonymous.cookies.set("twiga_ui", "other_way")
        html = anonymous.get("/login").text

    assert 'data-ui="other_way"' in html
    assert "tour-b-nav" not in html, "the login page has no shell"


# --- The shell ------------------------------------------------------------


def test_the_top_bar_has_four_destinations_and_what_goes_with_them(clients, other_way):
    html = page_of(clients, "admin", "/dashboard")
    nav = top_nav(html)

    assert [label for label in re.findall(r"<a[^>]*>(.*?)</a>", nav, re.S)] == ["La Savane", "Panorama", "Le Cap"]
    assert 'href="/transactions/inbox"' in nav and 'href="/dashboard"' in nav and 'href="/cap"' in nav
    assert 'id="tour-b-plus"' in nav and "Plus" in nav
    for marker in ('id="tour-b-search"', 'id="tour-b-help"', 'id="tour-b-avatar"', "Masquer les montants"):
        assert marker in html, marker
    assert "bg-accent " not in shell_of(html)


@pytest.mark.parametrize(
    "path, destination",
    [
        ("/transactions/inbox", ["La Savane"]),
        ("/dashboard", ["Panorama"]),
        ("/cap", ["Le Cap"]),
        ("/cap/mid", ["Le Cap"]),
        ("/budgets", ["Le Cap"]),
        ("/transactions/list", ["Plus"]),
        ("/settings", ["Plus"]),
        ("/profile", ["Plus"]),
        ("/reports", ["Plus"]),
        ("/projects", ["Plus"]),
    ],
)
def test_the_active_destination_follows_the_route(clients, other_way, path, destination):
    html = page_of(clients, "admin", path)

    assert current_in(top_nav(html)) == destination
    bottom = html[html.rindex('<nav id="tour-b-bottom-nav"'):][:3000]
    assert current_in(bottom) == destination


def test_the_menu_opens_with_the_balance_then_groups_by_intention(clients, other_way):
    html = page_of(clients, "admin", "/dashboard")
    menu = html[html.index('aria-label="Plus"'):]

    assert 'hx-get="/dashboard/shell-balance"' in menu and "amount-blur" in menu
    order = [menu.index(title) for title in ("Au quotidien", "Faire le point", "Alimenter", "Régler Twiga")]
    assert order == sorted(order)
    for label in (
        "Opérations", "Mon mois", "Budgets", "Projets", "Traitement en masse", "Rapports", "Importer un relevé",
        "Paramètres", "Comptes", "Catégories", "Règles", "Modes de paiement", "Abonnements", "Chèques",
        "Utilisateurs", "Mon profil",
    ):
        assert label in menu, label
    for href in ("/transactions/list", "/cap/mid", "/budgets", "/projects", "/backlog", "/reports", "/imports/new",
                 "/settings", "/accounts", "/categories", "/rules", "/payment-methods", "/recurring", "/checks",
                 "/users", "/profile"):
        assert f'href="{href}"' in menu, href


@pytest.mark.parametrize("role", ["editor", "viewer"])
def test_admin_only_entries_disappear_for_the_other_roles(clients, other_way, role):
    admin_shell = shell_of(page_of(clients, "admin", "/dashboard"))
    shell = shell_of(page_of(clients, role, "/dashboard"))

    for gone in ('href="/users"', 'href="/imports/new"', "Alimenter", "Importer un relevé"):
        assert gone in admin_shell and gone not in shell, gone
    # Everything else a reader may open is still there.
    for kept in ('href="/settings"', 'href="/accounts"', 'href="/reports"', 'href="/profile"', "Régler Twiga"):
        assert kept in shell, kept


def test_the_menu_entries_match_the_roles_of_auth_py(clients, other_way):
    """The conditions are the ones of backend/auth.py: a role that cannot open a path
    does not get the link, and every link of the shell opens for the role that sees it."""
    from backend import auth

    for role in ROLES:
        shell = shell_of(page_of(clients, role, "/dashboard"))
        hrefs = set(re.findall(r'href="(/[^"#?]*)"', shell))
        refused = {href for href in hrefs if not auth.check_role_access(role, "GET", href)}
        assert refused == set(), f"{role} is offered {refused}"
        hidden = {prefix for prefix in auth._ADMIN_ONLY_PREFIXES if not any(h.startswith(prefix) for h in hrefs)}
        assert hidden == (set(auth._ADMIN_ONLY_PREFIXES) if role != "admin" else set())


def test_the_avatar_menu(clients, other_way):
    html = page_of(clients, "editor", "/dashboard")
    menu = html[html.index('aria-label="Menu utilisateur"', html.index("</header>")):]
    menu = menu[: menu.index("</form>")]

    assert "test_editor" in menu and "Éditeur" in menu
    assert 'href="/profile"' in menu and 'href="/settings"' in menu
    assert "openShell('help')" in menu  # Aide & raccourcis
    assert "window.toggleTheme()" in menu and "closeShell()" in menu  # the theme switch closes the menu
    assert 'hx-post="/logout"' in menu and "text-danger" in menu


def test_the_help_sheet_reuses_the_dialogs_of_the_layout(clients, other_way):
    html = page_of(clients, "admin", "/dashboard")
    sheet = html[html.index('aria-label="Aide &amp; raccourcis"'):][:8000]

    assert "Revoir la visite guidée" in sheet and "startTwigaTour()" in sheet
    assert "Raccourcis clavier" in sheet and "twiga-help-dialog" in sheet
    assert "À propos de Twiga" in sheet and "twiga-about-dialog" in sheet
    assert 'id="twiga-help-dialog"' in html and 'id="twiga-about-dialog"' in html


def test_the_search_sheet_reuses_the_global_search(clients, other_way):
    html = page_of(clients, "admin", "/dashboard")
    sheet = html[html.index('aria-label="Recherche"', html.index("</header>")):][:2500]

    assert "Que cherches-tu ?" in sheet
    assert 'hx-get="/search/quick"' in sheet and 'hx-target="#shell-search-results"' in sheet
    assert 'id="shell-search-results"' in sheet


@pytest.mark.parametrize(
    "path, title",
    [("/transactions/list", "Opérations"), ("/settings", "Paramètres"), ("/dashboard", "Panorama"), ("/cap/mid", "Mon mois"),
     ("/transactions/inbox", "La Savane"), ("/imports/new", "Importer un relevé")],
)
def test_the_mobile_header_carries_the_title_of_the_page(clients, other_way, path, title):
    html = page_of(clients, "admin", path)

    assert re.search(rf'<p class="lg:hidden[^"]*">{title}</p>', html)


def test_the_balance_fragment(clients, demo):
    response = clients["admin"].get("/dashboard/shell-balance", headers={"HX-Request": "true"})

    assert response.status_code == 200
    assert "Solde total" in response.text and "sur 2 comptes" in response.text
    assert "amount-blur" in response.text


def test_escape_and_one_menu_at_a_time_live_in_the_shell_script():
    script = (ROOT / "frontend/static/js/other-way.js").read_text(encoding="utf-8")

    assert "Escape" in script and 'openShell("search")' in script
    assert "this.shell = name" in script  # opening one replaces the previous: a single state


def test_the_sheets_have_a_veil_and_a_close_button(clients, other_way):
    html = page_of(clients, "admin", "/dashboard")

    assert 'class="print:hidden fixed inset-0 z-[8999] bg-scrim"' in html
    for label in ("Plus", "Aide &amp; raccourcis", "Recherche"):
        sheet = html[html.index(f'aria-label="{label}"', html.index("</header>")):][:3000]
        assert "closeShell()" in sheet and "Fermer" in sheet, label


# --- The guided tour ------------------------------------------------------


def steps_of(html: str) -> list[dict]:
    import html as htmllib

    return json.loads(htmllib.unescape(re.search(r'data-steps="([^"]*)"', html).group(1)))


def test_the_classic_tour_keeps_its_five_steps(clients, demo):
    switch_variant("classic")
    steps = steps_of(page_of(clients, "admin", "/dashboard"))

    assert [step["id"] for step in steps] == ["welcome", "import", "nav-savane", "nav-dashboard", "search-icon"]
    assert [step["target"] for step in steps] == [
        None, "#tour-import", "#tour-nav-savane", "#tour-nav-dashboard", "#tour-search-icon",
    ]
    assert [step.get("altTarget") for step in steps] == [
        None, None, "#tour-sidebar-savane", "#tour-sidebar-dashboard", "#tour-desktop-search",
    ]


def test_the_other_ways_tour(clients, other_way):
    steps = steps_of(page_of(clients, "admin", "/dashboard"))

    assert [step["id"] for step in steps] == ["welcome", "destinations", "more", "search", "help"]
    assert "Le reste se cache sous Plus" in [step["title"] for step in steps]
    assert all(step["title"] and step["text"] for step in steps)


@pytest.mark.parametrize("variant_name", ["classic", "other_way"])
def test_every_tour_target_exists_in_the_page(clients, demo, monkeypatch, variant_name):
    monkeypatch.setenv("ENABLE_OTHER_WAY", "true")
    switch_variant(variant_name)
    try:
        html = page_of(clients, "admin", "/dashboard")
    finally:
        switch_variant("classic")
    for step in steps_of(html):
        for key in ("target", "altTarget"):
            if step.get(key):
                assert f'id="{step[key][1:]}"' in html, f"{variant_name}: {step['id']} {key} {step[key]}"
        assert step.get("target") or step.get("altTarget") or step["position"] == "center"


def test_the_tour_script_holds_no_step_of_its_own():
    script = (ROOT / "frontend/static/js/tour.js").read_text(encoding="utf-8")

    assert not re.search(r"#tour-(?!icons)", script), "a target selector is written in tour.js"
    assert "dataset.steps" in script


# --- Activation -----------------------------------------------------------


def test_the_preference_is_choosable_once_enabled(clients, monkeypatch):
    monkeypatch.setenv("ENABLE_OTHER_WAY", "true")
    page = page_of(clients, "admin", "/profile")
    option = re.search(r'<input[^>]*value="other_way"[^>]*>', page, re.S).group(0)

    assert "disabled" not in option
    assert "Bientôt" not in page


def test_switching_the_interface_reloads_the_page(clients, demo, monkeypatch):
    monkeypatch.setenv("ENABLE_OTHER_WAY", "true")
    client = clients["editor"]
    try:
        changed = client.post("/profile/preferences", data={"ui_variant": "other_way"}, headers={"HX-Request": "true"})
        # The display form posts every field on every change: the same variant is no reason to reload.
        same = client.post(
            "/profile/preferences", data={"ui_variant": "other_way", "theme": "dark"}, headers={"HX-Request": "true"}
        )
    finally:
        switch_variant("classic")
        client.post("/profile/preferences", data={"theme": "system"}, headers={"HX-Request": "true"})

    assert changed.headers["HX-Refresh"] == "true"
    assert "HX-Refresh" not in same.headers
