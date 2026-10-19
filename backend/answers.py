"""Twiga's sentence: the answer a screen of the other way opens with.

Each screen of "L'autre voie" starts with a sentence in the voice of the app
("Il reste 518 € à dépenser d'ici le 30.") that says what the screen has to say
before any figure does, and that changes when the reader acts (another period,
another account, one more envelope tightened).

Everything here is a pure function: figures in, text out, nothing read from the
database or the request. The routes compute the figures and pass them, the
templates only print the result, and the Classic interface ignores it. Texts go
through gettext (French source, English catalog).

Two styles live side by side, one per group of screens:
- La Savane, mass processing, Operations and the settings, import, profile and
  sign-in screens return an `Answer` (a title, a detail, optionally an `action`
  and a `focus`) whose amounts are already wrapped in `.amount-blur` (Markup),
  so privacy mode hides them in the headline too;
- Panorama, Mon mois, Budgets, Le Cap and Rapports return plain text (their
  templates put the whole sentence in an `.amount-blur` element) and share the
  verdict words of the gauges (`verdict`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from markupsafe import Markup, escape

from backend.dates import month_names
from backend.formatting import format_amount, format_integer
from backend.i18n import current_language
from backend.i18n import gettext as _t
from backend.i18n import lazy_gettext, ngettext

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


# --- Rapports ----------------------------------------------------------------

REPORT_QUESTIONS = [
    # (id, the question as the reader asks it)
    ("dep", lazy_gettext("Où est parti l'argent ?")),
    ("rec", lazy_gettext("D'où vient l'argent ?")),
    ("bal", lazy_gettext("Est-ce que le foyer épargne ?")),
    ("bud", lazy_gettext("Les budgets ont-ils tenu ?")),
    ("pat", lazy_gettext("Que vaut le foyer ?")),
    ("cap", lazy_gettext("Le cap a-t-il tenu ?")),
    ("shop", lazy_gettext("Que coûtent les courses ?")),
    ("chg", lazy_gettext("Qu'est-ce qui a changé ?")),
    ("score", lazy_gettext("Comment je me débrouille ?")),
]
REPORT_QUESTION_IDS = [key for key, _ in REPORT_QUESTIONS]


def report_answers(
    *,
    has_data: bool,
    des: str,  # "de septembre 2026", "du T3 2026", "de l'année 2026", "de la période"
    plab: str,  # "septembre 2026", "le T3 2026", "l'année 2026", "la période"
    period_start_label: str,
    in_period: str,  # "en septembre 2026" or "sur le T3 2026"
    expense_total: Decimal,
    expense_rows: list[dict],  # {"name", "amount", "percent"}
    pending_expense: Decimal,
    income_total: Decimal,
    income_rows: list[dict],
    shifted_income_label: str | None,  # the month whose income is counted, when the shift is on
    result: Decimal,
    twelve: dict,  # {"result", "income", "avg"}: the last twelve months
    budgets: dict,  # {"has", "held", "count", "spent", "budget", "saved"}
    patrimoine: dict,  # {"ok", "last", "delta", "high", "low", "account"}
    cap: dict,  # {"ok", "month", "all_ok", "worst", "quote", "rate"}
    shop: dict,  # {"empty", "total", "top"}
    change: dict,  # {"ref", "dep_delta", "rec_delta", "prev_label", "unfinished", "pending", "cur_label"}
    score: dict,  # {"score", "message"}
) -> dict[str, tuple[str, str]]:
    """The nine answers of the reports screen, as (sentence, line that says why).

    One per question: the sentence is what the reader asked for, in one line, the
    line under it is what makes it trustworthy (a share, a period, a caveat).
    Computed together so the screen can switch question without a round trip.
    """
    nothing = (
        _t("Twiga ne trouve rien sur cette période."),
        _t("Essaie une autre période, ou importe des opérations depuis Paramètres."),
    )
    answers: dict[str, tuple[str, str]] = {}

    # Où est parti l'argent ?
    if not has_data:
        answers["dep"] = nothing
    elif not expense_rows:
        answers["dep"] = (_t("Aucune dépense sur cette période."), _t("Essaie une autre période ou un autre compte."))
    else:
        top = expense_rows[0]
        sub = _t("C'est %(percent)s des dépenses %(des)s.") % {"percent": percent(top["percent"]), "des": des}
        if pending_expense > 0:
            sub += " " + _t("%(amount)s restent à trier : la répartition sera plus fine une fois La Savane vidée.") % {
                "amount": format_amount(pending_expense)
            }
        answers["dep"] = (
            _t("Surtout dans %(name)s : %(amount)s sur %(total)s.")
            % {"name": top["name"], "amount": whole_or_cents(top["amount"]), "total": whole_or_cents(expense_total)},
            sub,
        )

    # D'où vient l'argent ?
    if not has_data:
        answers["rec"] = nothing
    elif not income_rows:
        answers["rec"] = (_t("Aucune recette sur cette période."), _t("Essaie une autre période ou un autre compte."))
    else:
        top = income_rows[0]
        if top["percent"] >= 50:
            head = _t("%(name)s fait l'essentiel : %(amount)s sur %(total)s.")
        else:
            head = _t("Surtout %(name)s : %(amount)s sur %(total)s.")
        head = head % {"name": top["name"], "amount": whole_or_cents(top["amount"]), "total": whole_or_cents(income_total)}
        if shifted_income_label:
            sub = _t("Ce sont les recettes de %(month)s, décalées sur la période.") % {"month": shifted_income_label}
        elif len(income_rows) > 1:
            sub = _t("%(name)s ajoute %(amount)s.") % {
                "name": income_rows[1]["name"],
                "amount": whole_or_cents(income_rows[1]["amount"]),
            }
        else:
            sub = _t("Rien d'autre n'est entré %(in_period)s.") % {"in_period": in_period}
        answers["rec"] = (head, sub)

    # Est-ce que le foyer épargne ?
    if not has_data:
        answers["bal"] = nothing
    else:
        if result >= 0:
            head = _t("Oui : %(amount)s mis de côté %(in_period)s.") % {"amount": whole_or_cents(result), "in_period": in_period}
        else:
            head = _t("Pas cette fois : %(amount)s dépensés de plus que reçus %(in_period)s.") % {
                "amount": whole_or_cents(-result),
                "in_period": in_period,
            }
        if twelve["income"] > 0:
            sub = _t("Sur les 12 derniers mois : %(amount)s mis de côté, soit %(rate)s des recettes et %(avg)s par mois en moyenne.") % {
                "amount": whole_or_cents(twelve["result"]),
                "rate": percent(twelve["result"] / twelve["income"] * 100),
                "avg": whole_or_cents(twelve["avg"]),
            }
        else:
            sub = _t("Pas de recette sur les 12 derniers mois pour en tirer un taux.")
        answers["bal"] = (head, sub)

    # Les budgets ont-ils tenu ?
    if not has_data:
        answers["bud"] = nothing
    elif not budgets["has"]:
        answers["bud"] = (_t("Aucun budget défini pour cette période."), _t("Fixe-les dans Budgets pour suivre ce qu'ils deviennent."))
    elif budgets["held"] == budgets["count"]:
        answers["bud"] = (
            _t("Oui, les %(n)s budgets ont tenu.") % {"n": budgets["count"]}
            if budgets["count"] > 1
            else _t("Oui, le budget a tenu."),
            _t("%(spent)s dépensés sur %(budget)s %(des)s : %(saved)s économisés.")
            % {
                "spent": whole_or_cents(budgets["spent"]),
                "budget": whole_or_cents(budgets["budget"]),
                "des": des,
                "saved": whole_or_cents(budgets["saved"]),
            },
        )
    else:
        answers["bud"] = (
            ngettext("%(held)s budget sur %(count)s a tenu.", "%(held)s budgets sur %(count)s ont tenu.", budgets["held"])
            % {"held": budgets["held"], "count": budgets["count"]},
            _t("%(spent)s dépensés sur %(budget)s %(des)s ; les budgets en orange ou en rouge sont à regarder en premier.")
            % {"spent": whole_or_cents(budgets["spent"]), "budget": whole_or_cents(budgets["budget"]), "des": des},
        )

    # Que vaut le foyer ?
    if not has_data or not patrimoine["ok"]:
        answers["pat"] = (
            _t("Pas assez de données pour tracer le patrimoine."),
            _t("Pas assez de données pour tracer le patrimoine sur cette période."),
        )
    else:
        delta = patrimoine["delta"]
        rise = (_t("%(amount)s de plus depuis %(since)s") if delta >= 0 else _t("%(amount)s de moins depuis %(since)s")) % {
            "amount": whole_or_cents(abs(delta)),
            "since": period_start_label,
        }
        answers["pat"] = (
            _t("Le foyer vaut %(last)s, %(rise)s.") % {"last": whole_or_cents(patrimoine["last"]), "rise": rise},
            _t("Plus haut %(high)s, plus bas %(low)s sur la période.") % {
                "high": whole_or_cents(patrimoine["high"]),
                "low": whole_or_cents(patrimoine["low"]),
            }
            + " "
            + (_t("%(account)s seulement.") % {"account": patrimoine["account"]} if patrimoine["account"] else _t("Tous comptes confondus.")),
        )

    # Le cap a-t-il tenu ?
    if not has_data:
        answers["cap"] = nothing
    elif not cap["ok"]:
        answers["cap"] = (
            _t("Aucun cap fixé pour %(month)s.") % {"month": cap["month"]},
            _t("Tu peux en fixer un pour le mois en cours."),
        )
    else:
        quote = ("« %s » " % cap["quote"]) if cap["quote"] else ""
        rate = _t("Taux d'épargne %(des)s : %(rate)s.") % {"des": des, "rate": percent(cap["rate"])}
        if cap["all_ok"]:
            answers["cap"] = (_t("Oui, le cap de %(month)s tient.") % {"month": cap["month"]}, quote + rate)
        else:
            answers["cap"] = (
                _t("Le cap a bougé : le pilier %(pillar)s a dépassé son plan.") % {"pillar": cap["worst"]},
                quote + rate,
            )

    # Que coûtent les courses ?
    if shop["empty"]:
        answers["shop"] = (
            _t("Je n'ai aucun ticket détaillé pour l'instant."),
            _t("Importe la facture PDF d'une course depuis le détail de l'opération, Twiga la range rayon par rayon."),
        )
    else:
        answers["shop"] = (
            _t("Les courses : %(total)s en 12 mois, surtout en %(top)s.") % {"total": whole_or_cents(shop["total"]), "top": shop["top"]},
            _t("Basé sur les courses dont le ticket a été importé. Montants avant remises, bons d'achat et titres-restaurant : ce rapport mesure ce qui est acheté, pas ce qui est payé."),
        )

    # Qu'est-ce qui a changé ?
    if not has_data:
        answers["chg"] = nothing
    elif not change["ref"]:
        answers["chg"] = (
            _t("Je n'ai pas de référence avant %(plab)s.") % {"plab": plab},
            _t("Pas de référence sur la période précédente : la comparaison démarre à la prochaine période."),
        )
    else:
        dd = change["dep_delta"]
        head = (
            _t("Les dépenses ont baissé de %(amount)s par rapport à %(prev)s.")
            if dd < 0
            else _t("Les dépenses ont augmenté de %(amount)s par rapport à %(prev)s.")
        ) % {"amount": whole_or_cents(abs(dd)), "prev": change["prev_label"]}
        dr = change["rec_delta"]
        if abs(dr) < 1:
            sub = _t("Les recettes sont stables (%(delta)s).") % {"delta": format_amount(dr)}
        elif dr > 0:
            sub = _t("Les recettes montent de %(amount)s.") % {"amount": whole_or_cents(dr)}
        else:
            sub = _t("Les recettes baissent de %(amount)s.") % {"amount": whole_or_cents(-dr)}
        if change["unfinished"]:
            sub += " " + _t("%(period)s n'est pas terminé et %(pending)s restent à trier : l'écart peut encore se réduire.") % {
                "period": change["cur_label"],
                "pending": whole_or_cents(change["pending"]),
            }
        answers["chg"] = (head, sub)

    # Comment je me débrouille ?
    answers["score"] = (_t("Tu en es à %(score)s sur 100.") % {"score": score["score"]}, score["message"])
    return answers


def whole_or_cents(value: Decimal) -> str:
    """A round amount without cents ("1 055 €"), any other with them ("1 055,19 €")."""
    quantized = Decimal(value).quantize(Decimal("0.01"))
    if quantized == quantized.to_integral_value():
        return whole(quantized)
    return format_amount(quantized)


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


@dataclass(frozen=True)
class Answer:
    """A headline and the line under it. Both may carry blurred amounts (Markup)."""

    title: str
    detail: str
    # Optional, for screens whose sentence points at something: the main action
    # ("/checks", "Voir les paiements en attente") and the thing it is about.
    action: tuple[str, str] | None = None
    focus: str | None = None


def blurred(amount: str) -> Markup:
    """An amount, formatted, as the privacy mode expects it."""
    return Markup('<span class="amount-blur">{}</span>').format(amount)


def _fill(template: str, **values) -> Markup:
    """A translated sentence with values: the sentence is trusted, the values are escaped.

    Values that are already Markup (a blurred amount) stay as they are.
    """
    return Markup(escape(template)) % {key: escape(value) for key, value in values.items()}


# --- La Savane --------------------------------------------------------------


def savane_answer(*, lot: int, questions: int, filed: int) -> Answer:
    """The headline of La Savane: what Twiga recognizes, what it asks, or that it is done.

    `lot` is the number of operations recognized for sure, `questions` the
    number of the others, `filed` how many this visit has filed so far.
    """
    total = lot + questions
    if lot > 0:
        if questions == 0:
            title = (
                _t("Je les reconnais toutes : %(total)s. Un coup d'œil ?") % {"total": total}
                if total > 1
                else _t("Je reconnais celle-ci. Un coup d'œil ?")
            )
            detail = _t("Rien d'autre à décider : tout se range d'un geste.")
        else:
            title = _t("J'en reconnais %(lot)s sur %(total)s. Un coup d'œil ?") % {"lot": lot, "total": total}
            detail = ngettext(
                "L'autre, on la décide ensemble juste après.",
                "Les %(n)s autres, on les décide ensemble, une à la fois.",
                questions,
            ) % {"n": questions}
        return Answer(title, detail)
    if questions > 0:
        title = ngettext("Il reste %(n)s question.", "Il reste %(n)s questions.", questions) % {"n": questions}
        detail = _t("Une à la fois : « Oui » si ma proposition te va, sinon choisis une autre catégorie.")
        return Answer(title, detail)
    if filed > 0:
        title = _t("Tout est rangé.")
        detail = ngettext(
            "%(n)s opération rangée pendant cette séance.",
            "%(n)s opérations rangées pendant cette séance.",
            filed,
        ) % {"n": filed}
        return Answer(title, detail)
    return Answer(_t("Rien à ranger."), _t("La savane est propre."))


def next_text(*, lot: int, questions: int) -> str:
    """"Ensuite" in the panel of the visit: what comes after the current step."""
    if lot > 0:
        if questions > 0:
            return ngettext(
                "Après le lot, %(n)s question, puis le bilan du mois.",
                "Après le lot, %(n)s questions, puis le bilan du mois.",
                questions,
            ) % {"n": questions}
        return _t("Après le lot, le bilan du mois.")
    if questions > 1:
        return ngettext(
            "Après celle-ci, %(n)s autre, puis le bilan du mois.",
            "Après celle-ci, %(n)s autres, puis le bilan du mois.",
            questions - 1,
        ) % {"n": questions - 1}
    if questions == 1:
        return _t("Après celle-ci, le bilan du mois.")
    return _t("Le bilan du mois s'ouvre quand tout est rangé.")


def suggestion_reason(
    *,
    in_category: int,
    total: int,
    rule_keyword: str | None = None,
    based_on_label: str | None = None,
    confidence: int | None = None,
) -> str:
    """Why Twiga proposes a category, in one short sentence.

    Order of what is worth saying: a rule of the user, then how often this very
    merchant was filed there, then the look-alike it was guessed from.
    """
    if rule_keyword:
        return _t("Ta règle « %(keyword)s » le range là.") % {"keyword": rule_keyword}
    if total > 0 and in_category > 0:
        return ngettext(
            "Déjà rangée là %(n)s fois sur %(total)s.",
            "Déjà rangée là %(n)s fois sur %(total)s.",
            total,
        ) % {"n": in_category, "total": total}
    if based_on_label:
        if confidence is not None:
            return _t("Ressemble à « %(label)s » (%(confidence)s %%).") % {
                "label": based_on_label,
                "confidence": confidence,
            }
        return _t("Ressemble à « %(label)s ».") % {"label": based_on_label}
    return _t("Je n'ai pas de piste : choisis une catégorie.")


# --- Traitement en masse ----------------------------------------------------


def masse_answer(
    *,
    count: int,
    categories: int,
    amount: str,
    min_confidence: int | None,
    pending: int,
    searching: bool = False,
) -> Answer:
    """The headline of the bulk screen: how much of the lot is sure, in how many categories.

    `count`, `categories`, `amount` and `min_confidence` describe the sure
    operations in view; `pending` is the whole waiting queue.
    """
    if count > 0:
        title = ngettext(
            "Le lot tient en %(n)s catégorie.",
            "Le lot tient en %(n)s catégories.",
            categories,
        ) % {"n": categories}
        detail = ngettext(
            "%(count)s opération, %(amount)s, reconnue à %(min)s %% et plus.",
            "%(count)s opérations, %(amount)s, toutes reconnues à %(min)s %% et plus.",
            count,
        )
        return Answer(title, _fill(detail, count=count, amount=blurred(amount), min=min_confidence))
    if searching:
        return Answer(_t("Rien de sûr ne correspond."), _t("Essaie un autre mot, ou retire un filtre."))
    if pending > 0:
        return Answer(
            _t("Rien de sûr à ranger en masse."),
            ngettext(
                "%(n)s opération attend une question dans La Savane.",
                "%(n)s opérations attendent une question dans La Savane.",
                pending,
            )
            % {"n": pending},
        )
    return Answer(_t("Tout est rangé."), _t("Rien ne reste à traiter."))


# --- Opérations -------------------------------------------------------------


def operations_answer(
    *,
    total: int,
    net: str,
    todo: int,
    period: str,
    search: str = "",
    selected: int = 0,
    selected_sum: str = "",
) -> Answer:
    """The headline of the operations list: the selection, the search, what waits, or the month.

    `total` is the number of operations in view, `net` their formatted sum,
    `todo` how many of them still wait for a category, `period` the label of
    the dates in view ("Septembre 2026").
    """
    if selected > 0:
        title = _fill(
            ngettext("%(n)s opération choisie, %(sum)s.", "%(n)s opérations choisies, %(sum)s.", selected),
            n=selected,
            sum=blurred(selected_sum),
        )
        return Answer(title, _t("Choisis une catégorie pour les ranger d'un coup, ou un autre geste."))
    if search.strip():
        if total == 0:
            return Answer(
                _t("Rien ne correspond à « %(search)s ».") % {"search": search.strip()},
                _t("Essaie un autre mot, ou retire un filtre."),
            )
        title = ngettext(
            "%(n)s opération pour « %(search)s ».",
            "%(n)s opérations pour « %(search)s ».",
            total,
        ) % {"n": total, "search": search.strip()}
        return Answer(title, _fill(_t("Net : %(net)s. Touche une ligne pour l'ouvrir."), net=blurred(net)))
    if todo > 0:
        title = ngettext(
            "%(n)s opération attend encore une catégorie.",
            "%(n)s opérations attendent encore une catégorie.",
            todo,
        ) % {"n": todo}
        detail = ngettext(
            "%(period)s : %(count)s opération, %(net)s sur la période. Cherche un commerce, ou filtre d'un geste.",
            "%(period)s : %(count)s opérations, %(net)s sur la période. Cherche un commerce, ou filtre d'un geste.",
            total,
        )
        return Answer(title, _fill(detail, period=period, count=total, net=blurred(net)))
    if total == 0:
        return Answer(_t("Aucune opération ici."), _t("Cherche un commerce, ou change de période."))
    title = ngettext("%(n)s opération, tout est rangé.", "%(n)s opérations, tout est rangé.", total) % {"n": total}
    return Answer(
        title,
        _fill(_t("%(period)s : %(net)s sur la période. Cherche un commerce, ou filtre d'un geste."), period=period, net=blurred(net)),
    )


# ===== Group 5c: Projets, Paramètres and its pages, Import ==========================


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


def projects_answer(projects: list[dict], today: date) -> Answer:
    """The sentence of the Projets screen.

    Each project is {"name", "state", "gap_months", "monthly_effort", "effort"}
    (state as in crud.project_rhythm). Returns an Answer whose `focus` is the name of the project that is the
    furthest behind, or None.
    """
    if not projects:
        return Answer(_t("Pas encore de projet."), _t("Mets de l'argent de côté pour un but précis, avec une date : Twiga te dit quand tu y arrives."))
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
    return Answer(phrase, detail, focus=worst["name"] if worst else None)


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


# --- Paramètres ---------------------------------------------------------------


def settings_answer(
    oldest_check: dict | None, suggestions: int, accounts: int, categories: int, rules: int
) -> Answer:
    """The sentence of the settings hub: "all is in place", then the one thing that waits.

    `oldest_check` is {"number", "days"} for the payment that has waited the longest
    for its debit, or None. The action tells where to go and is None when nothing waits.
    """
    counts = " ".join(
        [
            ngettext("%(n)s compte,", "%(n)s comptes,", accounts) % {"n": accounts},
            ngettext("%(n)s catégorie,", "%(n)s catégories,", categories) % {"n": categories},
            ngettext("%(n)s règle de rangement.", "%(n)s règles de rangement.", rules) % {"n": rules},
        ]
    )
    detail = counts + " " + _t("Ce qui bouge le plus est en haut, le plus délicat tout en bas.")
    if oldest_check is not None:
        if oldest_check.get("number"):
            waiting = ngettext(
                "Le chèque n° %(number)s attend son débit depuis %(n)s jour.",
                "Le chèque n° %(number)s attend son débit depuis %(n)s jours.",
                oldest_check["days"],
            ) % {"number": oldest_check["number"], "n": oldest_check["days"]}
        else:
            waiting = ngettext(
                "Un paiement attend son débit depuis %(n)s jour.",
                "Un paiement attend son débit depuis %(n)s jours.",
                oldest_check["days"],
            ) % {"n": oldest_check["days"]}
        return Answer(_t("Tout est en place.") + " " + waiting, detail, action=("/checks", _t("Voir les paiements en attente")))
    if suggestions:
        waiting = ngettext(
            "%(n)s règle proposée attend ton avis.", "%(n)s règles proposées attendent ton avis.", suggestions
        ) % {"n": suggestions}
        return Answer(_t("Tout est en place.") + " " + waiting, detail, action=("/rules", _t("Voir les règles proposées")))
    return Answer(_t("Tout est en place."), detail)


def checks_answer(count: int, total: str | None, oldest: dict | None) -> Answer:
    """The sentence of the Chèques screen: how many payments wait, for how much, and since when.

    `oldest` is {"number", "days"} for the payment that has waited the longest."""
    if count == 0:
        return Answer(_t("Aucun paiement n'attend son débit."), _t(
                "Un chèque ou un paiement émis s'enregistre ici, et Twiga le rapproche seul quand il passe sur le compte."
            ))
    phrase = ngettext(
        "%(n)s paiement attend son débit, %(total)s.",
        "%(n)s paiements attendent leur débit, %(total)s.",
        count,
    ) % {"n": count, "total": total}
    tail = _t("Dès qu'il apparaît dans une opération importée, je le range tout seul.")
    if oldest and oldest.get("number"):
        waiting = ngettext(
            "Le chèque n° %(number)s attend depuis %(n)s jour.",
            "Le chèque n° %(number)s attend depuis %(n)s jours.",
            oldest["days"],
        ) % {"number": oldest["number"], "n": oldest["days"]}
    elif oldest:
        waiting = ngettext(
            "Le plus ancien attend depuis %(n)s jour.", "Le plus ancien attend depuis %(n)s jours.", oldest["days"]
        ) % {"n": oldest["days"]}
    else:
        waiting = ""
    return Answer(phrase, (waiting + " " + tail).strip())


def accounts_answer(accounts: int, pairs: int) -> Answer:
    """The sentence of the Comptes screen: how many accounts, and what waits to be confirmed."""
    count = ngettext("%(n)s compte", "%(n)s comptes", accounts) % {"n": accounts}
    if pairs:
        phrase = count + ", " + ngettext(
            "%(n)s virement interne à confirmer.", "%(n)s virements internes à confirmer.", pairs
        ) % {"n": pairs}
        detail = _t(
            "Ces paires ressemblent à des virements entre tes comptes : montant opposé, quelques jours d'écart. "
            "Confirmées, elles ne comptent plus comme dépenses."
        )
    else:
        phrase = count + ", " + _t("aucun virement interne à confirmer.")
        detail = _t(
            "Le solde de chaque compte vient du solde initial et des opérations importées : le détail se déplie sur le compte."
        )
    return Answer(phrase, detail)


def categories_answer(total: int, unset: int, overrides: int, excluded: int) -> Answer:
    """The sentence of the Catégories screen: every category counts in a pillar of Le Cap."""
    count = ngettext("%(n)s catégorie", "%(n)s catégories", total) % {"n": total}
    if unset:
        phrase = count + ", " + ngettext(
            "%(n)s sans pilier choisi : elle compte dans Choix.",
            "%(n)s sans pilier choisi : elles comptent dans Choix.",
            unset,
        ) % {"n": unset}
    else:
        phrase = count + ", " + _t("toutes rangées dans un pilier du Cap.")
    parts = []
    if overrides:
        parts.append(
            ngettext(
                "%(n)s sous-catégorie a son propre pilier (« override »).",
                "%(n)s sous-catégories ont leur propre pilier (« override »).",
                overrides,
            )
            % {"n": overrides}
        )
    if excluded:
        parts.append(
            ngettext(
                "%(n)s catégorie de revenu ne compte pas dans les Budgets.",
                "%(n)s catégories de revenu ne comptent pas dans les Budgets.",
                excluded,
            )
            % {"n": excluded}
        )
    if not parts:
        parts.append(_t("Une sous-catégorie suit le pilier de sa catégorie, sauf si tu lui en donnes un autre."))
    return Answer(phrase, " ".join(parts))


def rules_answer(suggestions: int, rules: int) -> Answer:
    """The sentence of the Règles screen: the proposals that wait for an opinion come first."""
    if suggestions:
        phrase = ngettext(
            "%(n)s règle attend ton avis.", "%(n)s règles attendent ton avis.", suggestions
        ) % {"n": suggestions}
        detail = _t(
            "Je les ai notées en te voyant ranger tes opérations dans La Savane. Une proposition ignorée ne revient plus."
        )
    elif rules:
        phrase = ngettext("%(n)s règle range tes opérations.", "%(n)s règles rangent tes opérations.", rules) % {"n": rules}
        detail = _t("Les plus utilisées viennent en premier. Teste un libellé pour voir quelle règle s'appliquerait.")
    else:
        phrase = _t("Aucune règle pour l'instant.")
        detail = _t(
            "Ajoutes-en une, ou valide des opérations dans La Savane : une règle te sera proposée automatiquement."
        )
    return Answer(phrase, detail)


def payments_answer(modes: int, missing: int) -> Answer:
    """The sentence of the Modes de paiement screen: how many modes, and the operations without one."""
    count = ngettext("%(n)s mode de paiement.", "%(n)s modes de paiement.", modes) % {"n": modes}
    if missing:
        phrase = count + " " + ngettext(
            "%(n)s opération n'a pas encore le sien.", "%(n)s opérations n'ont pas encore le leur.", missing
        ) % {"n": format_integer(missing)}
    else:
        phrase = count + " " + _t("Toutes les opérations ont le leur.")
    detail = _t(
        "Je peux lire les libellés pour deviner le mode : « CARTE SUPERMARCHE » devient CB. "
        "Ces modes servent aux règles, aux chèques et aux filtres."
    )
    return Answer(phrase, detail)


def recurring_state(item: dict) -> str:
    """Where a detected subscription stands: "ignored", "inactive", "seen" (already debited
    this month) or "pending" (expected this month, not seen yet)."""
    if item["status"] == "ignored":
        return "ignored"
    if item["activity_status"] == "inactive":
        return "inactive"
    return "seen" if item["seen_this_month"] else "pending"


def recurring_answer(active: int, expected: int, total: str) -> Answer:
    """The sentence of the Abonnements screen: how many, and how many are still expected this month."""
    if not active:
        return Answer(_t("Aucun abonnement détecté pour l'instant."), _t("Un abonnement apparaît quand le même montant revient à intervalle régulier."))
    count = ngettext("%(n)s abonnement", "%(n)s abonnements", active) % {"n": active}
    if expected:
        phrase = count + ", " + ngettext(
            "%(n)s attendu ce mois n'est pas encore passé.",
            "%(n)s attendus ce mois ne sont pas encore passés.",
            expected,
        ) % {"n": expected}
    else:
        phrase = count + ", " + _t("tous sont passés ce mois-ci.")
    detail = ngettext(
        "%(n)s abonnement détecté · Total mensuel estimé : %(total)s",
        "%(n)s abonnements détectés · Total mensuel estimé : %(total)s",
        active,
    ) % {"n": active, "total": total}
    return Answer(phrase, detail)


def users_answer(roles: dict, never_logged: list[str], admins: list[str]) -> Answer:
    """The sentence of the Utilisateurs screen: how many people have access, and who never opened
    their account. `roles` counts the active accounts by role; `admins` names the active administrators."""
    total = sum(roles.values())
    phrase = ngettext("%(n)s personne a accès.", "%(n)s personnes ont accès.", total) % {"n": total}
    if never_logged:
        names = ", ".join(never_logged)
        phrase += " " + ngettext(
            "%(names)s n'a jamais ouvert son compte.", "%(names)s n'ont jamais ouvert leur compte.", len(never_logged)
        ) % {"names": names}
    counts = ", ".join(
        [
            ngettext("%(n)s administrateur", "%(n)s administrateurs", roles.get("admin", 0)) % {"n": roles.get("admin", 0)},
            ngettext("%(n)s éditeur", "%(n)s éditeurs", roles.get("editor", 0)) % {"n": roles.get("editor", 0)},
            _t("%(n)s en lecture seule") % {"n": roles.get("viewer", 0)},
        ]
    )
    if admins:
        keep = _t("Il doit toujours rester au moins un administrateur actif : pour l'instant, c'est %(names)s.") % {
            "names": ", ".join(admins)
        } if len(admins) == 1 else _t(
            "Il doit toujours rester au moins un administrateur actif : pour l'instant, %(names)s."
        ) % {"names": ", ".join(admins)}
    else:
        keep = _t("Il doit toujours rester au moins un administrateur actif.")
    return Answer(phrase, f"{counts}. {keep}")


# --- Mon profil -----------------------------------------------------------------


def profile_words() -> dict:
    """The words of the display sentence, by choice: the page rewrites the sentence from
    them while the user picks, with no request."""
    return {
        "theme": {"light": _t("Thème clair"), "system": _t("Thème automatique"), "dark": _t("Thème sombre")},
        "density": {
            "compact": _t("affichage compact"),
            "normal": _t("affichage normal"),
            "comfortable": _t("affichage aéré"),
        },
        "privacy": {"hidden": _t("montants masqués"), "visible": _t("montants visibles")},
    }


def profile_answer(theme: str, density: str, hidden: bool) -> Answer:
    """The sentence of Mon profil: what the user will see, in three choices."""
    words = profile_words()
    title = "%s, %s, %s." % (
        words["theme"].get(theme, words["theme"]["system"]),
        words["density"].get(density, words["density"]["normal"]),
        words["privacy"]["hidden" if hidden else "visible"],
    )
    return Answer(title, "")


# --- Connexion ------------------------------------------------------------------


def login_title(with_accounts: bool) -> str:
    """The greeting of the login page: it asks who is there only when the accounts are shown as tiles."""
    return _t("Bonjour ! Qui est là ?") if with_accounts else _t("Bonjour !")


# --- Rôles: the reader's La Savane --------------------------------------------------


def reader_answer(waiting: int, helper: str | None) -> Answer:
    """The sentence of La Savane for someone who may read but not write: no decision is
    asked of them, so the sentence says what they can do and who can file the rest."""
    title = _t("Tu peux consulter, pas modifier.")
    if waiting <= 0:
        return Answer(title, _t("Rien n'attend d'être rangé pour l'instant."))
    count = ngettext(
        "%(n)s opération attend d'être rangée.", "%(n)s opérations attendent d'être rangées.", waiting
    ) % {"n": waiting}
    who = _t("%(name)s ou un éditeur peut s'en charger.") % {"name": helper} if helper else _t("Un éditeur peut s'en charger.")
    return Answer(title, f"{count} {who}")


def reader_lot_title(value: date) -> str:
    """"Le lot de septembre" / "Le lot d'octobre": the French elision is decided here."""
    name = month_in_sentence(value)
    if current_language() == "fr" and name[0] in "aeiouyéèêâôû":
        return _t("Le lot d'%(month)s") % {"month": name}
    return _t("Le lot de %(month)s") % {"month": name}


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


def import_idle_answer(has_accounts: bool) -> Answer:
    """The drop screen: one file is enough, and the very first import is a HomeBank history."""
    if not has_accounts:
        return Answer(_t("Aucun compte pour l'instant : commence par un historique HomeBank."), _t(
                "Importe d'abord un fichier QIF : il crée tes comptes et tes catégories. "
                "Les CSV et OFX suivants viendront alimenter un compte existant."
            ))
    return Answer(_t("Un fichier suffit, Twiga reconnaît le reste."), _t(
            "Dépose un relevé CSV, OFX ou QIF. Le format et le compte sont repérés seuls, rien ne quitte ton serveur."
        ))


def import_recap_answer(
    fmt: str, account_name: str, to_import: int, duplicates: int, delimiter: str | None = None
) -> Answer:
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
            "%(n)s doublon est déjà écarté, il ne reste qu'à confirmer.",
            "Les %(n)s doublons sont déjà écartés, il ne reste qu'à confirmer.",
            duplicates,
        ) % {"n": duplicates}
    else:
        tail = _t("Aucun doublon : il ne reste qu'à confirmer.")
    return Answer(phrase, f"{kind} {tail}")


def import_qif_answer(
    accounts: int, categories: int, transactions: int, duplicates: int, new_accounts: int
) -> Answer:
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
    return Answer(phrase, " ".join(parts))


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
                    "%(n)s autre t'attend dans La Savane : environ %(m)s minute.",
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
