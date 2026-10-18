from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from backend import crud
from backend.database import get_db
from backend.dates import (
    month_names,
    format_date_long,
    month_label,
    month_range,
    shift_month,
    trailing_months_ending,
)
from backend.formatting import format_amount
from backend.templating import templates
from backend.i18n import gettext as _t, lazy_gettext

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _parse_account_id(raw: str | None) -> int | None:
    return int(raw) if raw else None


def _prev_month_year(month: int, year: int) -> tuple[int, int]:
    return (12, year - 1) if month == 1 else (month - 1, year)


# Raccourcis de période proposés dans le Panorama, dans l'ordre d'affichage.
# Volontairement courts : le sélecteur doit se lire d'un coup d'œil.
PERIOD_CHOICES = [
    ("mois", lazy_gettext("Mois en cours")),
    ("mois-dernier", lazy_gettext("Mois dernier")),
    ("90j", lazy_gettext("90 J")),
    ("1an", lazy_gettext("1 an")),
    ("perso", lazy_gettext("Personnalisé")),
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
            label = f"{format_date_long(custom_start)} → {format_date_long(custom_end)}"
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
        shift_label = _t("Recettes %(month)s → Dépenses %(period)s") % {
            "month": month_names()[prev_month - 1],
            "period": period_label,
        }
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
    trend_income_label = "Recettes (M-1)" if shift_income else _t("Recettes")

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
        # Chiffres de la bande du haut qui ne dépendent pas de la période mais
        # vivent dans le même fragment : le solde, le nombre de comptes et ce
        # qui attend dans La Savane.
        "total_balance": crud.get_total_balance(db),
        "accounts_count": len(crud.list_accounts(db)),
        "pending_count": crud.count_pending_transactions(db),
        "today_long": format_date_long(today),
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

    # Détail par compte : l'évolution est toujours celle du mois CIVIL en
    # cours, indépendamment de la période sélectionnée dans les filtres (qui
    # ne s'applique qu'à la section #dashboard-content).
    current_month_start, current_month_end = month_range(today.year, today.month)
    account_balances = crud.get_account_balances_with_monthly_evolution(
        db, current_month_start, current_month_end
    )
    accounts = crud.list_accounts(db)

    project_summaries, project_summaries_total = _build_project_summaries(db, today)

    content = _build_period_context(
        db, period_key, period_start, period_end, period_label,
        is_calendar_month, parsed_account_id, parsed_shift_income, today,
    )

    context = {
        "request": request,
        "account_balances": account_balances,
        "accounts": accounts,
        "project_summaries": project_summaries,
        "project_summaries_total": project_summaries_total,
        "show_le_cap_banner": today.day == 1 and crud.get_cap_entry_for_month(db, current_month_start) is None,
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
    context = {
        "request": request,
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
