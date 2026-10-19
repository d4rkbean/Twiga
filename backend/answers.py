"""Twiga's sentence at the top of each screen of the other way: the answer first.

Every function here is pure: numbers in, an `Answer` out, nothing read from the
database or the request. The routes compute the figures, call one of these and
put the result in the template context; Classic ignores it. The text goes
through gettext (French source, English catalog), and an amount that has to
appear in a sentence arrives already formatted and is wrapped in `.amount-blur`
here, so privacy mode hides it in the headline too.
"""

from __future__ import annotations

from dataclasses import dataclass

from markupsafe import Markup, escape

from backend.i18n import gettext as _t, ngettext


@dataclass(frozen=True)
class Answer:
    """A headline and the line under it. Both may carry blurred amounts (Markup)."""

    title: str
    detail: str


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
