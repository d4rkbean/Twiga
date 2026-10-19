"""Fidelity of Panorama, Mon mois, Budgets, Le Cap and Rapports to the mockup."""

from datetime import date
from decimal import Decimal

from backend.database import SessionLocal
from backend.models import CapEntry


def _current_month_start() -> date:
    today = date.today()
    return date(today.year, today.month, 1)


def _delete_current_cap():
    with SessionLocal() as db:
        db.query(CapEntry).filter(CapEntry.month == _current_month_start()).delete()
        db.commit()


# --- Panorama ----------------------------------------------------------------


def test_panorama_account_filter_is_a_drawn_list_not_a_native_select(clients):
    html = clients["admin"].get("/dashboard").text
    filters = html.split('id="dashboard-filters"')[1].split("</form>")[0]
    assert "<select" not in filters
    assert 'aria-haspopup="listbox"' in filters
    assert 'name="account_id"' in filters
    assert "Tous les comptes" in filters


def test_panorama_sentence_opens_with_the_period_and_gives_the_pending_amount(clients):
    html = clients["admin"].get("/dashboard").text
    assert "le foyer a reçu" in html
    assert "il reste" in html
    assert "attendent encore dans La Savane" in html or "attend encore dans La Savane" in html
    # The 90-day shortcut reads as a period, not as a month.
    html = clients["admin"].get("/dashboard/content", params={"period": "90j"}, headers={"HX-Request": "true"}).text
    assert "Sur les 90 derniers jours," in html


def test_panorama_flux_chart_has_month_chips_and_a_readout(clients):
    html = clients["admin"].get("/dashboard").text
    assert 'id="trend-months"' in html
    assert 'id="trend-readout"' in html
    assert 'aria-label="Choisir un mois"' in html


def test_panorama_envelopes_carry_a_pace_tick_and_a_legend(clients):
    html = clients["admin"].get("/dashboard").text
    assert "Rythme au" in html
    assert "Encore dans La Savane" in html


def test_dashboard_expense_figure_shows_what_waits_in_la_savane(clients):
    html = clients["admin"].get("/dashboard").text
    assert "à trier" in html


# --- Mon mois ------------------------------------------------------------------


def test_mon_mois_has_four_pillars_and_a_legend(clients):
    _delete_current_cap()
    with SessionLocal() as db:
        db.add(
            CapEntry(
                month=_current_month_start(),
                planned_income=Decimal("2400.00"),
                planned_essentiel=Decimal("1200.00"),
                planned_choix=Decimal("600.00"),
                planned_imprevu=Decimal("200.00"),
                intention="Cook on Sundays",
            )
        )
        db.commit()
    try:
        html = clients["admin"].get("/cap/mid").text
        assert "Les 4 piliers du mois" in html
        assert "Épargne" in html
        assert "Encore dans La Savane" in html
        assert "Préparer Le Cap" in html
        assert "Revoir le cap du mois" in html
    finally:
        _delete_current_cap()


# --- Budgets -------------------------------------------------------------------


def test_budgets_amount_fields_are_formatted_and_month_bar_sits_in_the_header(clients):
    html = clients["admin"].get("/budgets").text
    header = html.split('id="budgets-filters"')[1].split('id="budgets-content"')[0]
    assert "Copier le mois précédent" in header
    assert "Mois précédent" in header
    assert "fmt2(" in html
    assert 'name="amount_' in html


# --- Le Cap --------------------------------------------------------------------


def test_cap_every_step_has_the_side_panel(clients):
    _delete_current_cap()
    admin = clients["admin"]
    step1 = admin.get("/cap").text
    assert "en direct" in step1 and "pilier par pilier" in step1
    assert "Précédent" in step1 and "Suivant" in step1
    step2 = admin.post("/cap/step2", data={}).text
    assert "Objectif d'épargne" in step2
    assert "Réserve" in step2
    assert "en direct" in step2


def test_cap_savings_goal_is_saved_shown_and_can_be_reopened(clients):
    _delete_current_cap()
    admin = clients["admin"]
    try:
        response = admin.post(
            "/cap/save",
            data={
                "planned_income": "2400",
                "planned_imprevu": "100",
                "savings_withdrawal": "0",
                "savings_goal": "500",
                "intention": "Cook on Sundays",
            },
        )
        assert response.status_code == 200
        assert "Reprendre le cap" in response.text
        assert "Aller au Panorama" in response.text
        with SessionLocal() as db:
            entry = db.query(CapEntry).filter(CapEntry.month == _current_month_start()).one()
            assert entry.savings_goal == Decimal("500.00")

        reopened = admin.get("/cap/reopen", headers={"HX-Request": "true"}).text
        assert "Cook on Sundays" in reopened
        assert "goal: 500.00" in reopened

        # A zero goal means "no goal".
        admin.post("/cap/save", data={"planned_income": "2400", "planned_imprevu": "100", "savings_goal": "0"})
        with SessionLocal() as db:
            entry = db.query(CapEntry).filter(CapEntry.month == _current_month_start()).one()
            assert entry.savings_goal is None
    finally:
        _delete_current_cap()


# --- Rapports ------------------------------------------------------------------


def test_reports_account_filter_is_drawn_and_the_flux_chart_has_a_readout(clients):
    html = clients["admin"].get("/reports").text
    form = html.split('id="reports-account-filter"')[1].split("</form>")[0]
    assert "<select" not in form
    assert 'aria-haspopup="listbox"' in form
    assert 'id="cashflow-readout"' in html
    assert "Ouvrir ce mois" in html
