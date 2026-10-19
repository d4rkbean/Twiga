"""Twiga's sentences (backend/answers.py): figures in, text out.

Every function is pure, so the tests only need numbers. The language is the
default one (French, the source of the texts).
"""

from decimal import Decimal

import pytest

from backend import answers
from backend.i18n import gettext as _t

D = Decimal


@pytest.fixture(autouse=True)
def plain_spaces(monkeypatch):
    """The formatter writes thin and no-break spaces: the expected texts below use plain ones."""
    amount, percent = answers.format_amount, answers.percent
    monkeypatch.setattr(answers, "format_amount", lambda value: amount(value).replace(" ", " ").replace(" ", " "))
    monkeypatch.setattr(answers, "percent", lambda value: percent(value).replace(" ", " "))


# --- Verdicts ------------------------------------------------------------------


@pytest.mark.parametrize(
    "percent, key, word",
    [
        (0, "ok", "Dans les clous"),
        (74.9, "ok", "Dans les clous"),
        (75, "watch", "À surveiller"),
        (90, "watch", "À surveiller"),
        (90.1, "almost", "Presque épuisé"),
        (100, "almost", "Presque épuisé"),
        (100.1, "exceeded", "Dépassé"),
    ],
)
def test_a_verdict_is_a_word_and_a_colour(percent, key, word):
    verdict = answers.verdict(percent)

    assert (verdict.key, verdict.word) == (key, word)
    # The colour never stands alone: every verdict carries its text class and its gauge fill.
    assert verdict.text.startswith("text-") and verdict.fill.startswith("progress-")


def test_a_round_amount_loses_its_cents_in_a_headline():
    assert answers.whole(D("517.6")) == "518 €"
    assert answers.whole_or_cents(D("1055.19")).endswith(",19 €")
    assert answers.whole_or_cents(D("300")) == "300 €"


# --- Panorama ------------------------------------------------------------------


def panorama(**overrides):
    figures = dict(
        kind="month",
        month_name="octobre",
        lead="En octobre",
        income=D("4648.00"),
        expense=D("1765.84"),
        envelopes_rest=D("517.60"),
        envelopes_count=4,
        envelopes_percent=D("52"),
        month_pace=87,
        pending_count=14,
        include_pending=True,
        account_name=None,
        shift_on=False,
        last_day=30,
        start_label="01/10",
        end_label="31/10",
    )
    figures.update(overrides)
    return answers.panorama_answer(**figures)


def test_the_panorama_says_what_is_left_to_spend_this_month():
    answer = panorama()

    assert answer.headline == "Il reste 518 € à dépenser d'ici le 30."
    assert "4 enveloppes du mois" in answer.sub and "14 opérations à ranger comprises" in answer.sub
    # The month advances faster than the envelopes: the verdict says so, in green.
    assert answer.bars_tone == "success"
    assert answer.bars_note.startswith("Dans les clous")


def test_the_panorama_follows_the_counter_of_operations_to_sort():
    without = panorama(include_pending=False, envelopes_rest=D("1000"))
    none = panorama(pending_count=0)

    assert "sans compter les 14 opérations à ranger" in without.sub
    assert "sans opération à ranger" in none.sub


def test_the_panorama_says_when_the_envelopes_are_exceeded():
    answer = panorama(envelopes_rest=D("-42.00"), envelopes_percent=D("104"))

    assert answer.headline == "Tu as dépassé tes enveloppes de 42 €."
    assert answer.bars_tone == "danger"


def test_the_panorama_names_the_account_it_is_filtered_on():
    assert "Compte joint" in panorama(account_name="Compte joint").sub


@pytest.mark.parametrize("kind", ["month", "last_month", "other"])
def test_an_empty_period_says_so(kind):
    answer = panorama(kind=kind, income=D("0"), expense=D("0"))

    assert answer.headline == "Rien sur cette période."
    assert "01/10" in answer.sub


def test_a_past_month_tells_what_was_left():
    answer = panorama(kind="last_month", month_name="septembre")

    assert answer.headline == "En septembre, il t'est resté 2 882 €."
    over = panorama(kind="last_month", month_name="septembre", income=D("100"), expense=D("350"))
    assert over.headline == "En septembre, tu as dépensé 250 € de plus que reçu."


def test_any_other_period_tells_what_was_spent():
    answer = panorama(kind="other", lead="Sur les 90 derniers jours")

    assert answer.headline == "Sur les 90 derniers jours tu as dépensé 1 766 €."
    assert answer.bars[0]["kind"] == "spent"


def test_the_three_things_to_look_at_each_say_why_and_offer_one_gesture():
    things = answers.panorama_things(
        pending_count=14,
        pending_total=D("559.23"),
        account_name=None,
        top_envelope={"name": "Sorties", "rest": D("27"), "percent": D("82"), "with_pending": True},
        days_left=4,
        last_day=30,
        cap={"state": "upcoming", "title": "Le Cap d'octobre", "previous": "septembre"},
    )

    assert [t["href"] for t in things] == ["/transactions/inbox", "#enveloppes", "/cap"]
    assert things[0]["title"] == "14 opérations à ranger." and things[0]["primary"]
    assert things[1]["pill"].word == "À surveiller" and "à 4 jours de la fin du mois" in things[1]["text"]
    assert things[2]["title"] == "Le Cap d'octobre arrive." and things[2]["when"] == "Dans 4 jours"
    # At most one of the three is the amber action of the screen.
    assert sum(1 for t in things if t["primary"]) == 1


def test_nothing_to_sort_and_envelopes_in_order_leave_no_amber_action():
    things = answers.panorama_things(
        pending_count=0,
        pending_total=D("0"),
        account_name="Compte joint",
        top_envelope={"name": "Transport", "rest": D("90"), "percent": D("40"), "with_pending": False},
        days_left=20,
        last_day=30,
        cap={"state": "set", "title": "Le Cap de septembre", "previous": ""},
    )

    assert things[0]["title"] == "Rien à ranger." and not any(t["primary"] for t in things)
    assert things[1]["title"] == "Les enveloppes sont dans les clous."
    assert things[2]["href"] == "/cap/mid"


# --- Mon mois ------------------------------------------------------------------


def pillars(*rows):
    return [{"code": code, "percent": percent, "verdict": answers.verdict(percent).key} for code, percent in rows]


def test_mon_mois_names_the_pillar_that_asks_for_a_look():
    headline, sub = answers.month_answer(
        has_plan=True,
        month_name="septembre",
        pillars=pillars(("choix", D("86")), ("imprevu", D("72")), ("essentiel", D("59"))),
        day=26,
        days=30,
        loose=("Choix", D("139.99")),
        next_cap_title="Le Cap d'octobre",
    )

    assert headline == "Choix demande un regard : 86 % de son budget, rangement compris."
    assert "Jour 26 sur 30." in sub and "dans les clous" in sub
    assert "Dans Choix, 139,99 € attendent encore une catégorie." in sub


def test_mon_mois_is_calm_when_every_pillar_is_in_order():
    headline, sub = answers.month_answer(
        has_plan=True,
        month_name="septembre",
        pillars=pillars(("essentiel", D("40")), ("choix", D("30")), ("imprevu", D("10"))),
        day=10,
        days=30,
        loose=None,
        next_cap_title="Le Cap d'octobre",
    )

    assert headline == "Le cap tient : les trois piliers sont dans les clous."
    assert "Le Cap d'octobre" in sub


def test_mon_mois_without_a_cap_invites_to_fix_one():
    headline, _ = answers.month_answer(
        has_plan=False, month_name="octobre", pillars=[], day=1, days=31, loose=None, next_cap_title="Le Cap de novembre"
    )

    assert headline == "Aucun cap n'est fixé pour octobre."


# --- Budgets -------------------------------------------------------------------


def test_budgets_say_what_is_left_to_spread_and_when_it_is_too_much():
    left, sub = answers.budgets_answer(available=D("4615.60"), total=D("2650"), month_label="Septembre 2026")
    zero, _ = answers.budgets_answer(available=D("100"), total=D("100"), month_label="Septembre 2026")
    over, _ = answers.budgets_answer(available=D("100"), total=D("130"), month_label="Septembre 2026")
    none, _ = answers.budgets_answer(available=D("0"), total=D("0"), month_label="Septembre 2026")

    assert left.startswith("Il reste ") and left.endswith(" à répartir.") and "1 965,60" in left
    assert "2 650,00 € budgétés sur 4 615,60 € disponibles." == sub
    assert zero == "Tout est réparti."
    assert over.startswith("Tu répartis 30,00 € de plus")
    assert none == "Il n'y a pas encore de ressources à répartir."


# --- Le Cap --------------------------------------------------------------------


def review(**overrides):
    figures = dict(
        month_name="Septembre",
        next_month_name="octobre",
        has_plan=True,
        result=D("2882.16"),
        pillars=[
            {"name": "Essentiel", "planned": D("2300"), "real": D("1358.46"), "ratio": D("59"), "unbudgeted": D("0")},
            {"name": "Choix", "planned": D("350"), "real": D("299.48"), "ratio": D("86"), "unbudgeted": D("139.99")},
            {"name": "Imprévus", "planned": D("150"), "real": D("107.90"), "ratio": D("72"), "unbudgeted": D("0")},
        ],
    )
    figures.update(overrides)
    return answers.cap_review_answers(**figures)


def test_the_review_has_a_sentence_for_each_step_of_both_flows():
    result = review()

    assert result["group"][0] == "Septembre s'est bien tenu : +2 882,16 € de reste."
    assert "Choix a frôlé son plafond" in result["groupDetail"][0] and "139,99 €" in result["groupDetail"][0]
    assert len(result["group"]) == 2 and len(result["step"]) == 5
    assert result["stepDetail"][3] == "Question 3 sur 4. Facultatif : tu peux passer."


def test_the_review_says_which_pillar_overran():
    result = review(
        pillars=[{"name": "Choix", "planned": D("350"), "real": D("420"), "ratio": D("120"), "unbudgeted": D("0")}]
    )

    assert result["group"][0] == "Septembre a débordé : Choix a dépassé son prévu."


def test_the_review_without_a_cap_just_reports_the_month():
    result = review(has_plan=False)

    assert result["group"][0].startswith("Septembre : +2 882,16 € de reste.")
    assert "Aucun cap n'était fixé" in result["groupDetail"][0]


# --- Rapports ------------------------------------------------------------------


def report(**overrides):
    figures = dict(
        has_data=True,
        des="de septembre 2026",
        plab="septembre 2026",
        period_start_label="septembre 2026",
        in_period="en septembre 2026",
        expense_total=D("1765.84"),
        expense_rows=[{"name": "Logement", "amount": D("1055.19"), "percent": 60}],
        pending_expense=D("559.23"),
        income_total=D("4648"),
        income_rows=[{"name": "Salaire", "amount": D("4000"), "percent": 86}, {"name": "Allocations", "amount": D("375.6"), "percent": 8}],
        shifted_income_label=None,
        result=D("2882.16"),
        twelve={"result": D("30000"), "income": D("50000"), "avg": D("2500")},
        budgets={"has": True, "held": 4, "count": 4, "spent": D("500"), "budget": D("1000"), "saved": D("500")},
        patrimoine={"ok": True, "last": D("16893.97"), "delta": D("1200"), "high": D("17000"), "low": D("15000"), "account": None},
        cap={"ok": True, "month": "septembre 2026", "all_ok": True, "worst": "Choix", "quote": "Un seul restaurant", "rate": 62},
        shop={"empty": False, "total": D("330.7"), "top": "viandes et poissons"},
        change={"ref": True, "dep_delta": D("-240"), "rec_delta": D("0.5"), "prev_label": "août 2026", "cur_label": "Septembre 2026", "unfinished": True, "pending": D("559.23")},
        score={"score": 90, "message": "La girafe est fière de toi !"},
    )
    figures.update(overrides)
    return answers.report_answers(**figures)


def test_each_of_the_nine_questions_has_its_sentence():
    result = report()

    assert list(result) == answers.REPORT_QUESTION_IDS and len(result) == 9
    assert result["dep"][0] == "Surtout dans Logement : 1 055,19 € sur 1 765,84 €."
    assert "60 % des dépenses de septembre 2026" in result["dep"][1] and "559,23 € restent à trier" in result["dep"][1]
    assert result["rec"][0].startswith("Salaire fait l'essentiel")
    assert result["bal"][0] == "Oui : 2 882,16 € mis de côté en septembre 2026."
    assert "60 % des recettes" in result["bal"][1]
    assert result["bud"][0] == "Oui, les 4 budgets ont tenu."
    assert result["cap"][0] == "Oui, le cap de septembre 2026 tient."
    assert result["chg"][0] == "Les dépenses ont baissé de 240 € par rapport à août 2026."
    assert result["score"][0] == "Tu en es à 90 sur 100."


def test_a_period_without_data_has_one_sentence_for_most_questions():
    result = report(has_data=False)

    assert result["dep"][0] == "Twiga ne trouve rien sur cette période."
    # The shopping report looks at twelve months of receipts, not at the period.
    assert result["shop"][0] != "Twiga ne trouve rien sur cette période."


def test_the_report_names_the_pillar_that_moved_the_cap():
    result = report(cap={"ok": True, "month": "septembre 2026", "all_ok": False, "worst": "Choix", "quote": "", "rate": 10})

    assert result["cap"][0] == "Le cap a bougé : le pilier Choix a dépassé son plan."


def test_the_report_asks_for_a_reference_when_there_is_none():
    result = report(change={"ref": False, "dep_delta": D("0"), "rec_delta": D("0"), "prev_label": "x", "cur_label": "y", "unfinished": False, "pending": D("0")})

    assert result["chg"][0] == "Je n'ai pas de référence avant septembre 2026."


def test_the_question_labels_are_the_nine_of_the_brief():
    labels = [str(label) for _, label in answers.REPORT_QUESTIONS]

    assert labels == [
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
    assert _t("Dépassé") == "Dépassé"
