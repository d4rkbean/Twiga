from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from backend import crud
from backend.database import get_db
from backend.dates import month_label, month_names, month_range
from backend.templating import templates
from imports.common import ImportParseError, parse_decimal_amount

router = APIRouter(prefix="/budgets", tags=["budgets"])


def _parse_budget_amount(raw: str | None) -> Decimal:
    if not raw:
        return Decimal("0.00")
    try:
        return abs(parse_decimal_amount(raw))
    except ImportParseError:
        return Decimal("0.00")


def _build_context(db: Session, month: int, year: int) -> dict:
    month_start, _ = month_range(year, month)
    categories = crud.get_budgetable_categories(db)
    budgets = crud.get_budgets_for_month(db, month_start)

    # Ressources du mois, référence de la répartition : chaque montant saisi
    # s'accompagne d'un % de CE total (voir budgets/_content.html) plutôt que
    # d'un montant isolé sans repère.
    #
    # C'est le MÊME nombre que celui du rituel, et ce n'est pas un détail :
    # cette page et Le Cap éditent le même plan. Tant qu'elle affichait « la
    # recette du mois précédent » alors que le rituel affichait le montant
    # engagé, les deux écrans proposaient deux bases différentes pour
    # répartir les mêmes enveloppes — et sur un foyer alimenté par virement,
    # la recette est de toute façon le mauvais repère (voir crud.INCOME_SOURCES).
    #
    # Priorité au cap du mois s'il est fixé : c'est la décision prise. Sinon
    # on retombe sur la proposition du réglage, comme le ferait le rituel.
    cap_entry = crud.get_cap_entry_for_month(db, month_start)
    if cap_entry is not None:
        month_resources = cap_entry.planned_income
        resources_from_cap = True
    else:
        month_resources = crud.get_income_prefill(db, month_start)
        resources_from_cap = False

    # Toujours le mois CIVIL en cours, indépendamment du mois consulté/édité
    # ci-dessus dans le formulaire : ce statut doit rester visible quel que
    # soit le mois affiché, pour remplacer la bannière d'alertes de La
    # Savane une fois ses alertes masquées.
    today = date.today()
    current_month_start, current_month_end = month_range(today.year, today.month)
    current_month_status = crud.get_budget_progress(db, current_month_start, current_month_end)

    return {
        "month": month,
        "year": year,
        "period_label": month_label(year, month),
        "categories": categories,
        "budgets": budgets,
        "current_month_status": current_month_status,
        "current_month_label": month_label(today.year, today.month),
        "month_resources": month_resources,
        "resources_from_cap": resources_from_cap,
        "savings_withdrawal": crud.get_savings_withdrawal(db, month_start),
    }


@router.get("", response_class=HTMLResponse)
def budgets_page(
    request: Request,
    month: int | None = None,
    year: int | None = None,
    db: Session = Depends(get_db),
):
    today = date.today()
    month = month if month and 1 <= month <= 12 else today.month
    year = year or today.year

    years = sorted(set(range(today.year - 1, today.year + 2)) | set(crud.get_transaction_years(db)), reverse=True)
    if year not in years:
        years = sorted(set(years) | {year}, reverse=True)

    context = {
        "request": request,
        "years": years,
        "month_options": list(enumerate(month_names(), start=1)),
        **_build_context(db, month, year),
    }
    return templates.TemplateResponse("budgets/index.html", context)


@router.get("/content", response_class=HTMLResponse)
def budgets_content(request: Request, month: int, year: int, db: Session = Depends(get_db)):
    context = {"request": request, **_build_context(db, month, year)}
    return templates.TemplateResponse("budgets/_content.html", context)


@router.post("/save", response_class=HTMLResponse)
async def save_budgets(request: Request, month: int, year: int, db: Session = Depends(get_db)):
    form = await request.form()
    month_start, _ = month_range(year, month)
    categories = crud.get_budgetable_categories(db)

    amounts = {
        category.id: _parse_budget_amount(form.get(f"amount_{category.id}"))
        for category in categories
    }
    crud.save_budgets(db, month_start, amounts)
    # Le champ n'est rendu que s'il y a une recette au mois précédent (voir
    # budgets/_content.html) : absent du formulaire, on laisse la valeur
    # stockée intacte plutôt que de l'effacer silencieusement.
    if "savings_withdrawal" in form:
        crud.save_savings_withdrawal(
            db, month_start, _parse_budget_amount(form.get("savings_withdrawal"))
        )

    context = {"request": request, **_build_context(db, month, year)}
    return templates.TemplateResponse("budgets/_content.html", context)


@router.post("/copy-previous", response_class=HTMLResponse)
def copy_previous(request: Request, month: int, year: int, db: Session = Depends(get_db)):
    month_start, _ = month_range(year, month)
    crud.copy_budgets_from_previous_month(db, month_start)

    context = {"request": request, **_build_context(db, month, year)}
    return templates.TemplateResponse("budgets/_content.html", context)
