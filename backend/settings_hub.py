"""The figures the settings hub of the other way shows next to each subject.

One place that gathers them (tiles of "Ce qui change souvent", the sentence of
Twiga, the examples of the settings search). The Classic page ignores the
extra keys: a template only reads what it names.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from backend import answers, crud
from backend.templating import user_display_name


def oldest_outstanding_check(checks: list, today: date) -> dict | None:
    """{"number", "days"} of the payment that has waited the longest, or None."""
    if not checks:
        return None
    oldest = min(checks, key=lambda check: check.issued_date)
    return {"number": oldest.check_number, "days": max((today - oldest.issued_date).days, 0)}


def search_examples(rule_keywords: list[str], user_names: list[str]) -> list[str]:
    """What to try in the settings search: a rule, a backup, a subscription, a person."""
    from backend.i18n import gettext as _t

    examples = []
    if rule_keywords:
        examples.append(rule_keywords[0].lower())
    examples += [_t("sauvegarde"), _t("abonnement")]
    if user_names:
        examples.append(user_names[0])
    return examples


def hub_context(db: Session, current_user, today: date | None = None) -> dict:
    today = today or date.today()
    outstanding = crud.get_outstanding_pending_checks(db)
    overview = crud.get_recurring_patterns_overview(db)
    active = [p for p in overview["recurring_patterns"] if p["status"] != "ignored"]
    expected = [p for p in active if p["activity_status"] == "active" and not p["seen_this_month"]]
    rules = crud.get_rules_with_usage(db)
    categories = crud.get_categories_tree(db)
    balances = crud.get_account_balances(db)
    suggestions = crud.count_pending_rule_suggestions(db)
    methods = crud.get_payment_methods_dict(db)
    logs = crud.list_import_logs(db, limit=1)
    users = crud.list_users(db)
    oldest = oldest_outstanding_check(outstanding, today)
    answer = answers.settings_answer(oldest, suggestions, len(balances), len(categories), len(rules))
    others = [user_display_name(u) for u in users if u.is_active and (current_user is None or u.id != current_user.id)]
    return {
        "answer": answer,
        "oldest_check": oldest,
        "tiles": {
            "payment_methods": {"count": len(methods), "labels": [m["label"] for m in methods.values()][:3]},
            "recurring": {
                "detected": len(active),
                "monthly_total": overview["recurring_monthly_total"],
                "expected": len(expected),
            },
            "checks": {
                "count": len(outstanding),
                "total": sum((abs(c.amount) for c in outstanding), Decimal("0")),
                "oldest_days": oldest["days"] if oldest else None,
            },
            "last_import": logs[0] if logs else None,
        },
        "search_examples": search_examples([r["rule"].keyword for r in rules], others),
        "rule_suggestions_count": suggestions,
        "show_login_accounts": crud.get_or_create_app_state(db).show_login_accounts,
    }
