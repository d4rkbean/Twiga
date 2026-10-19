"""The sentence of Twiga at the top of each screen of the other way.

The answer comes first: one short sentence that says what the screen is about
and changes when the user acts. These functions are pure (they take numbers
and names, never a session or a request), so they are tested without a
database; the routes compute the figures and pass them in. They return the
sentence already translated, in the language of the current request.

Amounts arrive formatted (the route applies `format_amount`), because a
sentence is text, not a figure; the template blurs it with the privacy mode.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from backend.dates import month_names
from backend.formatting import format_amount
from backend.i18n import current_language, gettext as _t, ngettext


def month_in_sentence(value: date) -> str:
    """The name of the month in the middle of a sentence: "octobre" / "October"."""
    name = month_names()[value.month - 1]
    return name.lower() if current_language() == "fr" else name


def month_year_in_sentence(value: date) -> str:
    return f"{month_in_sentence(value)} {value.year}"


def cap_of_month(value: date) -> str:
    """"Le Cap d'octobre", "Le Cap de novembre": the French elision is decided here."""
    name = month_in_sentence(value)
    if current_language() == "fr" and name[0] in "aeiouyéèêâôû":
        return _t("Le Cap d'%(month)s") % {"month": name}
    return _t("Le Cap de %(month)s") % {"month": name}


# --- Projets --------------------------------------------------------------


def project_clause(name: str, state: str, gap_months: int) -> str:
    """How one project stands against its deadline, as a half sentence."""
    if state == "done":
        return _t("%(name)s est atteint") % {"name": name}
    if state == "none":
        return _t("%(name)s n'avance pas encore") % {"name": name}
    if state == "late":
        return _t("%(name)s a %(n)s mois de retard") % {"name": name, "n": gap_months}
    if state == "early":
        return _t("%(name)s arrive en avance") % {"name": name}
    return _t("%(name)s arrive à l'heure") % {"name": name}


def projects_answer(projects: list[dict], today: date) -> dict:
    """The sentence of the Projets screen.

    Each project is {"name", "state", "gap_months", "monthly_effort", "effort"}
    (state as in crud.project_rhythm). Returns {"phrase", "detail", "late"}:
    `late` is the name of the project that is the furthest behind, or None.
    """
    if not projects:
        return {
            "phrase": _t("Pas encore de projet."),
            "detail": _t("Mets de l'argent de côté pour un but précis, avec une date : Twiga te dit quand tu y arrives."),
            "late": None,
        }
    late = [p for p in projects if p["state"] == "late"]
    worst = max(late, key=lambda p: p["gap_months"]) if late else None
    if len(projects) == 1 and not late:
        only = projects[0]
        phrase = project_clause(only["name"], only["state"], only["gap_months"]) + "."
    elif len(projects) <= 3:
        ordered = sorted(projects, key=lambda p: p["gap_months"])
        phrase = ", ".join(project_clause(p["name"], p["state"], p["gap_months"]) for p in ordered)
        phrase = phrase[0].upper() + phrase[1:] + "."
    elif late:
        phrase = ngettext(
            "%(n)s projet sur %(total)s a du retard.", "%(n)s projets sur %(total)s ont du retard.", len(late)
        ) % {"n": len(late), "total": len(projects)}
    else:
        phrase = _t("Tous tes projets tiennent leur date.")

    if worst is not None:
        detail = _t(
            "%(name)s tiendrait sa date avec %(need)s par mois au lieu de %(now)s. %(cap)s est le bon moment pour l'ajuster."
        ) % {
            "name": worst["name"],
            "need": format_amount(worst["monthly_effort"]),
            "now": format_amount(worst["effort"]),
            "cap": cap_of_month(today),
        }
    elif all(p["state"] == "done" for p in projects):
        detail = _t("Tout est mis de côté : tu peux dépenser depuis le projet.")
    else:
        detail = _t("Au rythme actuel, chaque projet arrive à sa date, ou avant.")
    return {"phrase": phrase, "detail": detail, "late": worst["name"] if worst else None}


def project_verdict(state: str, gap_months: int) -> tuple[str, str]:
    """(tone, word): the verdict of a project, always a word next to its colour."""
    if state == "done":
        return "success", _t("Objectif atteint")
    if state == "none":
        return "neutral", _t("Aucun versement régulier")
    if state == "late":
        return "warning", _t("À surveiller : %(n)s mois de retard") % {"n": gap_months}
    if state == "early":
        return "success", _t("En avance de %(n)s mois") % {"n": abs(gap_months)}
    return "success", _t("À l'heure")


def project_need_sentence(state: str, monthly_effort: Decimal, effort: Decimal) -> tuple[str, str]:
    """(tone, sentence) under the "to hold the deadline" figure."""
    if state == "done":
        return "success", _t("Rien à ajouter.")
    if effort <= 0:
        return "warning", _t("Tu ne mets rien de côté en ce moment.")
    if effort >= monthly_effort:
        return "success", _t("Tu mets %(effort)s : c'est assez.") % {"effort": format_amount(effort)}
    return "warning", _t("Tu mets %(effort)s : il manque %(gap)s par mois.") % {
        "effort": format_amount(effort),
        "gap": format_amount(monthly_effort - effort),
    }
