"""Lot 5, group C: Abonnements in the other way (what is still expected this month)."""

from datetime import date
from decimal import Decimal

from backend import answers, crud
from tests.test_lot5c_settings import other_way, page_of, text_of  # noqa: F401  (fixtures and helpers)

HX = {"HX-Request": "true"}


def pattern(label, amount="10.99", status="pending", activity="active", seen=False, days=10):
    return {
        "label_pattern": label, "amount": Decimal(amount), "frequency": "monthly", "frequency_label": "Mensuel",
        "frequency_days": 30, "last_date": date(2026, 9, 28), "next_expected": date(2026, 10, 28), "seen_this_month": seen,
        "activity_status": activity, "days_since_last": days, "category": None, "payment_method": None,
        "occurrences": 3, "status": status,
    }


def overview(patterns, duplicates=()):
    active = [p for p in patterns if p["status"] != "ignored"]
    return {
        "recurring_patterns": patterns, "recurring_active_count": len(active),
        "recurring_monthly_total": sum((p["amount"] for p in active), Decimal("0.00")),
        "recurring_duplicate_groups": list(duplicates),
    }


def test_a_subscription_is_ignored_inactive_seen_or_still_expected():
    assert answers.recurring_state(pattern("A", status="ignored")) == "ignored"
    assert answers.recurring_state(pattern("A", activity="inactive")) == "inactive"
    assert answers.recurring_state(pattern("A", seen=True)) == "seen"
    assert answers.recurring_state(pattern("A")) == "pending"


def test_the_sentence_counts_the_subscriptions_and_the_ones_still_expected():
    assert answers.recurring_answer(12, 3, "1 300,68 €").title == "12 abonnements, 3 attendus ce mois ne sont pas encore passés."
    assert answers.recurring_answer(12, 1, "1 300,68 €").title.endswith("1 attendu ce mois n'est pas encore passé.")
    assert answers.recurring_answer(2, 0, "20,00 €").title == "2 abonnements, tous sont passés ce mois-ci."
    assert "Total mensuel estimé : 1 300,68 €" in answers.recurring_answer(12, 3, "1 300,68 €").detail
    assert answers.recurring_answer(0, 0, "0,00 €").title == "Aucun abonnement détecté pour l'instant."


def test_subscriptions_are_grouped_by_state_with_filters_and_gestures(clients, other_way, monkeypatch):
    patterns = [
        pattern("MUTUELLE", "38.00"), pattern("SPOTIFY"), pattern("SPOTIFY AB"),
        pattern("DEEZER", activity="inactive", days=135), pattern("LOYER", "920.00", status="confirmed", seen=True),
        pattern("COTISATION", "2.10", status="ignored"),
    ]
    monkeypatch.setattr(crud, "get_recurring_patterns_overview", lambda db, today=None: overview(patterns, [[patterns[1], patterns[2]]]))
    html = page_of(clients, "admin", "/recurring")
    body = text_of(html)

    assert "5 abonnements, 3 attendus ce mois ne sont pas encore passés." in body
    for text in ("Attendus ce mois, pas encore vus", "Inactifs ou annulés ?", "Déjà prélevés ce mois", "Ignorés", "Total mensuel estimé",
                 "Ces 2 entrées semblent être le même abonnement : SPOTIFY, SPOTIFY AB", "Même montant (10,99 €)", "Fusionner", "Confirmer", "Ignorer"):
        assert text in body, text
    assert 'id="recurring-content"' in html and "/recurring/confirm" in html and "/recurring/ignore" in html and "/recurring/merge" in html


def test_a_reader_sees_the_subscriptions_without_confirm_ignore_or_merge(clients, other_way, monkeypatch):
    patterns = [pattern("SPOTIFY"), pattern("SPOTIFY AB")]
    monkeypatch.setattr(crud, "get_recurring_patterns_overview", lambda db, today=None: overview(patterns, [patterns]))
    html = page_of(clients, "viewer", "/recurring")

    assert "Attendus ce mois" in text_of(html)
    for hidden in ("/recurring/confirm", "/recurring/ignore", "/recurring/merge", "Fusionner"):
        assert hidden not in html, hidden


def test_nothing_detected_is_a_calm_screen(clients, other_way, monkeypatch):
    monkeypatch.setattr(crud, "get_recurring_patterns_overview", lambda db, today=None: overview([]))
    body = text_of(page_of(clients, "admin", "/recurring"))

    assert "Aucun abonnement détecté pour l'instant." in body
