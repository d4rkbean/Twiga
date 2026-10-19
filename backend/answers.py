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
from datetime import date
from decimal import Decimal

from markupsafe import Markup, escape

from backend.dates import month_names
from backend.formatting import format_amount, format_integer
from backend.i18n import current_language, gettext as _t, ngettext


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
            "Une règle proposée attend ton avis.", "%(n)s règles proposées attendent ton avis.", suggestions
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
            "Une opération n'a pas encore le sien.", "%(n)s opérations n'ont pas encore le leur.", missing
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
            "Le doublon est déjà écarté, il ne reste qu'à confirmer.",
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
