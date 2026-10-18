"""The redesigned Panorama, Reports, Mon mois, Budgets and Le Cap screens keep
their behaviour and follow the rules of the redesign (minus sign, one amber
button per screen, verdicts with a word)."""

MINUS = "−"
AMBER_IMPORT = "bg-accent text-on-accent hover:bg-accent-hover"
QUIET_IMPORT = "border border-border-strong text-primary hover:bg-sunken"


def test_panorama_period_is_a_group_of_pills(clients):
    html = clients["admin"].get("/dashboard").text
    assert 'type="radio"' in html and 'name="period"' in html
    assert '<select name="period"' not in html
    # The summary sentence and the figures strip.
    assert "le foyer a reçu" in html
    assert "Taux d'épargne" in html


def test_panorama_amounts_use_the_typographic_minus(clients):
    # The demo data has expenses: the period expense total is negative.
    html = clients["admin"].get("/dashboard").text
    assert MINUS in html


def test_panorama_fragment_refreshes_the_shift_label(clients):
    response = clients["admin"].get("/dashboard/content", headers={"HX-Request": "true"})
    assert 'id="panorama-period-label"' in response.text
    assert 'hx-swap-oob="true"' in response.text


def test_importer_stays_amber_except_on_screens_with_their_own_primary_action(clients):
    admin = clients["admin"]
    assert AMBER_IMPORT in admin.get("/dashboard").text
    assert AMBER_IMPORT in admin.get("/reports").text
    for path in ("/budgets", "/cap"):
        html = admin.get(path).text
        assert AMBER_IMPORT not in html, path
        assert QUIET_IMPORT in html, path


def test_budgets_are_grouped_by_pillar_with_steppers(clients):
    html = clients["admin"].get("/budgets").text
    assert 'id="group-' in html
    assert "bump(" in html
    assert "Pas de réglage" in html


def test_reports_have_an_export_and_worded_changes(clients):
    html = clients["admin"].get("/reports").text
    assert "Exporter" in html
    assert "/reports/export.csv" in html
    assert "vs période précédente" in html
    assert ("en hausse" in html) or ("en baisse" in html)
    # No emoji left as an icon.
    assert "ℹ️" not in html


def test_reports_export_csv_still_answers(clients):
    response = clients["admin"].get("/reports/export.csv")
    assert response.status_code == 200
    assert MINUS not in response.text


def test_mon_mois_shows_the_rhythm_marker(clients):
    html = clients["admin"].get("/cap/mid").text
    assert "Mon mois" in html
    assert "jour" in html


def test_cap_steps_are_named(clients):
    html = clients["admin"].get("/cap").text
    assert "Étapes du rituel" in html
    assert 'aria-current="step"' in html
