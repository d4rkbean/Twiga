"""Lot 5, group C of the other way: Projets, Import, Paramètres and the setting
pages, Mon profil, Connexion and the reader's view.

The sentences of Twiga (backend/answers.py) are pure functions, tested without
a database. The screens are rendered in the other way, for each role they are
open to, and the gestures the Classic screens offer are checked to still exist.
"""

import html as html_lib
import re
from datetime import date
from decimal import Decimal

import pytest

from backend import answers
from backend.project_path import project_path
from tests.conftest import switch_variant
from tests.test_other_way import page_of  # noqa: F401  (same helper as the shell tests)


@pytest.fixture
def other_way(monkeypatch, demo):
    monkeypatch.setenv("ENABLE_OTHER_WAY", "true")
    switch_variant("other_way")
    yield
    switch_variant("classic")


def text_of(html: str) -> str:
    """The visible text of a page, tags and spacing removed."""
    stripped = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", html, flags=re.S)
    return re.sub(r"\s+", " ", html_lib.unescape(stripped))


# --- Projets: the sentence --------------------------------------------------

TODAY = date(2026, 10, 19)


def project(name, state, gap, need="93.33", now="60.00"):
    return {"name": name, "state": state, "gap_months": gap, "monthly_effort": Decimal(need), "effort": Decimal(now)}


def test_no_project_invites_to_create_one():
    result = answers.projects_answer([], TODAY)

    assert result.title == "Pas encore de projet."
    assert result.focus is None


def test_each_project_is_named_with_its_verdict_and_the_latest_one_is_adjusted():
    result = answers.projects_answer(
        [project("Vacances", "early", -3, "88.89", "150.00"), project("Vélo", "late", 4)], TODAY
    )

    assert result.title == "Vacances arrive en avance, Vélo a 4 mois de retard."
    assert result.focus == "Vélo"
    assert "93,33 €" in result.detail and "60,00 €" in result.detail
    assert "Le Cap d'octobre" in result.detail


def test_a_single_project_on_time_has_a_calm_sentence():
    result = answers.projects_answer([project("Vacances", "on_time", 0)], TODAY)

    assert result.title == "Vacances arrive à l'heure."
    assert result.focus is None


def test_many_projects_are_counted_instead_of_listed():
    projects = [project(f"P{n}", "late" if n < 2 else "early", 2 if n < 2 else -1) for n in range(5)]

    assert answers.projects_answer(projects, TODAY).title == "2 projets sur 5 ont du retard."


def test_the_cap_of_a_month_elides_before_a_vowel():
    assert answers.cap_of_month(date(2026, 10, 1)) == "Le Cap d'octobre"
    assert answers.cap_of_month(date(2026, 11, 1)) == "Le Cap de novembre"


@pytest.mark.parametrize(
    "state, gap, word",
    [
        ("early", -3, "En avance de 3 mois"),
        ("on_time", 0, "À l'heure"),
        ("late", 4, "À surveiller : 4 mois de retard"),
        ("done", 0, "Objectif atteint"),
        ("none", 0, "Aucun versement régulier"),
    ],
)
def test_a_verdict_is_always_a_word(state, gap, word):
    assert answers.project_verdict(state, gap)[1] == word


def test_the_need_sentence_compares_what_is_put_aside_with_what_is_needed():
    assert answers.project_need_sentence("early", Decimal("88.89"), Decimal("150"))[0] == "success"
    tone, sentence = answers.project_need_sentence("late", Decimal("93.33"), Decimal("60"))
    assert tone == "warning" and "33,33 €" in sentence


# --- Projets: the track -------------------------------------------------------


def test_the_track_covers_twelve_months_and_places_the_markers_on_their_columns():
    path = project_path(TODAY, date(2027, 6, 1), date(2027, 3, 1), "early")

    assert len(path["months"]) == 12
    assert path["months"][0]["year"] == 2026 and path["months"][3]["year"] == 2027  # October, then January
    assert path["today"] < path["reach"] < path["deadline"]
    assert path["solid"]["left"] == path["today"]
    assert path["extra"]["left"] == path["reach"]  # the dashed stretch, from the reach to the deadline


def test_a_late_project_walks_up_to_the_deadline_then_a_pale_stretch_to_the_reach():
    path = project_path(TODAY, date(2027, 3, 1), date(2027, 7, 1), "late")

    assert path["solid"]["left"] + path["solid"]["width"] == pytest.approx(path["deadline"])
    assert path["extra"]["left"] == path["deadline"]


def test_the_track_grows_when_the_reach_is_far_away():
    assert len(project_path(TODAY, date(2027, 3, 1), date(2029, 1, 1), "late")["months"]) > 12


def test_without_a_rhythm_there_is_only_a_deadline():
    path = project_path(TODAY, date(2027, 3, 1), None, "none")

    assert path["reach"] is None and path["solid"] is None and path["extra"] is None


# --- Projets: the screen ------------------------------------------------------


def test_projects_screen_gives_the_sentence_and_every_gesture(clients, other_way):
    html = page_of(clients, "editor", "/projects")
    body = text_of(html)

    assert 'data-ui="other_way"' in html
    assert "Holidays" in body and "À ce rythme" in body and "Il manque" in body
    for gesture in ("Ajouter", "Dépenser", "Modifier", "Nouveau projet", "Historique"):
        assert gesture in body, gesture
    assert 'id="projects-list"' in html and 'id="project-card-' in html
    assert "/projects/create" in html and "/delete" in html and "/spend" in html and "/add" in html


def test_a_project_can_be_created_and_the_sentence_follows(clients, other_way):
    response = clients["admin"].post(
        "/projects/create",
        data={"name": "Roof", "target_amount": "3000", "target_date": "2030-01-01", "current_amount": "100"},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert "Roof" in response.text
