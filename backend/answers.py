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
from backend.formatting import format_amount, format_integer
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


# --- Import -----------------------------------------------------------------


def csv_delimiter_label(delimiter: str) -> str:
    """"points-virgules", "virgules"...: how a CSV separator is named in a sentence."""
    names = {
        ";": _t("points-virgules"),
        ",": _t("virgules"),
        "\t": _t("tabulations"),
        "|": _t("barres verticales"),
    }
    return names.get(delimiter, delimiter)


def import_idle_answer(has_accounts: bool) -> dict:
    """The drop screen: one file is enough, and the very first import is a HomeBank history."""
    if not has_accounts:
        return {
            "phrase": _t("Aucun compte pour l'instant : commence par un historique HomeBank."),
            "detail": _t(
                "Importe d'abord un fichier QIF : il crée tes comptes et tes catégories. "
                "Les CSV et OFX suivants viendront alimenter un compte existant."
            ),
        }
    return {
        "phrase": _t("Un fichier suffit, Twiga reconnaît le reste."),
        "detail": _t(
            "Dépose un relevé CSV, OFX ou QIF. Le format et le compte sont repérés seuls, rien ne quitte ton serveur."
        ),
    }


def import_recap_answer(
    fmt: str, account_name: str, to_import: int, duplicates: int, delimiter: str | None = None
) -> dict:
    """The sentence of a statement that was read and waits for a confirmation."""
    if to_import == 0:
        phrase = _t("Rien de nouveau : tout ce relevé est déjà en base.")
    else:
        phrase = ngettext(
            "%(account)s : %(n)s opération à importer.",
            "%(account)s : %(n)s opérations à importer.",
            to_import,
        ) % {"account": account_name, "n": format_integer(to_import)}
    if fmt == "csv":
        kind = _t("Format reconnu : CSV séparé par des %(delimiter)s.") % {
            "delimiter": csv_delimiter_label(delimiter or ";")
        }
    else:
        kind = _t("Format reconnu : OFX.")
    if duplicates:
        tail = ngettext(
            "Le doublon est déjà écarté, il ne reste qu'à confirmer.",
            "Les %(n)s doublons sont déjà écartés, il ne reste qu'à confirmer.",
            duplicates,
        ) % {"n": duplicates}
    else:
        tail = _t("Aucun doublon : il ne reste qu'à confirmer.")
    return {"phrase": phrase, "detail": f"{kind} {tail}"}


def import_qif_answer(
    accounts: int, categories: int, transactions: int, duplicates: int, new_accounts: int
) -> dict:
    """The sentence of a HomeBank history (QIF) that creates accounts and categories."""
    phrase = _t(
        "Un historique HomeBank : %(accounts)s comptes, %(categories)s catégories, %(transactions)s opérations."
    ) % {
        "accounts": format_integer(accounts),
        "categories": format_integer(categories),
        "transactions": format_integer(transactions),
    }
    parts = [_t("Format reconnu : QIF (HomeBank).")]
    if new_accounts:
        parts.append(_t("Twiga crée les comptes et les catégories qui manquent, et garde la hiérarchie."))
    if duplicates:
        parts.append(
            ngettext("%(n)s doublon est déjà écarté.", "%(n)s doublons sont déjà écartés.", duplicates)
            % {"n": format_integer(duplicates)}
        )
    return {"phrase": phrase, "detail": " ".join(parts)}


def minutes_to_sort(count: int) -> int:
    """How long the operations that wait in La Savane take: thirty in three minutes, at least one."""
    return max(1, -(-count // 10))


def import_result_detail(imported: int, duplicates: int, with_rule: int, to_sort: int) -> str:
    """The sentence under "Twiga a tout avalé !"."""
    sentence = ngettext(
        "%(n)s opération importée", "%(n)s opérations importées", imported
    ) % {"n": format_integer(imported)}
    if duplicates:
        sentence += ", " + ngettext(
            "%(n)s doublon écarté", "%(n)s doublons écartés", duplicates
        ) % {"n": format_integer(duplicates)}
    sentence += "."
    if to_sort <= 0:
        return sentence + " " + _t("Il n'y a rien à ranger : tout est en ordre.")
    if with_rule and with_rule < to_sort:
        remaining = to_sort - with_rule
        return " ".join(
            [
                sentence,
                ngettext(
                    "%(n)s a une règle de rangement,",
                    "%(n)s ont une règle de rangement,",
                    with_rule,
                )
                % {"n": format_integer(with_rule)},
                ngettext(
                    "l'autre t'attend dans La Savane : environ %(m)s minute.",
                    "les %(n)s autres t'attendent dans La Savane : environ %(m)s minutes.",
                    remaining,
                )
                % {"n": format_integer(remaining), "m": minutes_to_sort(to_sort)},
            ]
        )
    return sentence + " " + ngettext(
        "Elle t'attend dans La Savane : environ %(m)s minute.",
        "Elles t'attendent dans La Savane : environ %(m)s minutes.",
        to_sort,
    ) % {"m": minutes_to_sort(to_sort)}
