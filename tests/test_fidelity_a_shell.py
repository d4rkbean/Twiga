"""Fidelity of the shell (sidebar, top bar, mobile bar, avatar sheet) to the mockup."""


def _sidebar(html: str) -> str:
    return html.split("<aside")[1].split("</aside>")[0]


def test_sidebar_lists_the_mockup_entries_in_order(clients):
    side = _sidebar(clients["admin"].get("/dashboard").text)
    labels = ["La Savane", "Traitement en masse", "Panorama", "Opérations", "Mon mois", "Le Cap",
              "Projets", "Import", "Rapports", "Paramètres", "Solde total", "Masquer les montants", "Thème"]
    positions = [side.index(label) for label in labels]
    assert positions == sorted(positions)
    assert 'id="sidebar-pending-count"' in side
    for href in ("/backlog", "/cap", "/cap/mid", "/reports", "/imports/new"):
        assert f'href="{href}"' in side


def test_sidebar_le_cap_and_mon_mois_are_separate_active_states(clients):
    cap = _sidebar(clients["admin"].get("/cap").text)
    assert 'href="/cap"\n      title="Le Cap"\n      aria-current="page"' in cap
    assert 'href="/cap/mid"\n      title="Mon mois"\n      aria-current' not in cap
    mid = _sidebar(clients["admin"].get("/cap/mid").text)
    assert 'href="/cap/mid"\n      title="Mon mois"\n      aria-current="page"' in mid
    assert 'href="/cap"\n      title="Le Cap"\n      aria-current' not in mid


def test_sidebar_pending_count_endpoint_returns_a_bare_number_or_nothing(clients):
    response = clients["admin"].get("/dashboard/sidebar-pending", headers={"HX-Request": "true"})
    assert response.status_code == 200
    assert response.text == "" or response.text.isdigit()


def test_top_bar_has_density_theme_privacy_help_and_import(clients):
    html = clients["admin"].get("/dashboard").text
    header = html.split("<header")[1].split("</header>")[0]
    for marker in ('id="tour-density"', 'id="tour-theme-toggle"', 'id="tour-header-privacy"',
                   "twiga-help-dialog", 'id="tour-import"'):
        assert marker in header
    for label in ("Compact", "Normal", "Aéré"):
        assert label in header
    assert "twigaSetDensity" in html


def test_avatar_sheet_matches_the_mobile_mockup(clients):
    sheet = clients["admin"].get("/dashboard").text.split("BOTTOM SHEET")[1]
    for label in ("Le Cap", "Budgets", "Rapports", "Mon profil", "Paramètres", "Aide &amp; raccourcis",
                  "Revoir la visite de bienvenue", "Thème", "Se déconnecter"):
        assert label in sheet
    order = [sheet.index(x) for x in ("Le Cap", "Mon profil", "Aide &amp; raccourcis", "Se déconnecter")]
    assert order == sorted(order)
