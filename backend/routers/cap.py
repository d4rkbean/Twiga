from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from backend import answers, crud, month_view
from backend.budget_month import BudgetPeriod, period_containing, period_of_month
from backend.database import get_db
from backend.dates import format_date_short, month_label, month_names, shift_month
from backend.pillars import get_pillar_label
from backend.templating import templates
from backend.i18n import current_language, gettext as _t

router = APIRouter(prefix="/cap", tags=["cap"])


def _current_month(db: Session) -> date:
    """The budget month we are in, as the first day of its month (the key of the plan)."""
    return period_containing(date.today(), crud.get_budget_start_day(db)).month


def _period_of(db: Session, month_start: date) -> BudgetPeriod:
    """The days of the budget month named by `month_start`."""
    return period_of_month(month_start.year, month_start.month, crud.get_budget_start_day(db))


def _month_name(month_start: date) -> str:
    """Month name alone ("Octobre"), as the side panel titles use it."""
    return month_names()[month_start.month - 1]


def _title_for(month_start: date) -> str:
    """"Le Cap d'octobre" / "Le Cap de septembre" (French elision before a vowel)."""
    name = _month_name(month_start)
    if current_language() == "en":
        return _t("Le Cap de %(month)s") % {"month": name}
    name = name.lower()
    if name[0] in "aeiouéèh":
        return _t("Le Cap d'%(month)s") % {"month": name}
    return _t("Le Cap de %(month)s") % {"month": name}


def _fix_title(month_start: date) -> str:
    """"Fixer le cap d'octobre 2026" / "Fixer le cap de septembre 2026"."""
    name = _month_name(month_start)
    if current_language() == "en":
        return _t("Fixer le cap de %(month)s %(year)s") % {"month": name, "year": month_start.year}
    name = name.lower()
    key = _t("Fixer le cap d'%(month)s %(year)s") if name[0] in "aeiouéèh" else _t("Fixer le cap de %(month)s %(year)s")
    return key % {"month": name, "year": month_start.year}


def _plan_summary(income, essentiel, choix, imprevu, withdrawal, goal) -> dict:
    """The figures of the "live" side panel, computed on the server for the steps
    where the plan is not being edited (step 2 recomputes them in the browser)."""
    categories = essentiel + choix
    savings = income - categories - imprevu
    return {
        "income": income,
        "categories": categories,
        "imprevu": imprevu,
        "withdrawal": withdrawal,
        "savings": savings,
        "goal": goal,
        "goal_gap": (savings - goal) if goal else None,
    }


def _pending_by_pillar(db: Session, start: date, end: date) -> dict[str, Decimal]:
    """What sorting La Savane would add to each spending pillar of a month."""
    pending_by_category = {
        item["category"].id: item["pending"] for item in crud.get_budget_envelopes(db, start, end)
    }
    detail = crud.get_month_detail_by_pillar(db, start, end)
    result = {"essentiel": Decimal("0.00"), "choix": Decimal("0.00"), "imprevu": Decimal("0.00")}
    for code in ("essentiel", "choix"):
        for line in detail[code]["categories"]:
            result[code] += pending_by_category.get(line["category"].id, Decimal("0.00"))
    return result


def _pillar_review(db: Session, previous_month_start: date, planned: dict[str, Decimal]) -> list[dict]:
    """The reviewed month, pillar by pillar, against a plan: spent, still waiting in
    La Savane, and the share of the plan "with the sorting"."""
    reviewed = _period_of(db, previous_month_start)
    start, end = reviewed.start, reviewed.last_day
    actuals = crud.get_pillar_actuals(db, start, end)
    pending = _pending_by_pillar(db, start, end)
    rows = []
    for code, label in (("essentiel", _t("Essentiel")), ("choix", _t("Choix")), ("imprevu", _t("Imprévus"))):
        plan = planned.get(code) or Decimal("0.00")
        spent = actuals[code]
        waiting = pending[code]
        ratio = round((spent + waiting) / plan * 100) if plan else None
        spent_width = min(round(spent / plan * 100), 100) if plan else 0
        total_width = min(ratio or 0, 100)
        rows.append(
            {
                "code": code,
                "label": label,
                "spent": spent,
                "pending": waiting,
                "planned": plan,
                "ratio": ratio,
                "bar_width": spent_width,
                "pending_width": max(0, total_width - spent_width),
            }
        )
    return rows


def _wizard_context(db: Session, current_month_start: date) -> dict:
    previous_month_start = shift_month(current_month_start, -1)
    return {
        "cap_title": _title_for(current_month_start),
        "current_month_name": _month_name(current_month_start),
        "previous_month_name": _month_name(previous_month_start),
        "previous_month_name_lower": _month_name(previous_month_start).lower()
        if current_language() != "en"
        else _month_name(previous_month_start),
        "current_month_label_lower": month_label(current_month_start.year, current_month_start.month).lower()
        if current_language() != "en"
        else month_label(current_month_start.year, current_month_start.month),
        "fix_title": _fix_title(current_month_start),
    }


def _bilan_context(db: Session, month_start: date) -> dict:
    reviewed = _period_of(db, month_start)
    start, end = reviewed.start, reviewed.last_day
    real_income = crud.get_income_total(db, start, end)
    real_pillars = crud.get_pillar_actuals(db, start, end)
    real_savings = real_income - sum(real_pillars.values(), Decimal("0.00"))

    prev_entry = crud.get_cap_entry_for_month(db, month_start)
    # Même détail par catégorie que « Mon mois », sur le mois révolu : le
    # bilan doit pouvoir répondre à « l'Essentiel a dépassé de 140 € — dont
    # quoi ? » sans quitter l'écran.
    detail = crud.get_month_detail_by_pillar(db, start, end)
    lines = []
    for key, name, real in [
        ("income", _t("Revenus"), real_income),
        ("essentiel", _t("Essentiel"), real_pillars["essentiel"]),
        ("choix", _t("Choix"), real_pillars["choix"]),
        ("imprevu", _t("Imprévus"), real_pillars["imprevu"]),
        ("savings", _t("Épargne"), real_savings),
    ]:
        planned = None
        écart = None
        écart_color = None
        if prev_entry is not None:
            planned = {
                "income": prev_entry.planned_income,
                "essentiel": prev_entry.planned_essentiel,
                "choix": prev_entry.planned_choix,
                "imprevu": prev_entry.planned_imprevu,
                # L'épargne prévue n'est jamais stockée telle quelle (voir
                # CapEntry) : toujours recalculée, revenus prévus - somme des
                # 3 piliers prévus, cohérent avec le calcul live de l'étape 2.
                "savings": prev_entry.planned_income
                - prev_entry.planned_essentiel
                - prev_entry.planned_choix
                - prev_entry.planned_imprevu,
            }[key]
            if key in ("essentiel", "choix", "imprevu"):
                # Piliers de dépense : rester sous le prévu (réel < prévu)
                # est un BON écart, donc "écart" = prévu - réel pour rester
                # cohérent avec la même règle de couleur (>=0 vert) partout.
                écart = planned - real
            else:
                # income / savings : dépasser le prévu (réel > prévu) est
                # un BON écart.
                écart = real - planned
            if écart >= 0:
                écart_color = "success"
            elif planned and écart > -planned * Decimal("0.10"):
                écart_color = "warning"
            else:
                écart_color = "danger"
        lines.append(
            {
                "name": name,
                "real": real,
                "planned": planned,
                "écart": écart,
                "écart_color": écart_color,
                "code": key,
                # Revenus, Épargne et Imprévus ne se décomposent pas par
                # catégorie : les deux premiers ne sont pas des piliers de
                # dépense, le troisième est une réserve alimentée par des
                # événements et non par des catégories.
                "detail": detail.get(key) if key in ("essentiel", "choix") else None,
            }
        )

    expense_total = crud.get_expense_total(db, start, end)
    pending_total = crud.get_pending_expense_total(db, start, end)
    unbudgeted_total = sum(
        (detail[code]["unbudgeted"] for code in ("essentiel", "choix")), Decimal("0.00")
    )
    planned_savings = lines[-1]["planned"]  # the "savings" line

    # The envelope that sorting La Savane would push closest to its limit.
    envelope_alert = None
    risky = [
        item
        for item in crud.get_budget_envelopes(db, start, end)
        if item["pending"] and item["projected_percentage"] >= 75
    ]
    if risky:
        worst = max(risky, key=lambda item: item["projected_percentage"])
        envelope_alert = {
            "name": worst["category"].name,
            "category": worst["category"],
            "percentage": round(worst["projected_percentage"]),
            "over": worst["projected_percentage"] > 100,
        }

    return {
        "bilan_lines": lines,
        "has_previous_cap": prev_entry is not None,
        "unexpected_transactions": crud.get_unexpected_transactions(db, start, end),
        "bilan_income": real_income,
        "bilan_income_planned": prev_entry.planned_income if prev_entry is not None else None,
        "bilan_expense": expense_total,
        "bilan_pending": pending_total,
        "bilan_result": real_income - expense_total,
        "bilan_result_planned": planned_savings,
        "bilan_unbudgeted": unbudgeted_total,
        "envelope_alert": envelope_alert,
    }


def _fixer_context(db: Session, current_month_start: date) -> dict:
    """Étape 2 : le plan se décide par CATÉGORIE, les piliers en sont la somme.

    Deux piliers seulement se répartissent par catégorie — Essentiel et Choix.
    L'Imprévu reste une enveloppe unique, et ce n'est pas un raccourci : il
    n'est pas peuplé par des catégories mais par des ÉVÉNEMENTS. Une opération
    marquée imprévue bascule dans ce pilier quelle que soit sa catégorie (voir
    crud.resolve_transaction_pillar). On ne peut donc pas prévoir dans quelle
    catégorie tombera un imprévu — seulement en réserver une somme.

    Pré-remplissage : budgets du mois précédent, sinon dépense habituelle
    (médiane 3 mois), voir crud.get_cap_allocation. La réserve d'imprévu
    reprend celle du cap précédent.
    """
    previous_month_start = shift_month(current_month_start, -1)

    # D'où viennent les ressources du mois : réglage, pas règle codée en dur
    # (voir models.CapSettings). Le moteur ignore la réponse — elle ne pilote
    # que ce pré-remplissage.
    settings = crud.get_cap_settings(db)
    prefill_income = crud.get_income_prefill(db, current_month_start)
    virements = (
        crud.get_incoming_transfers_since_last_cap(
            db, current_month_start, settings.income_account_id
        )
        if settings.income_source == "virements"
        else []
    )

    allocation = crud.get_cap_allocation(db, current_month_start)
    previous_entry = crud.get_cap_entry_for_month(db, previous_month_start)
    prefill_imprevu = (
        previous_entry.planned_imprevu if previous_entry is not None else Decimal("0.00")
    )

    # Le réel du mois écoulé par pilier : sert la comparaison du panneau « en
    # direct » (cap/_step2_fixer.html), calculée dans le navigateur. En float
    # pour passer en JSON : ces montants n'y servent qu'à l'affichage.
    previous_period = _period_of(db, previous_month_start)
    previous_start, previous_end = previous_period.start, previous_period.last_day
    previous_actuals = {
        code: float(amount)
        for code, amount in crud.get_pillar_actuals(db, previous_start, previous_end).items()
    }

    previous_pending = {
        code: float(amount)
        for code, amount in _pending_by_pillar(db, previous_start, previous_end).items()
    }
    prefill_goal = previous_entry.savings_goal if previous_entry is not None else None
    withdrawal = crud.get_savings_withdrawal(db, current_month_start)
    essentiel_total = sum((l["prefill"] for l in allocation["essentiel"]["categories"]), Decimal("0.00"))
    choix_total = sum((l["prefill"] for l in allocation["choix"]["categories"]), Decimal("0.00"))
    plan = _plan_summary(prefill_income, essentiel_total, choix_total, prefill_imprevu, withdrawal, prefill_goal)

    return {
        **_wizard_context(db, current_month_start),
        "previous_actuals": previous_actuals,
        "previous_pending": previous_pending,
        "prefill_savings_goal": prefill_goal,
        "plan": plan,
        "review": _pillar_review(
            db,
            previous_month_start,
            {"essentiel": essentiel_total, "choix": choix_total, "imprevu": prefill_imprevu},
        ),
        "current_month_label": month_label(current_month_start.year, current_month_start.month),
        "previous_month_label": month_label(previous_month_start.year, previous_month_start.month),
        "prefill_income": prefill_income,
        "income_source": settings.income_source,
        # Aucun virement n'est pré-coché : aucune fenêtre automatique ne
        # distingue de façon fiable un virement de fin de mois qui finance
        # le mois suivant d'un rajout fait pour le mois courant. On propose
        # la matière, l'utilisateur tranche. Les plus récents en tête.
        "virements": virements,
        "prefill_imprevu": prefill_imprevu,
        # Volontairement PAS repris du mois précédent : un prélèvement sur
        # épargne est une décision ponctuelle (« ce mois-ci je compense un
        # découvert »), pas une habitude à reconduire. Même règle que
        # « Copier le mois précédent » sur la page Budgets.
        "savings_withdrawal": crud.get_savings_withdrawal(db, current_month_start),
        "groupes": [
            {"code": code, "label": get_pillar_label(code), **allocation[code]}
            for code in ("essentiel", "choix")
        ],
    }


@router.get("", response_class=HTMLResponse)
def cap_page(request: Request, db: Session = Depends(get_db)):
    current_month_start = _current_month(db)
    previous_month_start = shift_month(current_month_start, -1)

    first_use = not crud.has_any_cap_entry(db)
    current_entry = crud.get_cap_entry_for_month(db, current_month_start)

    if current_entry is not None:
        # Le cap du mois courant est déjà fixé : on montre le résumé déjà
        # confirmé plutôt que de re-proposer le wizard depuis le début.
        step_context = _confirmed_context(db, current_month_start, current_entry)
        step_template, current_step = "cap/_step3_confirme.html", 3
    elif first_use:
        step_context = {"first_use": True, **_fixer_context(db, current_month_start)}
        step_template, current_step = "cap/_step2_fixer.html", 2
    else:
        step_context = {
            **_fixer_context(db, current_month_start),
            "previous_month_label": month_label(previous_month_start.year, previous_month_start.month),
            **_bilan_context(db, previous_month_start),
        }
        step_template, current_step = "cap/_step1_bilan.html", 1

    context = {
        "request": request,
        "step_template": step_template,
        "current_step": current_step,
        **_wizard_context(db, current_month_start),
        **step_context,
    }
    return templates.TemplateResponse("cap/index.html", context)


def _confirmed_context(db: Session, current_month_start: date, entry) -> dict:
    """Step 3: the confirmed cap, with the same side panel as the other steps."""
    previous_month_start = shift_month(current_month_start, -1)
    withdrawal = crud.get_savings_withdrawal(db, current_month_start)
    return {
        **_wizard_context(db, current_month_start),
        "already_set": True,
        "entry": entry,
        "current_month_label": month_label(current_month_start.year, current_month_start.month),
        "previous_month_label": month_label(previous_month_start.year, previous_month_start.month),
        "plan": _plan_summary(
            entry.planned_income,
            entry.planned_essentiel,
            entry.planned_choix,
            entry.planned_imprevu,
            withdrawal,
            entry.savings_goal,
        ),
        "review": _pillar_review(
            db,
            previous_month_start,
            {
                "essentiel": entry.planned_essentiel,
                "choix": entry.planned_choix,
                "imprevu": entry.planned_imprevu,
            },
        ),
    }


@router.get("/reopen", response_class=HTMLResponse)
def cap_reopen(request: Request, db: Session = Depends(get_db)):
    """"Reprendre le cap": the plan editor again, filled with what was fixed."""
    current_month_start = _current_month(db)
    entry = crud.get_cap_entry_for_month(db, current_month_start)
    context = {
        "request": request,
        "current_step": 2,
        "reopened": entry,
        **_fixer_context(db, current_month_start),
    }
    if entry is not None:
        context["prefill_income"] = entry.planned_income
        context["prefill_imprevu"] = entry.planned_imprevu
        context["prefill_savings_goal"] = entry.savings_goal
        context["intention_value"] = entry.intention or ""
        context["reflection_unexpected"] = entry.reflection_unexpected or ""
        context["reflection_regret"] = entry.reflection_regret or ""
        context["reflection_proud"] = entry.reflection_proud or ""
        context["reflection_worked_well"] = entry.reflection_worked_well or ""
    return templates.TemplateResponse("cap/_step2_fixer.html", context)


@router.post("/step2", response_class=HTMLResponse)
def cap_step2(
    request: Request,
    reflection_unexpected: str = Form(""),
    reflection_regret: str = Form(""),
    reflection_proud: str = Form(""),
    reflection_worked_well: str = Form(""),
    db: Session = Depends(get_db),
):
    current_month_start = _current_month(db)
    context = {
        "request": request,
        "current_step": 2,
        "reflection_unexpected": reflection_unexpected,
        "reflection_regret": reflection_regret,
        "reflection_proud": reflection_proud,
        "reflection_worked_well": reflection_worked_well,
        **_fixer_context(db, current_month_start),
    }
    return templates.TemplateResponse("cap/_step2_fixer.html", context)


@router.post("/step1", response_class=HTMLResponse)
def cap_back_to_step1(request: Request, db: Session = Depends(get_db)):
    current_month_start = _current_month(db)
    previous_month_start = shift_month(current_month_start, -1)
    context = {
        "request": request,
        "current_step": 1,
        **_fixer_context(db, current_month_start),
        "previous_month_label": month_label(previous_month_start.year, previous_month_start.month),
        **_bilan_context(db, previous_month_start),
    }
    return templates.TemplateResponse("cap/_step1_bilan.html", context)


def _decimal(valeur: str) -> Decimal:
    """Montant saisi -> Decimal ; un champ vide ou illisible vaut 0 (jamais une 500)."""
    try:
        return Decimal((valeur or "0").replace(",", ".").strip() or "0")
    except ArithmeticError:
        return Decimal("0")


@router.post("/save", response_class=HTMLResponse)
async def cap_save(
    request: Request,
    planned_income: str = Form("0"),
    planned_imprevu: str = Form("0"),
    savings_withdrawal: str = Form("0"),
    savings_goal: str = Form(""),
    intention: str = Form(""),
    reflection_unexpected: str = Form(""),
    reflection_regret: str = Form(""),
    reflection_proud: str = Form(""),
    reflection_worked_well: str = Form(""),
    db: Session = Depends(get_db),
):
    current_month_start = _current_month(db)

    # Le plan du mois est écrit dans budgets, catégorie par catégorie : c'est
    # la seule source modifiable. Les champs arrivent en amount_<id>, comme
    # dans le formulaire de la page Budgets.
    formulaire = await request.form()
    montants: dict[int, Decimal] = {}
    for cle, valeur in formulaire.items():
        if not cle.startswith("amount_"):
            continue
        try:
            montants[int(cle.removeprefix("amount_"))] = Decimal(str(valeur) or "0")
        except (ValueError, ArithmeticError):
            continue
    crud.save_budgets(db, current_month_start, montants)

    # Le prélèvement sur épargne se décide au moment où l'on pose le plan :
    # c'est l'argent qu'on sort de l'épargne pour le financer. Il n'était
    # saisissable que sur la page Budgets, donc on fixait le cap sans pouvoir
    # répondre à la question posée à cet instant précis.
    try:
        crud.save_savings_withdrawal(db, current_month_start, Decimal(savings_withdrawal or "0"))
    except ArithmeticError:
        pass

    # Les totaux par pilier sont alors RECALCULÉS depuis ces budgets, puis
    # figés dans le cap. Ce n'est pas une duplication de l'intention : les
    # budgets restent le plan vivant, ces trois nombres deviennent la trace
    # de ce qui était prévu CE mois-là. Sans ce gel, modifier un budget
    # réécrirait après coup le bilan des mois passés (voir _bilan_context).
    sommes = crud.get_pillar_budget_sums(db, current_month_start)

    entry = crud.save_cap_entry(
        db,
        current_month_start,
        planned_income=_decimal(planned_income),
        planned_essentiel=sommes["essentiel"],
        planned_choix=sommes["choix"],
        planned_imprevu=_decimal(planned_imprevu),
        savings_goal=_decimal(savings_goal) if _decimal(savings_goal) > 0 else None,
        intention=intention.strip() or None,
        reflection_unexpected=reflection_unexpected.strip() or None,
        reflection_regret=reflection_regret.strip() or None,
        reflection_proud=reflection_proud.strip() or None,
        reflection_worked_well=reflection_worked_well.strip() or None,
    )
    context = {
        "request": request,
        "current_step": 3,
        **_confirmed_context(db, current_month_start, entry),
        "already_set": False,
    }
    return templates.TemplateResponse("cap/_step3_confirme.html", context)


@router.get("/mid", response_class=HTMLResponse)
def cap_mid(request: Request, db: Session = Depends(get_db)):
    today = date.today()
    current_period = period_containing(today, crud.get_budget_start_day(db))
    current_month_start = current_period.month
    start, end = current_period.start, current_period.last_day

    entry = crud.get_cap_entry_for_month(db, current_month_start)
    pillar_actuals = crud.get_pillar_actuals(db, start, today)
    income_actual = crud.get_income_total(db, start, today)

    # L'épargne se mesure contre ce qu'on s'était ENGAGÉ à avoir pour le
    # mois, pas contre ce qui se trouve déjà encaissé.
    #
    # C'est le seul repère qui vaille pour tout le monde : selon les foyers
    # l'argent arrive pendant le mois, à la fin du précédent, ou par
    # virements vers un pot commun — et `get_income_total` exclut les
    # virements. Se référer à l'encaissé rendait donc la jauge fausse une
    # partie du mois, parfois de plusieurs milliers d'euros, pour se
    # corriger d'un coup à l'arrivée de l'argent.
    #
    # Se référer au montant fixé dans le rituel rend la jauge exacte dès le
    # 1er. En contrepartie, l'écran doit afficher l'encaissé à côté : sinon
    # un mois où l'argent promis n'arrive jamais passerait inaperçu (voir
    # income_actual, rendu dans cap/mid.html).
    # Sans cap fixé, on retombe sur l'encaissé — faute de mieux.
    income_reference = entry.planned_income if entry is not None else income_actual
    savings_so_far = income_reference - sum(pillar_actuals.values(), Decimal("0.00"))

    # Le prévu du MOIS EN COURS se lit sur les budgets, pas sur l'instantané
    # figé dans cap_entries : les budgets sont le plan vivant, modifiable à
    # tout moment, et c'est à eux que le détail par catégorie affiché juste
    # en dessous se réfère. Prendre l'instantané ferait diverger la jauge du
    # pilier et la somme de ses lignes (constaté sur septembre 2026 : 3 500 €
    # figés contre 4 000 € de budgets). L'instantané reste la référence du
    # bilan, qui porte lui sur un mois révolu.
    #
    # Exception : l'Imprévu n'est porté par aucune catégorie (voir
    # _fixer_context), donc sa réserve ne peut venir que du cap.
    sommes_budgets = crud.get_pillar_budget_sums(db, current_month_start)
    detail = crud.get_month_detail_by_pillar(db, start, today)

    # What the sorting would add: the expenses still waiting in La Savane that it
    # would put in each budgeted category (same rules as the Panorama envelopes).
    pending_by_category = {
        item["category"].id: item["pending"] for item in crud.get_budget_envelopes(db, start, end)
    }
    for group in detail.values():
        for line in group["categories"]:
            pending = pending_by_category.get(line["category"].id, Decimal("0.00"))
            line["pending"] = pending
            line["projected"] = (
                (line["spent"] + pending) / line["budget"] * 100 if line["budget"] else Decimal("0.00")
            )

    pillars = []
    worst_ratio = Decimal("0.00")
    worst_code = None
    for key, name, planned in [
        ("essentiel", _t("Essentiel"), sommes_budgets["essentiel"] or None),
        ("choix", _t("Choix"), sommes_budgets["choix"] or None),
        ("imprevu", _t("Imprévus"), entry.planned_imprevu if entry else None),
    ]:
        actual = pillar_actuals[key]
        group = None if key == "imprevu" else detail.get(key)
        pending = sum((line["pending"] for line in group["categories"]), Decimal("0.00")) if group else Decimal("0.00")
        ratio = ((actual + pending) / planned * 100) if planned else Decimal("0.00")
        spent_ratio = (actual / planned * 100) if planned else Decimal("0.00")
        pillars.append(
            {
                "name": name,
                "actual": actual,
                "pending": pending,
                "planned": planned,
                "ratio": round(ratio),
                "bar_width": min(round(spent_ratio), 100),
                "pending_width": max(0, min(round(ratio), 100) - min(round(spent_ratio), 100)),
                "code": key,
                # L'Imprévu n'a pas de détail par catégorie : c'est une
                # réserve, pas une enveloppe répartie.
                "detail": group,
            }
        )
        if ratio > worst_ratio:
            worst_ratio = ratio
            worst_code = key

    # Mêmes seuils que les jauges (≥ 75 % à surveiller, > 90 % presque
    # atteint), pour que la phrase et les barres disent la même chose.
    labels = {"essentiel": _t("Essentiel"), "choix": _t("Choix"), "imprevu": _t("Imprévus")}
    warnings = {
        "essentiel": _t("L'Essentiel est à %(percentage)s %% avec le tri : à surveiller."),
        "choix": _t("Le Choix est à %(percentage)s %% avec le tri : à surveiller."),
        "imprevu": _t("Les Imprévus sont à %(percentage)s %% avec le tri : à surveiller."),
    }
    if worst_ratio > 100:
        status = "danger"
        status_message = _t("%(label)s dépassé !") % {"label": labels[worst_code]}
    elif worst_ratio > 90:
        status = "danger"
        status_message = _t("%(label)s presque épuisé !") % {"label": labels[worst_code]}
    elif worst_ratio >= 75:
        status = "warning"
        status_message = warnings[worst_code] % {"percentage": round(worst_ratio)}
    else:
        status = "success"
        status_message = _t("Le cap tient ! Continue comme ça.")

    # The fourth pillar, savings: measured against what the cap set aside.
    if entry is not None:
        savings_target = (
            entry.planned_income - entry.planned_essentiel - entry.planned_choix - entry.planned_imprevu
        )
        savings_ratio = round(savings_so_far / savings_target * 100) if savings_target > 0 else 0
        pillars.append(
            {
                "name": _t("Épargne"),
                "actual": savings_so_far,
                "pending": Decimal("0.00"),
                "planned": savings_target,
                "ratio": savings_ratio,
                "bar_width": max(0, min(savings_ratio, 100)),
                "pending_width": 0,
                "code": "savings",
                "detail": None,
            }
        )

    # Le rythme du mois : la part du mois écoulée, repère des jauges.
    days_in_month = (current_period.end - current_period.start).days
    day_of_month = (today - current_period.start).days + 1
    rhythm = round(day_of_month / days_in_month * 100)
    planned_total = sum((p["planned"] or Decimal("0.00") for p in pillars), Decimal("0.00"))
    spent_total = sum((p["actual"] for p in pillars), Decimal("0.00"))

    context = {
        "request": request,
        "current_month_label": current_period.label,
        "entry": entry,
        "pillars": pillars,
        "savings_so_far": savings_so_far,
        "income_reference": income_reference,
        "income_actual": income_actual,
        "income_is_planned": entry is not None,
        "status": status,
        "status_message": status_message,
        "day_of_month": day_of_month,
        "days_in_month": days_in_month,
        "days_left": days_in_month - day_of_month,
        "rhythm": rhythm,
        "pace_date": format_date_short(today),
        "pending_total": crud.get_pending_expense_total(db),
        "planned_total": planned_total,
        "spent_total": spent_total,
        **_month_other_way_context(db, today, entry),
    }
    return templates.TemplateResponse("cap/mid.html", context)


def _month_other_way_context(db: Session, today: date, entry) -> dict:
    """What only the other way's "Mon mois" reads: the pillars split between what
    is sorted and what still waits in La Savane, the sentence, the fixed charges."""
    view = month_view.build_month_view(db, today)
    lowercase = current_language() != "en"

    def month_word(value: date) -> str:
        name = _month_name(value)
        return name.lower() if lowercase else name

    pillar_names = {"essentiel": _t("Essentiel"), "choix": _t("Choix"), "imprevu": _t("Imprévus")}
    loosest = max(view.pillars, key=lambda p: p.loose_total)
    headline, sub = answers.month_answer(
        has_plan=entry is not None,
        month_name=month_word(view.period.month),
        pillars=[{"code": p.code, "percent": p.percent, "verdict": p.verdict.key} for p in view.pillars],
        day=view.day,
        days=view.days,
        loose=(pillar_names[loosest.code], loosest.loose_total) if loosest.loose_total else None,
        next_cap_title=_title_for(shift_month(view.period.month, 1)),
    )
    return {
        "month_view": view,
        "pillar_names": pillar_names,
        "answer_headline": headline,
        "answer_sub": sub,
        "month_word": month_word(view.period.month),
        "next_cap_title": _title_for(shift_month(view.period.month, 1)),
        "previous_month_word": month_word(shift_month(view.period.month, -1)),
    }
