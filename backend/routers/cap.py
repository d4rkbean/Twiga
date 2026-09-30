from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from backend import crud
from backend.database import get_db
from backend.dates import month_label, month_range, shift_month
from backend.pillars import get_pillar_label
from backend.templating import templates

router = APIRouter(prefix="/cap", tags=["cap"])


def _bilan_context(db: Session, month_start: date) -> dict:
    start, end = month_range(month_start.year, month_start.month)
    real_income = crud.get_income_total(db, start, end)
    real_pillars = crud.get_pillar_actuals(db, start, end)
    real_savings = real_income - sum(real_pillars.values(), Decimal("0.00"))

    prev_entry = crud.get_cap_entry_for_month(db, month_start)
    # Même détail par catégorie que « Mon mois », sur le mois révolu : le
    # bilan doit pouvoir répondre à « l'Essentiel a dépassé de 140 € — dont
    # quoi ? » sans quitter l'écran.
    detail = crud.get_month_detail_by_pillar(db, start, end)
    lines = []
    for key, icon, name, real in [
        ("income", "💰", "Revenus", real_income),
        ("essentiel", "🏠", "Essentiel", real_pillars["essentiel"]),
        ("choix", "🌟", "Choix", real_pillars["choix"]),
        ("imprevu", "🆘", "Imprévus", real_pillars["imprevu"]),
        ("savings", "🐷", "Épargne", real_savings),
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
                "icon": icon,
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

    return {
        "bilan_lines": lines,
        "has_previous_cap": prev_entry is not None,
        "unexpected_transactions": crud.get_unexpected_transactions(db, start, end),
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

    return {
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
    today = date.today()
    current_month_start = date(today.year, today.month, 1)
    previous_month_start = shift_month(current_month_start, -1)

    first_use = not crud.has_any_cap_entry(db)
    current_entry = crud.get_cap_entry_for_month(db, current_month_start)

    if current_entry is not None:
        # Le cap du mois courant est déjà fixé : on montre le résumé déjà
        # confirmé plutôt que de re-proposer le wizard depuis le début.
        step_context = {
            "already_set": True,
            "entry": current_entry,
            "current_month_label": month_label(today.year, today.month),
        }
        step_template, current_step = "cap/_step3_confirme.html", 3
    elif first_use:
        step_context = {"first_use": True, **_fixer_context(db, current_month_start)}
        step_template, current_step = "cap/_step2_fixer.html", 2
    else:
        step_context = {
            "previous_month_label": month_label(previous_month_start.year, previous_month_start.month),
            **_bilan_context(db, previous_month_start),
        }
        step_template, current_step = "cap/_step1_bilan.html", 1

    context = {
        "request": request,
        "step_template": step_template,
        "current_step": current_step,
        **step_context,
    }
    return templates.TemplateResponse("cap/index.html", context)


@router.post("/step2", response_class=HTMLResponse)
def cap_step2(
    request: Request,
    reflection_unexpected: str = Form(""),
    reflection_regret: str = Form(""),
    reflection_proud: str = Form(""),
    reflection_worked_well: str = Form(""),
    db: Session = Depends(get_db),
):
    today = date.today()
    current_month_start = date(today.year, today.month, 1)
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
    today = date.today()
    previous_month_start = shift_month(date(today.year, today.month, 1), -1)
    context = {
        "request": request,
        "current_step": 1,
        "previous_month_label": month_label(previous_month_start.year, previous_month_start.month),
        **_bilan_context(db, previous_month_start),
    }
    return templates.TemplateResponse("cap/_step1_bilan.html", context)


@router.post("/save", response_class=HTMLResponse)
async def cap_save(
    request: Request,
    planned_income: str = Form(...),
    planned_imprevu: str = Form(...),
    savings_withdrawal: str = Form("0"),
    intention: str = Form(""),
    reflection_unexpected: str = Form(""),
    reflection_regret: str = Form(""),
    reflection_proud: str = Form(""),
    reflection_worked_well: str = Form(""),
    db: Session = Depends(get_db),
):
    today = date.today()
    current_month_start = date(today.year, today.month, 1)

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
        planned_income=Decimal(planned_income),
        planned_essentiel=sommes["essentiel"],
        planned_choix=sommes["choix"],
        planned_imprevu=Decimal(planned_imprevu),
        intention=intention.strip() or None,
        reflection_unexpected=reflection_unexpected.strip() or None,
        reflection_regret=reflection_regret.strip() or None,
        reflection_proud=reflection_proud.strip() or None,
        reflection_worked_well=reflection_worked_well.strip() or None,
    )
    context = {
        "request": request,
        "current_step": 3,
        "already_set": False,
        "entry": entry,
        "current_month_label": month_label(current_month_start.year, current_month_start.month),
    }
    return templates.TemplateResponse("cap/_step3_confirme.html", context)


@router.get("/mid", response_class=HTMLResponse)
def cap_mid(request: Request, db: Session = Depends(get_db)):
    today = date.today()
    current_month_start = date(today.year, today.month, 1)
    start, end = month_range(today.year, today.month)

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

    pillars = []
    worst_ratio = Decimal("0.00")
    worst_label = None
    for key, icon, name, planned in [
        ("essentiel", "🏠", "Essentiel", sommes_budgets["essentiel"] or None),
        ("choix", "🌟", "Choix", sommes_budgets["choix"] or None),
        ("imprevu", "🆘", "Imprévus", entry.planned_imprevu if entry else None),
    ]:
        actual = pillar_actuals[key]
        ratio = (actual / planned * 100) if planned else Decimal("0.00")
        pillars.append(
            {
                "icon": icon,
                "name": name,
                "actual": actual,
                "planned": planned,
                "ratio": round(ratio),
                "bar_width": min(round(ratio), 100),
                "code": key,
                # L'Imprévu n'a pas de détail par catégorie : c'est une
                # réserve, pas une enveloppe répartie.
                "detail": None if key == "imprevu" else detail.get(key),
            }
        )
        if ratio > worst_ratio:
            worst_ratio = ratio
            worst_label = name

    if worst_ratio > 80:
        status = "danger"
        status_message = f"🔴 {worst_label} presque épuisé à mi-mois !"
    elif worst_ratio > 60:
        status = "warning"
        status_message = f"🟠 Surveillez {worst_label} dans les prochaines semaines."
    else:
        status = "success"
        status_message = "🟢 Le cap tient ! Continuez comme ça."

    context = {
        "request": request,
        "current_month_label": month_label(today.year, today.month),
        "entry": entry,
        "pillars": pillars,
        "savings_so_far": savings_so_far,
        "income_reference": income_reference,
        "income_actual": income_actual,
        "income_is_planned": entry is not None,
        "status": status,
        "status_message": status_message,
    }
    return templates.TemplateResponse("cap/mid.html", context)
