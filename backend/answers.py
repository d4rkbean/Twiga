"""Twiga's sentence: the answer a screen of the other way opens with.

Each screen of "L'autre voie" starts with a sentence in the voice of the app
("Il reste 518 € à dépenser d'ici le 30.") that says what the screen has to say
before any figure does, and that changes when the reader acts (another period,
another account, one more envelope tightened).

Everything here is a pure function: figures in, text out. The routes compute
the figures with `crud` and pass them, the templates only print the result, and
the Classic interface ignores it. Texts go through gettext (`_t`, `ngettext`),
amounts through the same formatter as the `eur` filter, so the sentence reads
in the language and number format of the account.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from backend.formatting import format_amount
from backend.i18n import gettext as _t
from backend.i18n import ngettext

ZERO = Decimal("0.00")
NBSP = " "

# Thresholds of a budget gauge, shared with the Classic gauge (DESIGN.md, "The
# Traffic Light Rule"): from 75 % to watch, past 90 % almost used up, past
# 100 % exceeded. A verdict is always a colour AND a word.
WATCH_AT = 75
ALMOST_AT = 90
EXCEEDED_AT = 100


def whole(value: Decimal | int) -> str:
    """An amount rounded to the euro, for a headline ("518 €")."""
    return format_amount(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP)).replace(",00", "").replace(".00", "")


def percent(value: Decimal | float | int) -> str:
    """"87 %", with a no-break space so the sign never wraps alone."""
    return f"{round(value)}{NBSP}%"


@dataclass(frozen=True)
class Verdict:
    key: str  # ok | watch | almost | exceeded
    word: str
    tone: str  # success | warning | danger
    fill: str  # progress-green | progress-orange | progress-red
    text: str  # text-success | text-warning | text-danger (written out so Tailwind sees them)


def verdict(pct: Decimal | float | int | None) -> Verdict:
    """The verdict of a gauge at `pct` % : the word that always doubles the colour."""
    value = Decimal(str(pct or 0))
    if value > EXCEEDED_AT:
        return Verdict("exceeded", _t("Dépassé"), "danger", "progress-red", "text-danger")
    if value > ALMOST_AT:
        return Verdict("almost", _t("Presque épuisé"), "danger", "progress-red", "text-danger")
    if value >= WATCH_AT:
        return Verdict("watch", _t("À surveiller"), "warning", "progress-orange", "text-warning")
    return Verdict("ok", _t("Dans les clous"), "success", "progress-green", "text-success")


def count_phrase(n: int, singular: str, plural: str) -> str:
    return ngettext(singular, plural, n) % {"n": n}


def days_phrase(n: int) -> str:
    """"Aujourd'hui", "Demain", "Dans 4 jours"."""
    if n <= 0:
        return _t("Aujourd'hui")
    if n == 1:
        return _t("Demain")
    return ngettext("Dans %(n)s jour", "Dans %(n)s jours", n) % {"n": n}


# --- Panorama ---------------------------------------------------------------


@dataclass
class PanoramaAnswer:
    headline: str
    sub: str
    # Under the sentence: either the month and the envelopes advancing (current
    # month), or what was spent of what was received (any other period).
    bars: list[dict] = field(default_factory=list)
    bars_note: str = ""
    bars_tone: str = "success"


def panorama_answer(
    *,
    kind: str,  # "month" (the current budget month) | "last_month" | "other"
    month_name: str,
    lead: str,
    income: Decimal,
    expense: Decimal,
    envelopes_rest: Decimal | None,
    envelopes_count: int,
    envelopes_percent: Decimal,
    month_pace: int,
    pending_count: int,
    include_pending: bool,
    account_name: str | None,
    shift_on: bool,
    last_day: int,
    start_label: str,
    end_label: str,
) -> PanoramaAnswer:
    """The sentence under which the Panorama opens, for a period and an account."""
    result = income - expense
    who = ""
    if account_name:
        who = " " + _t("Compte : %(account)s seulement.") % {"account": account_name}

    if expense == 0 and income == 0:
        sub = _t("Aucune opération du %(start)s au %(end)s.") % {"start": start_label, "end": end_label}
        if account_name:
            sub = _t("Aucune opération du %(start)s au %(end)s sur %(account)s.") % {
                "start": start_label,
                "end": end_label,
                "account": account_name,
            }
        return PanoramaAnswer(_t("Rien sur cette période."), sub)

    if kind == "month":
        if envelopes_count and envelopes_rest is not None:
            if envelopes_rest >= 0:
                headline = _t("Il reste %(amount)s à dépenser d'ici le %(day)s.") % {
                    "amount": whole(envelopes_rest),
                    "day": last_day,
                }
            else:
                headline = _t("Tu as dépassé tes enveloppes de %(amount)s.") % {"amount": whole(-envelopes_rest)}
            sub = ngettext(
                "C'est ce qui reste dans l'enveloppe du mois",
                "C'est ce qui reste dans les %(n)s enveloppes du mois",
                envelopes_count,
            ) % {"n": envelopes_count}
            if pending_count == 0:
                sub += _t(", sans opération à ranger.")
            elif include_pending:
                sub += ngettext(
                    ", l'opération à ranger comprise.", ", les %(n)s opérations à ranger comprises.", pending_count
                ) % {"n": pending_count}
            else:
                sub += ngettext(
                    ", sans compter l'opération à ranger.", ", sans compter les %(n)s opérations à ranger.", pending_count
                ) % {"n": pending_count}
            if account_name:
                sub += " " + _t("Dépenses de %(account)s seulement.") % {"account": account_name}
            bars_note = verdict_sentence(envelopes_percent, month_pace)
            return PanoramaAnswer(
                headline,
                sub,
                bars=[
                    {"label": _t("Le mois"), "pct": month_pace, "kind": "pace"},
                    {"label": _t("Les enveloppes"), "pct": round(envelopes_percent), "kind": "envelopes"},
                ],
                bars_note=bars_note,
                bars_tone=_pace_tone(envelopes_percent, month_pace),
            )
        # A month with no envelope to count: say what the month did instead.
        headline = _t("%(lead)s tu as dépensé %(amount)s.") % {"lead": lead, "amount": whole(expense)}
        sub = _t("Aucune enveloppe n'est fixée pour ce mois : fixe-les dans Budgets pour voir ce qu'il reste à dépenser.")
        return PanoramaAnswer(headline, sub + who)

    if kind == "last_month":
        if result >= 0:
            headline = _t("En %(month)s, il t'est resté %(amount)s.") % {"month": month_name, "amount": whole(result)}
        else:
            headline = _t("En %(month)s, tu as dépensé %(amount)s de plus que reçu.") % {
                "month": month_name,
                "amount": whole(-result),
            }
        sub = _t("%(expense)s dépensés pour %(income)s reçus") % {"expense": whole(expense), "income": whole(income)}
        sub += (_t(", recettes décalées d'un mois") if shift_on else "") + "."
        return PanoramaAnswer(headline, sub + who, bars=_spent_bars(income, expense), bars_note=_spent_note(income, expense, shift_on))

    headline = _t("%(lead)s tu as dépensé %(amount)s.") % {"lead": lead, "amount": whole(expense)}
    if result >= 0:
        sub = _t("Pour %(income)s reçus : il t'en reste %(left)s.") % {"income": whole(income), "left": whole(result)}
    else:
        sub = _t("Pour %(income)s reçus : %(over)s de trop.") % {"income": whole(income), "over": whole(-result)}
    return PanoramaAnswer(headline, sub + who, bars=_spent_bars(income, expense), bars_note=_spent_note(income, expense, shift_on))


def _spent_bars(income: Decimal, expense: Decimal) -> list[dict]:
    if income <= 0:
        return []
    return [{"label": _t("Dépensé"), "pct": min(100, round(expense / income * 100)), "kind": "spent"}]


def _spent_note(income: Decimal, expense: Decimal, shift_on: bool) -> str:
    if income <= 0:
        return ""
    note = _t("Tu as dépensé %(percent)s de ce que tu as reçu") % {"percent": percent(expense / income * 100)}
    return note + (_t(" (recettes du mois d'avant).") if shift_on else ".")


def _pace_tone(envelopes_percent: Decimal, pace: int) -> str:
    if envelopes_percent <= pace:
        return "success"
    return "warning" if envelopes_percent <= 100 else "danger"


def verdict_sentence(envelopes_percent: Decimal, pace: int) -> str:
    """The line under the two bars: are the envelopes faster than the month?"""
    if envelopes_percent <= pace:
        return _t("Dans les clous : les enveloppes avancent moins vite que le mois.")
    if envelopes_percent <= 100:
        return _t("À surveiller : les enveloppes avancent plus vite que le mois.")
    return _t("Enveloppes dépassées : il faut en reprendre ailleurs.")


def panorama_things(
    *,
    pending_count: int,
    pending_total: Decimal,
    account_name: str | None,
    top_envelope: dict | None,  # {"name", "rest", "percent", "with_pending"}
    days_left: int,
    last_day: int,
    cap: dict,  # {"state": "open"|"upcoming"|"set", "title": "Le Cap d'octobre", "previous": "septembre"}
) -> list[dict]:
    """The three things worth a look, each with its reason and its one gesture.

    Every suggestion says why (a figure, a date) and offers the single action
    that answers it. At most one of the three is the amber action of the screen:
    sorting what waits in La Savane.
    """
    things: list[dict] = []

    if pending_count == 0:
        things.append(
            {
                "title": _t("Rien à ranger."),
                "text": _t("Aucune opération n'attend sa catégorie sur ce compte.")
                if account_name
                else _t("Aucune opération n'attend sa catégorie."),
                "when": _t("Aujourd'hui"),
                "cta": _t("Ouvrir La Savane"),
                "href": "/transactions/inbox",
                "primary": False,
            }
        )
    else:
        title = count_phrase(pending_count, "%(n)s opération à ranger.", "%(n)s opérations à ranger.")
        if account_name:
            text = ngettext(
                "%(n)s opération du compte %(account)s attend sa catégorie. Moins de 3 minutes pour la ranger.",
                "%(n)s opérations du compte %(account)s attendent leur catégorie. Moins de 3 minutes pour les ranger.",
                pending_count,
            ) % {"n": pending_count, "account": account_name}
        else:
            text = ngettext(
                "%(amount)s de dépenses attend sa catégorie. Moins de 3 minutes pour la ranger.",
                "%(amount)s de dépenses attendent leur catégorie. Moins de 3 minutes pour les ranger.",
                pending_count,
            ) % {"amount": format_amount(pending_total)}
        things.append(
            {
                "title": title,
                "text": text,
                "when": _t("Aujourd'hui"),
                "cta": _t("Ranger maintenant"),
                "href": "/transactions/inbox",
                "primary": True,
            }
        )

    when = _t("D'ici le %(day)s") % {"day": last_day}
    if top_envelope is None:
        things.append(
            {
                "title": _t("Aucune enveloppe ce mois-ci."),
                "text": _t("Fixe des budgets pour voir ce qu'il reste à dépenser."),
                "when": when,
                "cta": _t("Fixer les budgets"),
                "href": "/budgets",
                "primary": False,
            }
        )
    else:
        state = verdict(top_envelope["percent"])
        if state.key == "ok":
            things.append(
                {
                    "title": _t("Les enveloppes sont dans les clous."),
                    "text": _t("La plus avancée, %(name)s, est à %(percent)s %%.")
                    % {"name": top_envelope["name"], "percent": round(top_envelope["percent"])},
                    "when": when,
                    "cta": _t("Voir les enveloppes"),
                    "href": "#enveloppes",
                    "primary": False,
                    "pill": state,
                }
            )
        else:
            text = _t("L'enveloppe est à %(percent)s %%") % {"percent": round(top_envelope["percent"])}
            if top_envelope["with_pending"]:
                text += _t(" avec les opérations à ranger")
            text += ", " + ngettext(
                "à %(n)s jour de la fin du mois.", "à %(n)s jours de la fin du mois.", max(days_left, 0)
            ) % {"n": max(days_left, 0)}
            things.append(
                {
                    "title": _t("%(name)s : il reste %(rest)s.") % {"name": top_envelope["name"], "rest": format_amount(max(top_envelope["rest"], ZERO))},
                    "text": text,
                    "when": when,
                    "cta": _t("Voir les enveloppes"),
                    "href": "#enveloppes",
                    "primary": False,
                    "pill": state,
                }
            )

    if cap["state"] == "set":
        things.append(
            {
                "title": _t("%(cap)s est fixé.") % {"cap": cap["title"]},
                "text": _t("Suis-le au fil du mois, pilier par pilier."),
                "when": days_phrase(days_left),
                "cta": _t("Voir Mon mois"),
                "href": "/cap/mid",
                "primary": False,
            }
        )
    else:
        if cap["state"] == "upcoming":
            title = _t("%(cap)s arrive.") % {"cap": cap["title"]}
            text = _t("Fais le bilan de %(previous)s et fixe les enveloppes du mois prochain.") % {
                "previous": cap["previous"]
            }
            when_cap = days_phrase(days_left)
        else:
            title = _t("%(cap)s n'est pas fixé.") % {"cap": cap["title"]}
            text = _t("Fais le bilan de %(previous)s et fixe les enveloppes du mois.") % {"previous": cap["previous"]}
            when_cap = _t("Aujourd'hui")
        things.append(
            {
                "title": title,
                "text": text,
                "when": when_cap,
                "cta": _t("Préparer"),
                "href": "/cap",
                "primary": False,
            }
        )
    return things


# --- Mon mois ---------------------------------------------------------------


def month_answer(
    *,
    has_plan: bool,
    month_name: str,
    pillars: list[dict],  # tightest first: {"code", "percent", "verdict"}
    day: int,
    days: int,
    loose: tuple[str, Decimal] | None,  # (pillar name, amount waiting without a category)
    next_cap_title: str,
) -> tuple[str, str]:
    """The sentence of "Mon mois": which pillar asks for a look, and why."""
    if not has_plan:
        return (
            _t("Aucun cap n'est fixé pour %(month)s.") % {"month": month_name},
            _t("Fixe-le pour suivre tes trois piliers jour après jour."),
        )
    worst = pillars[0]
    day_line = _t("Jour %(day)s sur %(days)s.") % {"day": day, "days": days}
    if worst["verdict"] != "ok":
        figure = {"percent": percent(worst["percent"])}
        if worst["code"] == "imprevu":
            headline = _t("Les imprévus demandent un regard : %(percent)s de leur réserve, rangement compris.") % figure
        elif worst["code"] == "essentiel":
            headline = _t("L'Essentiel demande un regard : %(percent)s de son budget, rangement compris.") % figure
        else:
            headline = _t("Choix demande un regard : %(percent)s de son budget, rangement compris.") % figure
        parts = [day_line]
        for other in pillars[1:]:
            figure = {"percent": percent(other["percent"])}
            if other["code"] == "imprevu":
                sentence = _t("Les imprévus sont à %(percent)s de leur réserve") % figure
            elif other["code"] == "essentiel":
                sentence = _t("L'Essentiel est à %(percent)s de son budget") % figure
            else:
                sentence = _t("Choix est à %(percent)s de son budget") % figure
            parts.append(sentence + (_t(" : dans les clous.") if other["verdict"] == "ok" else "."))
        if loose is not None and loose[1] > 0:
            parts.append(
                _t("Dans %(pillar)s, %(amount)s attendent encore une catégorie.")
                % {"pillar": loose[0], "amount": format_amount(loose[1])}
            )
        return headline, " ".join(parts)
    return (
        _t("Le cap tient : les trois piliers sont dans les clous."),
        day_line + " " + _t("Tu peux préparer %(cap)s l'esprit tranquille.") % {"cap": next_cap_title},
    )


# --- Le Cap ------------------------------------------------------------------


def cap_review_answers(
    *,
    month_name: str,  # the month under review, capitalised ("Septembre")
    next_month_name: str,  # the month being planned, lowercase ("octobre")
    has_plan: bool,
    result: Decimal,  # income - expenses of the reviewed month
    pillars: list[dict],  # {"name", "planned", "real", "ratio", "unbudgeted"}
) -> dict:
    """The sentences of the review (Bilan, Un mot): one per group of the desktop
    frise and one per step of the mobile flow, with the line that says why."""
    held = [p for p in pillars if p["planned"] and p["real"] <= p["planned"]]
    tightest = max(pillars, key=lambda p: p["ratio"] or 0) if pillars else None
    signed_result = ("+" if result > 0 else "") + format_amount(result)
    if has_plan and len(held) == len(pillars):
        bilan = _t("%(month)s s'est bien tenu : %(result)s de reste.") % {"month": month_name, "result": signed_result}
        detail = _t("Les trois piliers sont sous leur prévu.")
    elif has_plan:
        over = next(p for p in pillars if p["planned"] and p["real"] > p["planned"])
        bilan = _t("%(month)s a débordé : %(pillar)s a dépassé son prévu.") % {"month": month_name, "pillar": over["name"]}
        detail = _t("%(pillar)s : %(real)s sur %(planned)s prévus.") % {
            "pillar": over["name"],
            "real": format_amount(over["real"]),
            "planned": format_amount(over["planned"]),
        }
    else:
        bilan = _t("%(month)s : %(result)s de reste.") % {"month": month_name, "result": signed_result}
        detail = _t("Aucun cap n'était fixé : voici ce que le mois a donné.")
    short_detail = detail
    if has_plan and tightest and tightest["ratio"] and tightest["ratio"] >= WATCH_AT and tightest["planned"]:
        near = _t("%(pillar)s a frôlé son plafond : %(real)s sur %(planned)s") % {
            "pillar": tightest["name"],
            "real": format_amount(tightest["real"]),
            "planned": format_amount(tightest["planned"]),
        }
        if tightest["unbudgeted"] > 0:
            near += ", " + _t("dont %(amount)s encore sans catégorie") % {"amount": format_amount(tightest["unbudgeted"])}
        detail += " " + near + "."
        short_detail += " " + _t("%(pillar)s a frôlé son plafond.") % {"pillar": tightest["name"]}
    word = _t("Un mot sur %(month)s, pour garder le fil.") % {"month": month_name.lower()}
    word_detail = _t("Quatre questions, toutes facultatives. Tes réponses sont enregistrées avec le cap de %(month)s.") % {
        "month": next_month_name
    }
    step_word = _t("Un mot sur %(month)s.") % {"month": month_name.lower()}
    return {
        # the desktop frise: Bilan, Un mot
        "group": [bilan, word],
        "groupDetail": [detail, word_detail],
        # the mobile flow: Bilan, then the four questions
        "step": [bilan, step_word, step_word, step_word, step_word],
        "stepDetail": [short_detail]
        + [_t("Question %(n)s sur 4. Facultatif : tu peux passer.") % {"n": n} for n in (1, 2, 3, 4)],
    }


# --- Budgets -----------------------------------------------------------------


def budgets_answer(*, available: Decimal, total: Decimal, month_label: str) -> tuple[str, str]:
    """"Il reste 1 965,60 € à répartir." and the line under it."""
    left = available - total
    if available <= 0:
        return (
            _t("Il n'y a pas encore de ressources à répartir."),
            _t("%(total)s budgétés pour %(month)s. Fixe les ressources dans Le Cap, ou répartis librement.")
            % {"total": format_amount(total), "month": month_label},
        )
    if left > 0:
        headline = _t("Il reste %(amount)s à répartir.") % {"amount": format_amount(left)}
    elif left == 0:
        headline = _t("Tout est réparti.")
    else:
        headline = _t("Tu répartis %(amount)s de plus que tes ressources.") % {"amount": format_amount(-left)}
    sub = _t("%(total)s budgétés sur %(available)s disponibles.") % {
        "total": format_amount(total),
        "available": format_amount(available),
    }
    return headline, sub
