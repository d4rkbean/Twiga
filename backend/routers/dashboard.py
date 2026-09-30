from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from backend import crud
from backend.database import get_db
from backend.dates import (
    MONTH_NAMES_FR,
    format_date_long_fr,
    month_label,
    month_range,
    shift_month,
    trailing_months_ending,
)
from backend.formatting import format_amount
from backend.templating import templates

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _parse_account_id(raw: str | None) -> int | None:
    return int(raw) if raw else None


def _prev_month_year(month: int, year: int) -> tuple[int, int]:
    return (12, year - 1) if month == 1 else (month - 1, year)


# Raccourcis de période proposés dans le Panorama, dans l'ordre d'affichage.
# Volontairement courts : le sélecteur doit se lire d'un coup d'œil.
PERIOD_CHOICES = [
    ("mois", "Mois en cours"),
    ("mois-dernier", "Mois dernier"),
    ("90j", "90 J"),
    ("1an", "1 an"),
    ("perso", "Personnalisé"),
]
PERIOD_KEYS = {key for key, _ in PERIOD_CHOICES}
DEFAULT_PERIOD = "mois"


def _parse_iso_date(raw: str | None) -> date | None:
    try:
        return date.fromisoformat(raw) if raw else None
    except ValueError:
        # Date inexploitable dans l'URL (saisie manuelle, lien tronqué) : on
        # retombe sur la période par défaut plutôt que de renvoyer une 500.
        return None


def _resolve_period(
    period: str | None, start: str | None, end: str | None, today: date
) -> tuple[str, date, date, str, bool]:
    """Traduit le choix de période en un intervalle de dates concret.

    Renvoie `(clé, début, fin, libellé, est_un_mois_civil)`.

    `est_un_mois_civil` commande tout ce qui n'a de sens qu'au mois : le
    décalage des recettes (« les recettes de M-1 financent les dépenses de
    M ») n'est pas définissable sur « 90 derniers jours ». Plutôt que de
    produire un chiffre douteux, l'appelant désactive la case dans ce cas.
    """
    key = period if period in PERIOD_KEYS else DEFAULT_PERIOD

    if key == "perso":
        custom_start = _parse_iso_date(start)
        custom_end = _parse_iso_date(end)
        if custom_start and custom_end:
            # Bornes inversées : on les remet à l'endroit au lieu de renvoyer
            # une période vide, qui n'aurait aucune valeur de diagnostic pour
            # qui vient de saisir deux dates à la main.
            if custom_start > custom_end:
                custom_start, custom_end = custom_end, custom_start
            label = f"{format_date_long_fr(custom_start)} → {format_date_long_fr(custom_end)}"
            is_month = (custom_start, custom_end) == month_range(
                custom_start.year, custom_start.month
            )
            return key, custom_start, custom_end, label, is_month
        key = DEFAULT_PERIOD

    if key == "mois":
        period_start, period_end = month_range(today.year, today.month)
        return key, period_start, period_end, month_label(today.year, today.month), True
    if key == "mois-dernier":
        prev_month, prev_year = _prev_month_year(today.month, today.year)
        period_start, period_end = month_range(prev_year, prev_month)
        return key, period_start, period_end, month_label(prev_year, prev_month), True
    days = {"90j": 90, "1an": 365}[key]
    label = {"90j": "90 derniers jours", "1an": "12 derniers mois"}[key]
    return key, today - timedelta(days=days - 1), today, label, False


def _build_period_context(
    db: Session,
    period_key: str,
    period_start: date,
    period_end: date,
    period_label: str,
    is_calendar_month: bool,
    account_id: int | None,
    shift_income: bool = False,
    today: date | None = None,
) -> dict:
    today = today or date.today()

    # "Décalage recettes" (même logique que la page Rapports) : le salaire
    # perçu fin du mois précédent finance les dépenses du mois sélectionné.
    # Décalé ensemble (recettes ET donut/liste Recettes) pour rester cohérent
    # — la carte "Recettes période" et le donut juste en dessous doivent
    # toujours pointer sur le même total, jamais deux chiffres différents
    # pour "les recettes" sur la même page. Les dépenses (montant, donut,
    # tendance) ne sont JAMAIS décalées.
    #
    # Réservé aux périodes qui SONT un mois civil : "les recettes de M-1" ne
    # veut rien dire sur "90 derniers jours". Hors de ce cas la case est
    # désactivée dans le gabarit et le décalage forcé à faux ici — on ne
    # laisse pas un réglage actif produire un total qu'on ne saurait pas
    # expliquer.
    shift_income = shift_income and is_calendar_month
    if shift_income:
        prev_month, prev_year = _prev_month_year(period_start.month, period_start.year)
        income_period_start, income_period_end = month_range(prev_year, prev_month)
        shift_label = f"Recettes {MONTH_NAMES_FR[prev_month - 1]} → Dépenses {period_label}"
    else:
        income_period_start, income_period_end = period_start, period_end
        shift_label = None

    income_total = crud.get_income_total(db, income_period_start, income_period_end, account_id)
    expense_total = crud.get_expense_total(db, period_start, period_end, account_id)
    result_total = income_total - expense_total

    category_spending = crud.get_category_spending(db, period_start, period_end, account_id)
    income_spending = crud.get_category_income(db, income_period_start, income_period_end, account_id)
    # "None" (non catégorisé) n'est pas sérialisable tel quel dans l'URL du
    # clic donut (voir _content.html) : remplacé par la chaîne "none",
    # reconnue par category_transactions ci-dessous.
    category_ids = [cid if cid is not None else "none" for cid, _, _ in category_spending]
    income_category_ids = [cid if cid is not None else "none" for cid, _, _ in income_spending]

    # Courbe d'évolution : toujours 12 mois glissants se terminant sur le mois
    # qui CONTIENT la fin de période. Une période de 7 ou 90 jours ne fait pas
    # une courbe lisible ; on garde donc la maille mensuelle et on situe la
    # période choisie dedans, plutôt que de faire varier l'échelle du
    # graphique avec le sélecteur.
    months = trailing_months_ending(period_end.year, period_end.month)
    monthly_expense_totals = crud.get_monthly_expense_totals(db, months[0][0], months[-1][1], account_id)
    # La tendance des recettes suit le décalage, exactement comme
    # crud.get_period_monthly_breakdown(shift_income=True) le fait pour le
    # détail mensuel des Rapports : sans ça, la carte au-dessus compare les
    # recettes de M-1 aux dépenses de M pendant que la courbe juste en
    # dessous compare M à M — deux lectures contradictoires des mêmes
    # recettes sur la même page. La fenêtre de requête démarre un mois plus
    # tôt pour couvrir le premier point du graphique.
    income_query_start = shift_month(months[0][0], -1) if shift_income else months[0][0]
    monthly_income_totals = crud.get_monthly_income_totals(
        db, income_query_start, months[-1][1], account_id
    )
    trend_labels = [label for _, _, label in months]
    trend_expense_values = [
        monthly_expense_totals.get(start, Decimal("0.00")) for start, _, _ in months
    ]
    trend_income_values = [
        monthly_income_totals.get(
            shift_month(start, -1) if shift_income else start, Decimal("0.00")
        )
        for start, _, _ in months
    ]
    trend_income_label = "Recettes (M-1)" if shift_income else "Recettes"

    # Budgets déjà triés par % consommé décroissant (get_budget_progress) :
    # les 6 premiers (grille compacte 3 colonnes x 2 rangées en desktop) sont
    # donc naturellement les plus urgents à surveiller, cohérent avec un
    # aperçu Panorama plutôt qu'une liste exhaustive (toujours disponible via
    # "Voir tous →" -> /budgets).
    #
    # Les budgets sont définis PAR MOIS : les confronter à « 90 derniers
    # jours » comparerait une enveloppe mensuelle à trois mois de dépenses.
    # Ils restent donc calés sur le mois civil en cours quelle que soit la
    # période choisie, et le gabarit affiche ce mois dans le titre pour que
    # l'écart avec le reste de la page soit explicite. Même règle que les
    # objectifs du Cap (voir _build_cap_progress).
    budget_month_start, budget_month_end = month_range(today.year, today.month)
    budget_progress = crud.get_budget_progress(db, budget_month_start, budget_month_end, account_id)
    budget_progress_total = len(budget_progress)
    # Les budgets les plus consommés d'abord (get_budget_progress trie déjà
    # par pourcentage décroissant) : la colonne du Récapitulatif ne montre
    # que ceux qui appellent une décision, pas la liste complète — celle-ci
    # vit sur « Mon mois », qui est faite pour ça.
    budgets_at_risk = [b for b in budget_progress if b["percentage"] >= 75][:5]

    return {
        "period_key": period_key,
        "period_start": period_start,
        "period_end": period_end,
        "is_calendar_month": is_calendar_month,
        "period_choices": PERIOD_CHOICES,
        "budget_month": today.month,
        "budget_year": today.year,
        "budget_month_label": month_label(today.year, today.month),
        "account_id": account_id,
        "period_label": period_label,
        "shift_income": shift_income,
        "shift_label": shift_label,
        "income_total": income_total,
        "expense_total": expense_total,
        "result_total": result_total,
        "category_spending": category_spending,
        "category_labels": [name for _, name, _ in category_spending],
        "category_values": [amount for _, _, amount in category_spending],
        "category_ids": category_ids,
        "income_spending": income_spending,
        "income_labels": [name for _, name, _ in income_spending],
        "income_values": [amount for _, _, amount in income_spending],
        "income_category_ids": income_category_ids,
        "trend_labels": trend_labels,
        "trend_expense_values": trend_expense_values,
        "trend_income_values": trend_income_values,
        "trend_income_label": trend_income_label,
        "budget_progress": budget_progress[:6],
        "budget_progress_total": budget_progress_total,
        "budgets_at_risk": budgets_at_risk,
    }


def _build_project_summaries(db: Session, today: date) -> tuple[list[dict], int]:
    # Résumé lecture-seule pour la grille "Projets" du Panorama — pas les
    # dialogues d'édition/mouvements de la vraie page Projets, juste de quoi
    # visualiser l'avancement d'un coup d'œil et y renvoyer. Tronqué à 6
    # (grille compacte 3 colonnes x 2 rangées en desktop), total conservé
    # pour le lien "Voir tous les projets →".
    summaries = []
    for project in crud.list_projects(db):
        percentage = (
            min(project.current_amount / project.target_amount * 100, Decimal("100"))
            if project.target_amount
            else Decimal("0")
        )
        summaries.append(
            {
                "project": project,
                "percentage_display": round(percentage),
                "bar_width": max(0, min(round(percentage), 100)),
                "monthly_effort": crud.compute_monthly_effort(
                    project.target_amount, project.current_amount, project.target_date, today
                ),
            }
        )
    return summaries[:6], len(summaries)


def _build_row1_totals(db: Session, today: date, shift_income: bool) -> tuple[Decimal, Decimal, Decimal]:
    # Carte "Ce mois" (ROW 1) : toujours le mois CIVIL en cours (jamais le
    # mois sélectionné dans les filtres, voir _build_period_context pour
    # celui-là), avec le même décalage recettes que la carte "Recettes
    # période" quand actif. Dépenses jamais décalées.
    current_month_start, current_month_end = month_range(today.year, today.month)
    if shift_income:
        prev_month, prev_year = _prev_month_year(today.month, today.year)
        income_start, income_end = month_range(prev_year, prev_month)
    else:
        income_start, income_end = current_month_start, current_month_end
    row1_income = crud.get_income_total(db, income_start, income_end, None)
    row1_expense = crud.get_expense_total(db, current_month_start, current_month_end, None)
    return row1_income, row1_expense, row1_income - row1_expense



def _build_cap_progress(db: Session, today: date):
    """Avancement des trois piliers du Cap pour le mois CIVIL en cours.

    Renvoie `(cap_entry, pillars, savings_so_far)`, ou `(None, None, None)`
    si aucun cap n'a été fixé pour ce mois.

    Toujours le mois civil, jamais la période sélectionnée dans les filtres :
    le Cap est un engagement mensuel, le regarder sur « juin 2024 » alors
    qu'on est en septembre n'aurait pas de sens. Les gabarits doivent donc
    l'étiqueter explicitement comme tel (voir dashboard/_content.html).

    Partagé entre `dashboard()` et `dashboard_content()` : depuis que les
    objectifs du Cap sont rendus DANS la carte Évolution (fragment
    `_content.html`, re-rendu seul à chaque changement de filtre), les deux
    routes en ont besoin.

    `spent` et `planned` sont exposés en plus de `ratio` : la carte affiche
    « dépensé / prévu » à côté de la jauge, un pourcentage seul ne dit pas
    de combien on dépasse.
    """
    current_month_start, _ = month_range(today.year, today.month)
    cap_entry = crud.get_cap_entry_for_month(db, current_month_start)
    if cap_entry is None:
        return None, None, None

    actuals = crud.get_pillar_actuals(db, current_month_start, today)
    # Même règle que /cap/mid : on compare à ce qui était engagé, pas à ce
    # qui est encaissé — le budget arrive par virement, exclu des recettes.
    savings_so_far = cap_entry.planned_income - sum(actuals.values(), Decimal("0.00"))
    pillars = [
        {
            "key": key,
            "label": label,
            "icon": tabler_icon,
            "spent": actuals[key],
            "planned": planned,
            # Plafonné à 100 pour la LARGEUR de la jauge uniquement ; le
            # dépassement reste lisible via le couple dépensé/prévu affiché
            # à côté, et via `over` qui pilote la couleur.
            "ratio": min(round(actuals[key] / planned * 100), 100) if planned else 0,
            "over": bool(planned) and actuals[key] > planned,
        }
        for key, label, tabler_icon, planned in [
            ("essentiel", "Essentiel", "home", cap_entry.planned_essentiel),
            ("choix", "Choix", "star", cap_entry.planned_choix),
            ("imprevu", "Imprévu", "urgent", cap_entry.planned_imprevu),
        ]
    ]
    return cap_entry, pillars, savings_so_far


@router.get("", response_class=HTMLResponse)
def dashboard(
    request: Request,
    period: str | None = None,
    start: str | None = None,
    end: str | None = None,
    account_id: str | None = None,
    shift_income: str | None = None,
    db: Session = Depends(get_db),
):
    today = date.today()
    period_key, period_start, period_end, period_label, is_calendar_month = _resolve_period(
        period, start, end, today
    )
    parsed_account_id = _parse_account_id(account_id)
    parsed_shift_income = shift_income == "1"

    # Cartes "solde par compte" : toujours le mois CIVIL en cours pour
    # l'évolution, indépendamment de la période sélectionnée dans les
    # filtres (qui ne s'applique qu'à la section #dashboard-content).
    current_month_start, current_month_end = month_range(today.year, today.month)
    account_balances = crud.get_account_balances_with_monthly_evolution(
        db, current_month_start, current_month_end
    )
    # Toujours égal à la somme des soldes réels par compte (voir
    # crud.get_total_balance) : les virements, correctement appariés ou non,
    # doivent être comptés ici comme n'importe quelle transaction.
    total_balance = crud.get_total_balance(db)
    accounts = crud.list_accounts(db)

    # ROW 1 (cartes "situation globale") : toujours le mois civil en cours,
    # TOUS comptes confondus, indépendamment des filtres période/compte de la
    # ROW 2 ci-dessous (qui ne pilotent que #dashboard-content) — c'est un
    # aperçu global, pas une vue filtrée. Le décalage recettes (case ROW 2)
    # s'y applique quand même : voir _build_row1_totals.
    row1_income, row1_expense, row1_result = _build_row1_totals(db, today, parsed_shift_income)

    row1_budget_progress = crud.get_budget_progress(db, current_month_start, current_month_end, None)
    budget_ok_count = sum(1 for b in row1_budget_progress if b["percentage"] <= 75)
    budget_warning_count = sum(1 for b in row1_budget_progress if 75 < b["percentage"] <= 90)
    budget_danger_count = sum(1 for b in row1_budget_progress if b["percentage"] > 90)

    pending_count = crud.count_pending_transactions(db)


    project_summaries, project_summaries_total = _build_project_summaries(db, today)

    content = _build_period_context(
        db, period_key, period_start, period_end, period_label,
        is_calendar_month, parsed_account_id, parsed_shift_income, today,
    )

    # Carte "Le Cap" (ROW 1) : indépendante du décalage recettes (ROW 2), pas
    # besoin du mécanisme OOB de _ce_mois_card.html/_decision_helper.html —
    # même principe que les cartes Budgets/Alertes, jamais resynchronisée
    # séparément.
    cap_entry, cap_pillar_progress, cap_savings_so_far = _build_cap_progress(db, today)

    context = {
        "request": request,
        "account_balances": account_balances,
        "total_balance": total_balance,
        "accounts": accounts,
        "project_summaries": project_summaries,
        "project_summaries_total": project_summaries_total,
        "row1_income": row1_income,
        "row1_expense": row1_expense,
        "row1_result": row1_result,
        "budget_ok_count": budget_ok_count,
        "budget_warning_count": budget_warning_count,
        "budget_danger_count": budget_danger_count,
        "budget_defined_count": len(row1_budget_progress),
        "pending_count": pending_count,
        "cap_entry": cap_entry,
        "cap_pillar_progress": cap_pillar_progress,
        "cap_savings_so_far": cap_savings_so_far,
        "cap_month_label": f"{MONTH_NAMES_FR[today.month - 1]} {today.year}",
        "show_le_cap_banner": today.day == 1 and cap_entry is None,
        "current_month_key": today.strftime("%Y-%m"),
        **content,
    }
    return templates.TemplateResponse("dashboard/index.html", context)


@router.get("/content", response_class=HTMLResponse)
def dashboard_content(
    request: Request,
    period: str | None = None,
    start: str | None = None,
    end: str | None = None,
    account_id: str | None = None,
    shift_income: str | None = None,
    db: Session = Depends(get_db),
):
    today = date.today()
    parsed_shift_income = shift_income == "1"
    period_key, period_start, period_end, period_label, is_calendar_month = _resolve_period(
        period, start, end, today
    )
    content = _build_period_context(
        db, period_key, period_start, period_end, period_label,
        is_calendar_month, _parse_account_id(account_id), parsed_shift_income, today,
    )
    # La grille Projets fait maintenant partie de _content.html (rangée
    # budgets+projets) : nécessaire ici aussi, ce partial étant re-rendu seul
    # à chaque changement de filtre (mois/année/compte) via HTMX.
    project_summaries, project_summaries_total = _build_project_summaries(db, today)

    # La case "Décaler les recettes" fait partie du même <form> que
    # mois/année/compte (un seul hx-get sur "change" pour tout le monde),
    # mais la carte "Ce mois" et l'aide à la décision (ROW 1) vivent en
    # dehors de #dashboard-content, dans index.html — jamais touchées par ce
    # partial normalement. Recalculées ici et renvoyées en swap "hors
    # bande" (hx-swap-oob, voir dashboard/_ce_mois_card.html et
    # _decision_helper.html) uniquement pour rester synchronisées avec la
    # case à cocher, qui est la SEULE chose parmi mois/année/compte/décalage
    # dont ROW 1 doit tenir compte (ROW 1 reste "toujours le mois civil en
    # cours", indépendante du mois/année/compte sélectionnés).
    row1_income, row1_expense, row1_result = _build_row1_totals(db, today, parsed_shift_income)
    pending_count = crud.count_pending_transactions(db)

    # Les objectifs du Cap sont affichés DANS la carte Évolution, qui fait
    # partie de ce fragment : sans ça, le premier changement de filtre les
    # ferait disparaître. Ils restent calculés sur le mois civil en cours,
    # pas sur la période filtrée (voir _build_cap_progress).
    cap_entry, cap_pillar_progress, cap_savings_so_far = _build_cap_progress(db, today)

    context = {
        "request": request,
        "project_summaries": project_summaries,
        "project_summaries_total": project_summaries_total,
        "row1_income": row1_income,
        "row1_expense": row1_expense,
        "row1_result": row1_result,
        "cap_entry": cap_entry,
        "cap_pillar_progress": cap_pillar_progress,
        "cap_savings_so_far": cap_savings_so_far,
        "cap_month_label": f"{MONTH_NAMES_FR[today.month - 1]} {today.year}",
        "row1_oob": True,
        **content,
    }
    return templates.TemplateResponse("dashboard/_content.html", context)


@router.get("/category-transactions", response_class=HTMLResponse)
def category_transactions(
    request: Request,
    category_id: str,
    start: str,
    end: str,
    label: str,
    type: str,
    account_id: str | None = None,
    db: Session = Depends(get_db),
):
    # Le donut transmet désormais l'intervalle exact affiché (et son libellé)
    # plutôt qu'un couple mois/année : depuis le sélecteur de période, la
    # fenêtre du Panorama n'est plus forcément un mois civil.
    period_start = _parse_iso_date(start) or date.today().replace(day=1)
    period_end = _parse_iso_date(end) or date.today()
    parsed_category_id = None if category_id == "none" else int(category_id)
    transactions = crud.get_category_transactions(
        db,
        period_start,
        period_end,
        parsed_category_id,
        positive=(type == "income"),
        account_id=_parse_account_id(account_id),
    )
    context = {
        "request": request,
        "transactions": transactions,
        "period_label": label,
    }
    return templates.TemplateResponse("dashboard/_category_transactions.html", context)


@router.get("/sidebar-balance", response_class=HTMLResponse)
def sidebar_balance(db: Session = Depends(get_db)):
    # Chargé en hx-trigger="load" depuis _sidebar.html (desktop) : la sidebar
    # est incluse par base.html sur TOUTE page, or total_balance n'était
    # jusqu'ici calculé que dans la route /dashboard elle-même. Un petit
    # endpoint dédié évite d'avoir à faire porter ce calcul par chaque
    # routeur de l'appli juste pour ce badge.
    return HTMLResponse(content=format_amount(crud.get_total_balance(db)))
