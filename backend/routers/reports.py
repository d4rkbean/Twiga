import csv
import io
import math
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from backend import crud
from backend.database import get_db
from backend.dates import (
    month_label,
    month_range,
    quarter_label,
    quarter_range,
    semester_label,
    semester_range,
    trailing_months_ending,
    year_label,
    year_range,
)
from backend.formatting import format_amount, format_date
from backend.templating import category_display_filter, templates

router = APIRouter(prefix="/reports", tags=["reports"])

_PERIOD_TYPES = ("mois", "trimestre", "semestre", "annee", "personnalise")
_TRANSACTIONS_PAGE_SIZE = 25


def _parse_account_id(raw: str | None) -> int | None:
    return int(raw) if raw else None


@dataclass
class ResolvedPeriod:
    period_type: str
    start: date
    end: date
    label: str
    prev_start: date
    prev_end: date
    prev_params: dict
    next_params: dict
    month: int
    year: int
    quarter: int
    semester: int
    date_from: str
    date_to: str


def _resolve_period(
    period_type: str | None,
    month: int | None,
    year: int | None,
    quarter: int | None,
    semester: int | None,
    date_from: str | None,
    date_to: str | None,
    today: date,
) -> ResolvedPeriod:
    period_type = period_type if period_type in _PERIOD_TYPES else "mois"

    if period_type == "mois":
        m = month if month and 1 <= month <= 12 else today.month
        y = year or today.year
        start, end = month_range(y, m)
        label = month_label(y, m)
        prev_m, prev_y = (12, y - 1) if m == 1 else (m - 1, y)
        next_m, next_y = (1, y + 1) if m == 12 else (m + 1, y)
        prev_start, prev_end = month_range(prev_y, prev_m)
        prev_params = {"period_type": "mois", "month": prev_m, "year": prev_y}
        next_params = {"period_type": "mois", "month": next_m, "year": next_y}
        quarter, semester = (m - 1) // 3 + 1, 1 if m <= 6 else 2

    elif period_type == "trimestre":
        q = quarter if quarter and 1 <= quarter <= 4 else (today.month - 1) // 3 + 1
        y = year or today.year
        start, end = quarter_range(y, q)
        label = quarter_label(y, q)
        prev_q, prev_y = (4, y - 1) if q == 1 else (q - 1, y)
        next_q, next_y = (1, y + 1) if q == 4 else (q + 1, y)
        prev_start, prev_end = quarter_range(prev_y, prev_q)
        prev_params = {"period_type": "trimestre", "quarter": prev_q, "year": prev_y}
        next_params = {"period_type": "trimestre", "quarter": next_q, "year": next_y}
        month, quarter, semester = today.month, q, 1 if q <= 2 else 2

    elif period_type == "semestre":
        s = semester if semester in (1, 2) else (1 if today.month <= 6 else 2)
        y = year or today.year
        start, end = semester_range(y, s)
        label = semester_label(y, s)
        prev_s, prev_y = (2, y - 1) if s == 1 else (1, y)
        next_s, next_y = (1, y + 1) if s == 2 else (2, y)
        prev_start, prev_end = semester_range(prev_y, prev_s)
        prev_params = {"period_type": "semestre", "semester": prev_s, "year": prev_y}
        next_params = {"period_type": "semestre", "semester": next_s, "year": next_y}
        month, quarter, semester = today.month, (today.month - 1) // 3 + 1, s

    elif period_type == "annee":
        y = year or today.year
        start, end = year_range(y)
        label = year_label(y)
        prev_start, prev_end = year_range(y - 1)
        prev_params = {"period_type": "annee", "year": y - 1}
        next_params = {"period_type": "annee", "year": y + 1}
        month, quarter, semester = today.month, (today.month - 1) // 3 + 1, 1 if today.month <= 6 else 2

    else:  # personnalise
        try:
            start = date.fromisoformat(date_from) if date_from else today.replace(day=1)
        except ValueError:
            start = today.replace(day=1)
        try:
            end = date.fromisoformat(date_to) if date_to else today
        except ValueError:
            end = today
        if start > end:
            start, end = end, start
        y = start.year
        label = f"{format_date(start)} → {format_date(end)}"
        span_days = (end - start).days + 1
        prev_end = start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=span_days - 1)
        next_start = end + timedelta(days=1)
        next_end = next_start + timedelta(days=span_days - 1)
        prev_params = {
            "period_type": "personnalise",
            "date_from": prev_start.isoformat(),
            "date_to": prev_end.isoformat(),
        }
        next_params = {
            "period_type": "personnalise",
            "date_from": next_start.isoformat(),
            "date_to": next_end.isoformat(),
        }
        month, quarter, semester = today.month, (today.month - 1) // 3 + 1, 1 if today.month <= 6 else 2

    return ResolvedPeriod(
        period_type=period_type,
        start=start,
        end=end,
        label=label,
        prev_start=prev_start,
        prev_end=prev_end,
        prev_params=prev_params,
        next_params=next_params,
        # BUG corrigé : dans la branche "mois", la variable locale `month`
        # n'est jamais réassignée (contrairement à `m`, le mois RÉSOLU) — un
        # accès direct à /reports sans ?month= explicite (le cas normal,
        # atterrissage sur le mois en cours) renvoyait period.month=None,
        # ce que _build_report_qs sérialisait tel quel en "month=None" dans
        # l'URL. Inoffensif tant que report_qs ne servait qu'à un <a href>
        # d'export CSV jamais cliqué automatiquement ; devenu bloquant dès
        # que report_qs alimente un hx-get déclenché par hx-trigger="load"
        # (422 Unprocessable Entity, FastAPI ne parse pas la chaîne "None"
        # comme int).
        month=m if period_type == "mois" else today.month,
        year=y,
        quarter=quarter,
        semester=semester,
        date_from=date_from or "",
        date_to=date_to or "",
    )


def _resolve_period_from_params(params: dict, today: date) -> ResolvedPeriod:
    # Reconstruit un ResolvedPeriod complet à partir d'un prev_params déjà
    # produit par _resolve_period (voir "Décalage période" plus bas, onglet
    # Mois) : réutilise la même résolution plutôt que de dupliquer la
    # logique par type de période. Sert à retrouver le mois ENCORE avant
    # (mois-2) pour comparer "vs période précédente" des recettes décalées
    # sur une base cohérente (pas comparer le mois décalé à lui-même).
    return _resolve_period(
        params.get("period_type"),
        params.get("month"),
        params.get("year"),
        params.get("quarter"),
        params.get("semester"),
        params.get("date_from"),
        params.get("date_to"),
        today,
    )


def _percent_change(current: Decimal, previous: Decimal) -> Decimal | None:
    if previous == 0:
        return None
    return ((current - previous) / abs(previous) * 100).quantize(Decimal("1"))


def _build_category_rows(
    db: Session,
    start: date,
    end: date,
    prev_start: date,
    prev_end: date,
    account_id: int | None,
    *,
    positive: bool,
) -> list[dict]:
    current = crud.get_category_spending(db, start, end, account_id) if not positive else crud.get_category_income(db, start, end, account_id)
    previous = crud.get_category_spending(db, prev_start, prev_end, account_id) if not positive else crud.get_category_income(db, prev_start, prev_end, account_id)
    previous_by_id = {cid: amount for cid, _, amount in previous}
    total = sum((amount for _, _, amount in current), Decimal("0.00"))

    rows = []
    for category_id, name, amount in current:
        has_children = category_id is not None and bool(crud.get_child_categories(db, category_id))
        rows.append(
            {
                "category_id": category_id,
                "name": name,
                "amount": amount,
                "percent_of_total": round(amount / total * 100) if total else 0,
                "change": _percent_change(amount, previous_by_id.get(category_id, Decimal("0.00"))),
                "has_children": has_children,
                "subcategories": (
                    crud.get_subcategory_breakdown(db, start, end, category_id, account_id, positive=positive)
                    if has_children
                    else []
                ),
            }
        )
    return rows


def _build_report_qs(period: ResolvedPeriod, account_id: int | None, shift_income: bool = False) -> str:
    # Reconstruit les query params de la période ACTUELLEMENT résolue (pas
    # les query params bruts reçus, qui peuvent être partiels/absents) :
    # sert au lien d'export CSV et aux fetches HTMX de la liste de
    # transactions pour qu'ils portent exactement la période affichée, pas
    # la période par défaut si l'utilisateur a navigué via ← / →.
    qs_params = {"period_type": period.period_type}
    if period.period_type == "mois":
        qs_params.update(month=period.month, year=period.year)
    elif period.period_type == "trimestre":
        qs_params.update(quarter=period.quarter, year=period.year)
    elif period.period_type == "semestre":
        qs_params.update(semester=period.semester, year=period.year)
    elif period.period_type == "annee":
        qs_params.update(year=period.year)
    else:
        qs_params.update(date_from=period.start.isoformat(), date_to=period.end.isoformat())
    if account_id is not None:
        qs_params["account_id"] = account_id
    if shift_income:
        # Propagé dans report_qs (export CSV, base des fetches HTMX de la
        # liste de transactions) pour que ces liens reflètent le "Décalage
        # période" actif — sans effet sur la liste de transactions
        # elle-même (hors périmètre du décalage, voir reports/transactions),
        # ignoré silencieusement par cet endpoint.
        qs_params["shift_income"] = "1"
    return urlencode(qs_params)


def _build_report_context(
    db: Session,
    period_type: str | None,
    month: int | None,
    year: int | None,
    quarter: int | None,
    semester: int | None,
    date_from: str | None,
    date_to: str | None,
    account_id: str | None,
    today: date | None = None,
    shift_income: bool = False,
) -> dict:
    today = today or date.today()
    parsed_account_id = _parse_account_id(account_id)
    period = _resolve_period(period_type, month, year, quarter, semester, date_from, date_to, today)

    # "Décalage période" : reflète la réalité d'un budget familial où le
    # salaire perçu fin du mois M-1 finance les dépenses du mois M — un
    # concept intrinsèquement MENSUEL. Décaler des totaux agrégés sur une
    # période plus large (ex. recettes de l'année N-1 vs dépenses de
    # l'année N, ou du trimestre précédent) n'a pas de sens (demandé
    # explicitement) : restreint à l'onglet Mois, où "le mois précédent" est
    # sans ambiguïté. Trimestre/Semestre/Personnalisé restent TOUJOURS sur
    # la période sélectionnée, jamais décalés. Pour Année, seul le détail
    # mensuel (mois par mois) est concerné — voir monthly_shift_active plus
    # bas, qui pilote crud.get_period_monthly_breakdown ; les métriques
    # héros, barres Balance et onglet Budget restent sur l'année entière
    # même là.
    #
    # Quand actif (mois_shift_active) : les recettes (métriques héros, onglet
    # Recettes, sa liste de transactions via /reports/transactions) viennent
    # du mois PRÉCÉDENT (period.prev_*) ; les dépenses restent sur le mois
    # sélectionné. La comparaison "vs période précédente" des recettes doit
    # alors elle aussi remonter d'un cran (comparer le salaire de M-1 à
    # celui de M-2, pas à lui-même) : _resolve_period_from_params(period.
    # prev_params) redonne un ResolvedPeriod complet pour "le mois
    # précédent", dont le PROPRE prev_start/prev_end est ce point de
    # comparaison, et .label sert au libellé composite de la barre de
    # période ("Dépenses : Juillet 2026 | Recettes : Juin 2026").
    mois_shift_active = shift_income and period.period_type == "mois"
    if mois_shift_active:
        shifted_prev_period = _resolve_period_from_params(period.prev_params, today)
        income_period_start, income_period_end = period.prev_start, period.prev_end
        income_period_label = shifted_prev_period.label
        income_compare_start, income_compare_end = shifted_prev_period.prev_start, shifted_prev_period.prev_end
        period_bar_label = f"Dépenses : {period.label} | Recettes : {shifted_prev_period.label}"
    else:
        income_period_start, income_period_end = period.start, period.end
        income_period_label = period.label
        income_compare_start, income_compare_end = period.prev_start, period.prev_end
        period_bar_label = period.label

    income_total = crud.get_income_total(db, income_period_start, income_period_end, parsed_account_id)
    expense_total = crud.get_expense_total(db, period.start, period.end, parsed_account_id)
    result_total = income_total - expense_total
    savings_rate = round(result_total / income_total * 100) if income_total else 0

    # Barres Recettes/Dépenses de l'onglet Balance : proportionnelles l'une
    # à l'autre (le plus grand montant = 100%), pas chacune sur sa propre
    # échelle implicite — corrige le bug où Dépenses affichait toujours
    # 100% de large même très inférieure à Recettes. Reflètent naturellement
    # le décalage Mois (income_total déjà décalé ci-dessus), cohérent avec
    # les autres métriques héros.
    bar_max = max(income_total, expense_total)
    income_bar_pct = round(income_total / bar_max * 100) if bar_max else 0
    expense_bar_pct = round(expense_total / bar_max * 100) if bar_max else 0

    prev_income = crud.get_income_total(db, income_compare_start, income_compare_end, parsed_account_id)
    prev_expense = crud.get_expense_total(db, period.prev_start, period.prev_end, parsed_account_id)
    prev_result = prev_income - prev_expense
    result_change = _percent_change(result_total, prev_result)

    twiga_score = crud.compute_twiga_score(db, period.start, period.end, parsed_account_id)

    # Cashflow 12 mois glissants : TOUJOURS jusqu'au mois en cours (pas
    # jusqu'à la fin de la période sélectionnée), pour que ce graphique reste
    # un repère fixe indépendant de l'onglet actif — comportement demandé
    # explicitement ("stays visible regardless of which tab is active").
    months = trailing_months_ending(today.year, today.month)
    cashflow_months = crud.get_cashflow_months(db, months, parsed_account_id)
    # Onglet "Courses" : même fenêtre glissante de 12 mois que le cashflow
    # (et non la période sélectionnée) — un rapport d'évolution se lit mieux
    # sur une fenêtre fixe.
    receipt_report = crud.get_receipt_family_months(db, months)
    # Graphique : 13 rayons empilés seraient illisibles sur mobile — on garde
    # les 6 plus gros et on agrège le reste en "Autres". Le TABLEAU en
    # dessous, lui, garde le détail complet de tous les rayons.
    sorted_rows = sorted(receipt_report["family_rows"], key=lambda r: r["total"], reverse=True)
    receipt_chart_series = [
        {"label": f"{row['icon']} {row['label']}", "data": [float(v) for v in row["monthly"]]}
        for row in sorted_rows[:6]
    ]
    if len(sorted_rows) > 6:
        others = [
            float(sum((row["monthly"][i] for row in sorted_rows[6:]), Decimal("0.00")))
            for i in range(len(months))
        ]
        receipt_chart_series.append({"label": "Autres", "data": others})
    current_month_start, _ = month_range(today.year, today.month)

    expense_rows = _build_category_rows(
        db, period.start, period.end, period.prev_start, period.prev_end, parsed_account_id, positive=False
    )
    # Donut/liste de l'onglet Recettes : sur income_period_start/end (mois
    # précédent si mois_shift_active, sinon période sélectionnée comme
    # avant) — cohérent avec income_total ci-dessus, sinon le donut
    # afficherait un total qui ne correspond à aucune des catégories listées
    # en-dessous.
    income_rows = _build_category_rows(
        db, income_period_start, income_period_end, income_compare_start, income_compare_end, parsed_account_id, positive=True
    )
    budget_progress = crud.get_budget_progress(db, period.start, period.end, parsed_account_id)
    period_months = max(1, round((period.end - period.start).days / 30.44))
    budget_saved = sum((item["budget"] - item["spent"] for item in budget_progress), Decimal("0.00"))

    # Performance budgétaire (carte héros "🎯 Budget Performance") : part du
    # budget total consommée sur la période, tous budgets confondus (même
    # principe que chaque barre individuelle de l'onglet Budget, agrégé sur
    # l'ensemble). None si aucun budget défini (rien à mesurer, pas 0%).
    # Comparaison en points de pourcentage (pas un %-de-%-change, qui serait
    # trompeur : passer de 40% à 60% consommé n'est pas "+50%").
    total_budgeted = sum((item["budget"] for item in budget_progress), Decimal("0.00"))
    total_spent_budgeted = sum((item["spent"] for item in budget_progress), Decimal("0.00"))
    budget_performance_pct = round(total_spent_budgeted / total_budgeted * 100) if total_budgeted else None

    prev_budget_progress = crud.get_budget_progress(db, period.prev_start, period.prev_end, parsed_account_id)
    prev_total_budgeted = sum((item["budget"] for item in prev_budget_progress), Decimal("0.00"))
    prev_total_spent_budgeted = sum((item["spent"] for item in prev_budget_progress), Decimal("0.00"))
    prev_budget_performance_pct = (
        round(prev_total_spent_budgeted / prev_total_budgeted * 100) if prev_total_budgeted else None
    )
    budget_performance_change = (
        budget_performance_pct - prev_budget_performance_pct
        if budget_performance_pct is not None and prev_budget_performance_pct is not None
        else None
    )

    # Détail mensuel de l'onglet Balance : TOUS les mois civils de la
    # période sélectionnée (mois sans transaction inclus à 0,00 €) —
    # indépendant de cashflow_months (fenêtre glissante fixe de 12 mois
    # ancrée sur aujourd'hui, qui peut ne pas couvrir la période choisie).
    #
    # Le décalage n'a de sens qu'à la granularité mensuelle : restreint à la
    # vue Année (demandé explicitement — comparer trimestre/semestre N-1 à
    # N n'est pas plus sensé que comparer des années entières). En Mois,
    # Trimestre, Semestre ou Personnalisé, le détail mensuel reste toujours
    # sur ses propres mois, même si la case est cochée.
    monthly_shift_active = shift_income and period.period_type == "annee"
    monthly_breakdown = crud.get_period_monthly_breakdown(
        db, period.start, period.end, parsed_account_id, shift_income=monthly_shift_active
    )

    # Moyennes mensuelles (cartes sous le détail mensuel) : SUM / nombre de
    # mois ACTIFS uniquement (recettes ou dépenses non nulles) — un mois
    # totalement vide (avant le premier import, ou sans aucune opération)
    # ne doit pas diluer la moyenne vers 0, demandé explicitement.
    active_months = [m for m in monthly_breakdown if m["income"] or m["expense"]]
    active_month_count = len(active_months)
    if active_month_count:
        monthly_avg_income = sum((m["income"] for m in active_months), Decimal("0.00")) / active_month_count
        monthly_avg_expense = sum((m["expense"] for m in active_months), Decimal("0.00")) / active_month_count
    else:
        monthly_avg_income = Decimal("0.00")
        monthly_avg_expense = Decimal("0.00")
    monthly_avg_net = monthly_avg_income - monthly_avg_expense

    # Patrimoine : historique complet (première transaction -> aujourd'hui)
    # pour Année/Personnalisé, sinon la période sélectionnée en quotidien.
    if period.period_type in ("annee", "personnalise"):
        history_start = crud.get_full_history_start(db) or period.start
        net_worth = crud.get_net_worth_series(db, history_start, min(period.end, today), parsed_account_id, daily=False)
    else:
        net_worth = crud.get_net_worth_series(db, period.start, min(period.end, today), parsed_account_id, daily=True)

    net_worth_points = net_worth["points"]
    net_worth_accounts = net_worth["accounts"]
    if net_worth_points:
        totals = [p["total"] for p in net_worth_points]
        net_worth_delta = net_worth_points[-1]["total"] - net_worth_points[0]["total"]
        net_worth_high = max(totals)
        net_worth_low = min(totals)
    else:
        net_worth_delta = Decimal("0.00")
        net_worth_high = Decimal("0.00")
        net_worth_low = Decimal("0.00")

    accounts = crud.list_accounts(db)
    report_qs = _build_report_qs(period, parsed_account_id, shift_income)

    # Onglet "Le Cap" : volontairement sur le MOIS CIVIL EN COURS plutôt que
    # sur la période sélectionnée ci-dessus (mois/trimestre/semestre/année/
    # personnalisé) — Le Cap est une notion mensuelle (un CapEntry par mois),
    # agréger ses barres pilier sur une période multi-mois n'aurait pas de
    # sens univoque. L'historique, lui, reste indépendant de toute période :
    # c'est un journal complet, pas une vue filtrée.
    cap_today = date.today()
    cap_month_start = date(cap_today.year, cap_today.month, 1)
    cap_entry = crud.get_cap_entry_for_month(db, cap_month_start)
    cap_pillar_bars = None
    if cap_entry is not None:
        cap_actuals = crud.get_pillar_actuals(db, cap_month_start, cap_today, parsed_account_id)
        cap_pillar_bars = [
            {
                "icon": icon,
                "name": name,
                "planned": planned,
                "actual": cap_actuals[key],
                "bar_width": min(round(cap_actuals[key] / planned * 100), 100) if planned else 0,
            }
            for key, icon, name, planned in [
                ("essentiel", "🏠", "Essentiel", cap_entry.planned_essentiel),
                ("choix", "🌟", "Choix", cap_entry.planned_choix),
                ("imprevu", "🆘", "Imprévus", cap_entry.planned_imprevu),
            ]
        ]
    cap_unexpected = crud.get_unexpected_transactions(db, cap_month_start, cap_today)
    cap_unexpected_total = sum((-t.amount for t in cap_unexpected), Decimal("0.00"))
    cap_history = crud.get_cap_entry_history(db)

    return {
        "period": period,
        "report_qs": report_qs,
        "period_type": period.period_type,
        "account_id": parsed_account_id,
        "accounts": accounts,
        "today": today,
        "income_total": income_total,
        "expense_total": expense_total,
        "result_total": result_total,
        "savings_rate": savings_rate,
        "income_change": _percent_change(income_total, prev_income),
        "expense_change": _percent_change(expense_total, prev_expense),
        "result_change": result_change,
        "result_positive": result_total >= 0,
        "prev_result_positive": prev_result >= 0,
        "budget_performance_pct": budget_performance_pct,
        "budget_performance_change": budget_performance_change,
        "twiga_score": twiga_score,
        "cashflow_months": cashflow_months,
        "receipt_report": receipt_report,
        "receipt_chart_series": receipt_chart_series,
        "current_month_start": current_month_start,
        "income_bar_pct": income_bar_pct,
        "expense_bar_pct": expense_bar_pct,
        "expense_rows": expense_rows,
        "income_rows": income_rows,
        "budget_progress": budget_progress,
        "period_months": period_months,
        "budget_saved": budget_saved,
        "monthly_breakdown": monthly_breakdown,
        "monthly_avg_income": monthly_avg_income,
        "monthly_avg_expense": monthly_avg_expense,
        "monthly_avg_net": monthly_avg_net,
        "active_month_count": active_month_count,
        "shift_income": shift_income,
        "monthly_shift_active": monthly_shift_active,
        "mois_shift_active": mois_shift_active,
        "income_period_label": income_period_label,
        "period_bar_label": period_bar_label,
        "net_worth_points": net_worth_points,
        "net_worth_accounts": net_worth_accounts,
        "net_worth_delta": net_worth_delta,
        "net_worth_high": net_worth_high,
        "net_worth_low": net_worth_low,
        "cap_entry": cap_entry,
        "cap_pillar_bars": cap_pillar_bars,
        "cap_unexpected": cap_unexpected,
        "cap_unexpected_total": cap_unexpected_total,
        "cap_history": cap_history,
        "cap_month_label": month_label(cap_today.year, cap_today.month),
    }


@router.get("", response_class=HTMLResponse)
def reports_page(
    request: Request,
    period_type: str | None = None,
    month: int | None = None,
    year: int | None = None,
    quarter: int | None = None,
    semester: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    account_id: str | None = None,
    shift_income: str | None = None,
    db: Session = Depends(get_db),
):
    context = _build_report_context(
        db, period_type, month, year, quarter, semester, date_from, date_to, account_id,
        shift_income=shift_income == "1",
    )
    context["request"] = request
    return templates.TemplateResponse("reports/index.html", context)


@router.get("/content", response_class=HTMLResponse)
def reports_content(
    request: Request,
    period_type: str | None = None,
    month: int | None = None,
    year: int | None = None,
    quarter: int | None = None,
    semester: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    account_id: str | None = None,
    shift_income: str | None = None,
    db: Session = Depends(get_db),
):
    context = _build_report_context(
        db, period_type, month, year, quarter, semester, date_from, date_to, account_id,
        shift_income=shift_income == "1",
    )
    context["request"] = request
    return templates.TemplateResponse("reports/_content.html", context)


@router.get("/transactions", response_class=HTMLResponse)
def report_transactions(
    request: Request,
    period_type: str | None = None,
    month: int | None = None,
    year: int | None = None,
    quarter: int | None = None,
    semester: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    account_id: str | None = None,
    type: str = "expense",
    category_id: str | None = None,
    exact_category_id: str | None = None,
    category_name: str = "",
    page: int = 1,
    shift_income: str | None = None,
    db: Session = Depends(get_db),
):
    # Liste de transactions du rapport (onglet Dépenses/Recettes) : sans
    # catégorie sélectionnée (category_id et exact_category_id absents),
    # montre TOUTES les opérations de la période — pas de "Top 5" tronqué.
    # category_name est fourni par le clic côté template (déjà connu du
    # donut affiché), ça évite une requête DB supplémentaire ici juste pour
    # le titre.
    today = date.today()
    period = _resolve_period(period_type, month, year, quarter, semester, date_from, date_to, today)
    parsed_account_id = _parse_account_id(account_id)
    uncategorized = category_id == "none"
    parsed_category_id = int(category_id) if category_id and not uncategorized else None
    parsed_exact_category_id = int(exact_category_id) if exact_category_id else None
    positive = type == "income"
    page = max(1, page)

    # "Décalage période" (onglet Mois, voir _build_report_context) : la
    # liste de transactions de l'onglet Recettes doit rester cohérente avec
    # son propre donut, déjà décalé au mois précédent — sinon la liste sous
    # le donut afficherait les recettes du mauvais mois. Les dépenses ne
    # sont jamais décalées, ni les autres types de période.
    mois_shift_active = shift_income == "1" and period.period_type == "mois"
    if positive and mois_shift_active:
        query_start, query_end = period.prev_start, period.prev_end
        query_label = _resolve_period_from_params(period.prev_params, today).label
    else:
        query_start, query_end, query_label = period.start, period.end, period.label

    transactions, total = crud.get_report_transactions_page(
        db,
        query_start,
        query_end,
        parsed_account_id,
        positive=positive,
        category_id=parsed_category_id,
        exact_category_id=parsed_exact_category_id,
        uncategorized=uncategorized,
        page=page,
        page_size=_TRANSACTIONS_PAGE_SIZE,
    )
    total_pages = max(1, math.ceil(total / _TRANSACTIONS_PAGE_SIZE))

    context = {
        "request": request,
        "transactions": transactions,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "period_label": query_label,
        "type": type,
        "category_id": category_id or "",
        "exact_category_id": exact_category_id or "",
        "category_name": category_name,
        "report_qs": _build_report_qs(period, parsed_account_id),
    }
    return templates.TemplateResponse("reports/_transactions_list.html", context)


@router.get("/category-trend", response_class=HTMLResponse)
def category_trend(
    request: Request,
    period_type: str | None = None,
    month: int | None = None,
    year: int | None = None,
    quarter: int | None = None,
    semester: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    account_id: str | None = None,
    type: str = "expense",
    category_id: str | None = None,
    category_name: str = "",
    exact: bool = False,
    db: Session = Depends(get_db),
):
    # Évolution d'une catégorie sur les 12 mois glissants se terminant au
    # mois affiché dans le rapport — pas forcément le mois civil en cours :
    # naviguer sur un mois passé avant d'ouvrir "l'évolution" d'une
    # catégorie doit ancrer la fenêtre sur CE mois-là, pas sur aujourd'hui.
    today = date.today()
    period = _resolve_period(period_type, month, year, quarter, semester, date_from, date_to, today)
    parsed_account_id = _parse_account_id(account_id)
    uncategorized = category_id == "none"
    parsed_category_id = int(category_id) if category_id and not uncategorized else None
    positive = type == "income"

    anchor_year, anchor_month = period.end.year, period.end.month
    months = trailing_months_ending(anchor_year, anchor_month, count=12)
    trend = crud.get_category_trend(
        db, parsed_category_id, months, positive=positive, account_id=parsed_account_id, exact=exact
    )
    current_amount = trend[-1]["amount"] if trend else Decimal("0.00")

    # Comparaison "même mois l'an dernier" plutôt que "mois précédent" (déjà
    # visible dans le graphique lui-même) : plus pertinente pour repérer une
    # dérive sur une catégorie saisonnière (chauffage, cadeaux, vacances).
    year_ago_start, year_ago_end = month_range(anchor_year - 1, anchor_month)
    year_ago_amount = crud.get_category_amount_for_period(
        db, year_ago_start, year_ago_end, parsed_category_id, positive=positive, account_id=parsed_account_id, exact=exact
    )
    yoy_change = _percent_change(current_amount, year_ago_amount)

    context = {
        "request": request,
        "category_name": category_name,
        "type": type,
        "trend": trend,
        "current_amount": current_amount,
        "year_ago_amount": year_ago_amount,
        "year_ago_label": month_label(anchor_year - 1, anchor_month),
        "yoy_change": yoy_change,
    }
    return templates.TemplateResponse("reports/_category_trend.html", context)


@router.get("/transactions/export.csv")
def export_report_transactions_csv(
    period_type: str | None = None,
    month: int | None = None,
    year: int | None = None,
    quarter: int | None = None,
    semester: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    account_id: str | None = None,
    type: str = "expense",
    category_id: str | None = None,
    exact_category_id: str | None = None,
    shift_income: str | None = None,
    db: Session = Depends(get_db),
):
    # Export du tableau "Toutes les dépenses/recettes" d'un onglet du
    # rapport, PAS le résumé par catégorie déjà couvert par /export.csv —
    # mêmes filtres (période, compte, décalage recettes) que
    # /reports/transactions, pour exporter exactement ce que l'utilisateur
    # voit dans ce tableau, sans la pagination de l'affichage à l'écran.
    today = date.today()
    period = _resolve_period(period_type, month, year, quarter, semester, date_from, date_to, today)
    parsed_account_id = _parse_account_id(account_id)
    uncategorized = category_id == "none"
    parsed_category_id = int(category_id) if category_id and not uncategorized else None
    parsed_exact_category_id = int(exact_category_id) if exact_category_id else None
    positive = type == "income"

    mois_shift_active = shift_income == "1" and period.period_type == "mois"
    if positive and mois_shift_active:
        query_start, query_end = period.prev_start, period.prev_end
    else:
        query_start, query_end = period.start, period.end

    transactions = crud.get_report_transactions_all(
        db,
        query_start,
        query_end,
        parsed_account_id,
        positive=positive,
        category_id=parsed_category_id,
        exact_category_id=parsed_exact_category_id,
        uncategorized=uncategorized,
    )

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(["Date", "Libellé", "Catégorie", "Compte", "Montant"])
    for tx in transactions:
        category_name = (
            category_display_filter(tx.category.name) if tx.category else "Non catégorisé"
        )
        writer.writerow(
            [tx.date.isoformat(), tx.label or "", category_name, tx.account.name, str(tx.amount)]
        )

    filename = f"twiga-operations-rapport-{type}-{query_start.isoformat()}-{query_end.isoformat()}.csv"
    return Response(
        content="﻿" + buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export.csv")
def export_report_csv(
    period_type: str | None = None,
    month: int | None = None,
    year: int | None = None,
    quarter: int | None = None,
    semester: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    account_id: str | None = None,
    shift_income: str | None = None,
    db: Session = Depends(get_db),
):
    context = _build_report_context(
        db, period_type, month, year, quarter, semester, date_from, date_to, account_id,
        shift_income=shift_income == "1",
    )
    period = context["period"]

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(["Rapport Twiga", context["period_bar_label"]])
    writer.writerow([])
    writer.writerow(["Recettes", format_amount(context["income_total"])])
    writer.writerow(["Dépenses", format_amount(context["expense_total"])])
    writer.writerow(["Résultat", format_amount(context["result_total"])])
    writer.writerow(["Taux d'épargne", f"{context['savings_rate']} %"])
    writer.writerow(["Score Twiga", f"{context['twiga_score']['score']} / 100"])
    writer.writerow([])
    writer.writerow(["Dépenses par catégorie", "Montant", "% du total", "Évolution vs période précédente"])
    for row in context["expense_rows"]:
        change = f"{row['change']} %" if row["change"] is not None else ""
        writer.writerow([row["name"], format_amount(row["amount"]), f"{row['percent_of_total']} %", change])
    writer.writerow([])
    writer.writerow(["Recettes par catégorie", "Montant", "% du total", "Évolution vs période précédente"])
    for row in context["income_rows"]:
        change = f"{row['change']} %" if row["change"] is not None else ""
        writer.writerow([row["name"], format_amount(row["amount"]), f"{row['percent_of_total']} %", change])

    filename = f"twiga-rapport-{period.start.isoformat()}-{period.end.isoformat()}.csv"
    return Response(
        content="﻿" + buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
