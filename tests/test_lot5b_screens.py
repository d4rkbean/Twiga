"""Lot 5B: Panorama, Mon mois, Budgets, Le Cap and Rapports of the other way.

The screens of the other way answer with a sentence first (backend/answers.py) and
keep every route and field of the Classic ones. These tests play the screens as
the browser does, in both interfaces: Classic must render exactly what it always
did, the other way must show its sentence, its panels and the gestures that were
added (the counter of operations to sort, the sources of the month's resources,
the side sheet of a category...).
"""

import re
from datetime import date

import pytest

from backend.database import SessionLocal
from backend.models import CapEntry
from tests.conftest import switch_variant


@pytest.fixture
def other_way(monkeypatch, demo):
    monkeypatch.setenv("ENABLE_OTHER_WAY", "true")
    switch_variant("other_way")
    yield
    switch_variant("classic")


def get(clients, path, role="admin", htmx=False):
    response = clients[role].get(path, headers={"HX-Request": "true"} if htmx else {})
    assert response.status_code == 200, path
    return response.text


def text_of(html: str) -> str:
    """The text of a page without its tags, scripts and styles, spaces collapsed."""
    html = re.sub(r"<(script|style)\b.*?</\1>", "", html, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).replace(" ", " ")


def sentence(html: str) -> str:
    return text_of(re.search(r'<h1 id="answer"[^>]*>(.*?)</h1>', html, re.S).group(1))


# --- Classic is untouched ---------------------------------------------------------


@pytest.mark.parametrize(
    "path, marker",
    [
        ("/dashboard", "panorama-data"),
        ("/cap/mid", "Les piliers, du plus tendu"),
        ("/budgets", "budgets-form"),
        ("/cap", "twigaCapFlow"),
        ("/reports", "reports-data"),
    ],
)
def test_classic_keeps_its_own_screens(clients, demo, path, marker):
    switch_variant("classic")

    assert marker not in get(clients, path)


# --- Panorama ---------------------------------------------------------------------


def test_the_panorama_opens_with_a_sentence_and_the_three_things_to_look_at(clients, other_way):
    html = get(clients, "/dashboard")

    assert sentence(html)
    assert "Trois choses à regarder" in html and "Le détail en chiffres" in html
    # The tappable filters of the fragment keep their ids (the contract of the fragments).
    for marker in ('id="dashboard-content"', 'id="dashboard-filters"', 'id="category-detail"', 'id="panorama-data"'):
        assert marker in html, marker
    assert 'hx-target="#dashboard-content"' in html


def test_the_panorama_sentence_follows_the_period_the_account_and_the_counter(clients, other_way, demo):
    month = sentence(get(clients, "/dashboard/content", htmx=True))
    last = sentence(get(clients, "/dashboard/content?period=mois-dernier", htmx=True))
    quarter = sentence(get(clients, "/dashboard/content?period=90j", htmx=True))
    account = get(clients, f"/dashboard/content?account_id={demo['account_id']}", htmx=True)

    assert last.startswith("En ") and quarter.startswith("Sur les 90 derniers jours")
    assert month != last
    assert "Checking account" in text_of(account)


def test_the_counter_of_operations_to_sort_changes_the_envelopes_and_the_sentence(clients, other_way):
    counted = get(clients, "/dashboard/content?tri=1", htmx=True)
    ignored = get(clients, "/dashboard/content?tri=0", htmx=True)

    assert 'aria-checked="true"' in counted and 'aria-checked="false"' in ignored
    assert 'name="tri" id="panorama-tri" value="0"' in ignored
    assert "comprises" in text_of(counted) or "sans opération" in text_of(counted)
    assert "sans compter" in text_of(ignored) or "sans opération" in text_of(ignored)


def test_a_click_on_a_category_opens_its_operations_in_a_panel(clients, other_way, demo):
    start, today = date.today().replace(day=1).isoformat(), date.today().isoformat()
    html = get(
        clients,
        f"/dashboard/category-transactions?category_id={demo['category_id']}&start={start}&end={today}"
        "&label=Month&type=expense&name=Food",
        htmx=True,
    )

    assert "Food" in html and "Voir dans Opérations" in html and "f_category=" in html


def test_operations_without_a_category_lead_to_la_savane(clients, other_way):
    start, today = date.today().replace(day=1).isoformat(), date.today().isoformat()
    html = get(
        clients,
        f"/dashboard/category-transactions?category_id=none&start={start}&end={today}&label=Month&type=expense&name=To+sort",
        htmx=True,
    )

    assert "/transactions/inbox" in html and "Ranger dans La Savane" in html


def test_the_panorama_filters_still_reach_both_period_and_account(clients, other_way):
    html = get(clients, "/dashboard")

    assert 'name="period"' in html and 'name="account_id"' in html and 'name="shift_income"' in html
    assert "Décaler recettes" in html and "Voir le rapport complet" in html


# --- Mon mois ---------------------------------------------------------------------


def test_mon_mois_lists_the_pillars_from_the_tightest(clients, other_way):
    html = get(clients, "/cap/mid")

    assert sentence(html)
    assert "Les piliers, du plus tendu au plus tranquille" in html
    assert "Ajuster le plan du mois" in html and 'href="/budgets"' in html
    # Mon mois belongs to Panorama: its neighbour strip names the two.
    assert 'aria-label="Panorama, écrans voisins"' in html


def test_mon_mois_totals_add_up_whatever_waits_in_la_savane(demo):
    from backend.month_view import build_month_view

    with SessionLocal() as db:
        view = build_month_view(db, date.today())

    assert sum(p.pending for p in view.pillars) == view.pending_total
    assert sum(p.spent for p in view.pillars) == view.spent_total
    # Tightest first.
    ranks = [(p.verdict.key != "ok", p.percent) for p in view.pillars]
    assert ranks == sorted(ranks, reverse=True)


# --- Budgets ----------------------------------------------------------------------


def test_budgets_open_with_what_is_left_to_spread(clients, other_way):
    html = get(clients, "/budgets")

    assert sentence(html)
    for marker in ('id="budgets-content"', 'id="budgets-form"', 'id="budgets-filters"', 'name="savings_withdrawal"'):
        assert marker in html, marker
    assert "Copier le mois précédent" in html and "Enregistrer" in html


def test_budgets_still_save_the_same_fields(clients, other_way, demo):
    today = date.today()
    path = f"/budgets/save?month={today.month}&year={today.year}"
    page = get(clients, f"/budgets/content?month={today.month}&year={today.year}", htmx=True)
    field = re.search(r'name="(amount_\d+)"', page).group(1)

    saved = clients["admin"].post(path, data={field: "123,45"}, headers={"HX-Request": "true"})

    assert saved.status_code == 200
    assert "123.45" in saved.text
    copied = clients["admin"].post(
        f"/budgets/copy-previous?month={today.month}&year={today.year}", headers={"HX-Request": "true"}
    )
    assert copied.status_code == 200 and 'id="budgets-form"' in copied.text


# --- Le Cap -----------------------------------------------------------------------


@pytest.fixture
def clean_cap():
    """The ritual writes a cap and a setting: put them back as they were."""
    from backend import crud

    yield
    with SessionLocal() as db:
        db.query(CapEntry).filter(CapEntry.month == date.today().replace(day=1)).delete()
        crud.get_cap_settings(db).income_source = "recettes_precedent"
        db.commit()


def test_the_cap_opens_on_the_review_and_runs_the_six_steps_in_the_browser(clients, other_way):
    html = get(clients, "/cap")

    assert sentence(html)
    assert 'id="cap-wizard"' in html and "twigaCapFlow()" in html
    # The frise names the six steps; the mobile flow shows five gestures here.
    for label in ("Bilan", "Un mot", "Ressources", "Les piliers", "Épargne", "Intention"):
        assert label in html, label
    assert 'hx-post="/cap/step2"' in html
    for field in ("reflection_unexpected", "reflection_regret", "reflection_proud", "reflection_worked_well"):
        assert f'name="{field}"' in html


def test_the_review_posts_its_words_and_the_plan_comes_back_with_the_same_fields(clients, other_way, clean_cap):
    plan = clients["admin"].post("/cap/step2", data={"reflection_regret": "Too many takeaways"}, headers={"HX-Request": "true"}).text

    assert 'hx-post="/cap/save"' in plan
    for field in ("planned_income", "planned_imprevu", "savings_withdrawal", "savings_goal", "intention"):
        assert f'name="{field}"' in plan, field
    assert re.search(r'name="amount_\d+"', plan)
    # The words written at the first step travel with the plan, untouched.
    assert 'name="reflection_regret" value="Too many takeaways"' in plan


def test_going_back_to_the_review_keeps_what_was_written(clients, other_way):
    html = clients["admin"].post("/cap/step1", data={"reflection_proud": "Cooked at home"}, headers={"HX-Request": "true"}).text

    assert "Cooked at home" in html


def test_a_source_picked_in_the_ritual_becomes_the_setting(clients, other_way, clean_cap):
    from backend import crud

    html = clients["admin"].post("/cap/step2", data={"income_source": "fixe"}, headers={"HX-Request": "true"}).text

    with SessionLocal() as db:
        assert crud.get_cap_settings(db).income_source == "fixe"
    assert "Source actuelle : Un montant fixe" in text_of(html)
    # An unknown code changes nothing.
    clients["admin"].post("/cap/step2", data={"income_source": "nonsense"}, headers={"HX-Request": "true"})
    with SessionLocal() as db:
        assert crud.get_cap_settings(db).income_source == "fixe"


def test_the_first_cap_skips_the_review(clients, other_way, clean_cap):
    html = clients["admin"].post("/cap/step2", data={"first": "1"}, headers={"HX-Request": "true"}).text

    assert '"first": true' in html.replace("&#34;", '"')


def test_fixing_the_cap_saves_the_month_and_confirms(clients, other_way, clean_cap):
    plan = clients["admin"].post("/cap/step2", data={}, headers={"HX-Request": "true"}).text
    fields = {"planned_income": "2400", "planned_imprevu": "150", "savings_withdrawal": "0", "savings_goal": "", "intention": "Cook at home"}
    fields.update({name: "50" for name in re.findall(r'name="(amount_\d+)"', plan)})

    done = clients["admin"].post("/cap/save", data=fields, headers={"HX-Request": "true"}).text

    assert "Le cap est fixé" in done and "Cook at home" in done and 'href="/dashboard"' in done
    with SessionLocal() as db:
        entry = db.query(CapEntry).filter(CapEntry.month == date.today().replace(day=1)).one()
        assert entry.intention == "Cook at home" and entry.planned_imprevu == 150


def test_a_cap_already_fixed_shows_its_confirmation(clients, other_way, clean_cap):
    clients["admin"].post(
        "/cap/save",
        data={"planned_income": "1000", "planned_imprevu": "10", "intention": "Save"},
        headers={"HX-Request": "true"},
    )

    assert "Le cap est fixé" in get(clients, "/cap")
    reopened = get(clients, "/cap/reopen", htmx=True)
    assert 'hx-post="/cap/save"' in reopened


# --- Rapports ---------------------------------------------------------------------


QUESTIONS = [
    "Où est parti l'argent ?",
    "D'où vient l'argent ?",
    "Est-ce que le foyer épargne ?",
    "Les budgets ont-ils tenu ?",
    "Que vaut le foyer ?",
    "Le cap a-t-il tenu ?",
    "Que coûtent les courses ?",
    "Qu'est-ce qui a changé ?",
    "Comment je me débrouille ?",
]


def test_the_reports_ask_nine_questions_and_answer_each_with_a_sentence(clients, other_way):
    html = get(clients, "/reports")

    for question in QUESTIONS:
        assert question.replace("'", "&#39;") in html or question in html, question
    assert html.count('x-show="q === ') >= 9
    # The old tabs are gone from the page, their content answers the questions.
    assert 'role="tablist"' not in html
    assert sentence(html)


@pytest.mark.parametrize("question", ["dep", "rec", "bal", "bud", "pat", "cap", "shop", "chg", "score"])
def test_every_question_can_be_the_one_asked(clients, other_way, question):
    html = get(clients, f"/reports?q={question}")

    assert f"q: '{question}'" in html


def test_an_unknown_question_falls_back_on_the_first(clients, other_way):
    assert "q: 'dep'" in get(clients, "/reports?q=whatever")


def test_the_reports_keep_their_period_account_and_shift_controls(clients, other_way):
    html = get(clients, "/reports")

    for marker in ('id="reports-account-filter"', 'id="reports-content"', 'id="report-sheet"', "/reports/export.csv", "window.print()"):
        assert marker in html, marker
    assert "Décaler les recettes" in html and "Plus de critères" in html and "Score Twiga" in html


def test_the_score_twiga_is_still_computed_and_explained(clients, other_way):
    html = get(clients, "/reports?q=score")

    assert "Score Twiga" in html and "Catégorisation" in html and "/ 100" in html
    assert re.search(r"Budgets \d+/40", html)


def test_a_category_opens_a_side_sheet_with_its_operations_and_trend(clients, other_way, demo):
    html = get(clients, f"/reports/category-sheet?type=expense&category_id={demo['category_id']}&category_name=Food", htmx=True)

    assert "Food" in html and "/reports/category-trend" in html and "/reports/transactions" in html
    # The sheet loads the two existing fragments by itself.
    assert html.count('hx-trigger="load"') == 2


def test_the_sheet_of_uncategorised_expenses_points_to_la_savane(clients, other_way):
    html = get(clients, "/reports/category-sheet?type=expense&category_id=none&category_name=To+sort", htmx=True)

    assert "/transactions/inbox" in html and "/reports/category-trend" not in html


def test_the_report_fragments_are_the_other_ways_in_the_other_way(clients, other_way, demo):
    listing = get(clients, "/reports/transactions?type=expense", htmx=True)
    trend = get(clients, f"/reports/category-trend?category_id={demo['category_id']}", htmx=True)

    assert 'id="report-tx-list-expense"' in listing and "Exporter en CSV" in listing
    assert 'id="category-trend-chart"' in trend and "<dialog" not in trend


def test_the_reports_page_of_classic_is_not_given_the_other_ways_figures(clients, demo):
    switch_variant("classic")
    html = get(clients, "/reports")

    assert 'role="tablist"' in html and "report_sentences" not in html


# --- English -------------------------------------------------------------------------


@pytest.fixture
def english(other_way):
    """The three demo accounts read the interface in English."""
    from backend.models import User

    with SessionLocal() as db:
        db.query(User).update({User.language: "en"})
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(User).update({User.language: "fr"})
        db.commit()


@pytest.mark.parametrize("path", ["/dashboard", "/cap/mid", "/budgets", "/cap", "/reports", "/reports?q=bal", "/reports?q=chg"])
def test_the_screens_render_in_english_with_their_sentences_translated(clients, english, path):
    html = clients["admin"].get(path).text

    assert 'lang="en"' in html
    heading = sentence(html)
    assert heading and not re.search(r"\b(le|la|des|du|un|une|les|tu|il|reste|dépenser)\b", heading, re.I), heading
