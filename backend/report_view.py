"""What the other way's Rapports screen needs on top of the figures of the report.

The Classic screen is seven tabs over one big context (reports._build_report_context).
The other way asks nine questions over the same figures ("Où est parti l'argent ?",
"Les budgets ont-ils tenu ?"...), each answered by a sentence (backend/answers.py,
report_answers) and a panel. This module turns the figures of the context into
what those nine panels and sentences print: the shares with their budget verdict,
the twelve months as columns, the comparison with the period before, the parts
of the Twiga score and the reason of each.

Nothing here reads a request or writes a row.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from backend import answers, crud
from backend.dates import month_label
from backend.i18n import current_language
from backend.i18n import gettext as _t

ZERO = Decimal("0.00")


def _starts_with_vowel(text: str) -> bool:
    return text[:1].lower() in "aeiouyhàâäéèêëîïôöùûü"


def period_words(period, today: date) -> dict:
    """The period as a sentence wants it: "de septembre 2026", "du T3 2026"..."""
    label = period.label
    english = current_language() == "en"
    if period.period_type == "mois":
        month = label if english else label.lower()
        des = (
            _t("de %(label)s") % {"label": month}
            if english or not _starts_with_vowel(month)
            else _t("d'%(label)s") % {"label": month}
        )
        previous_label = month_label(period.prev_start.year, period.prev_start.month)
        return {
            "des": des,
            "plab": month,
            "in_period": _t("en %(label)s") % {"label": month},
            "prev_label": previous_label if english else previous_label.lower(),
            "cur_label": label,
            "start_label": month,
            "unfinished": period.end >= today,
        }
    if period.period_type in ("trimestre", "semestre"):
        return {
            "des": _t("du %(label)s") % {"label": label},
            "plab": _t("le %(label)s") % {"label": label},
            "in_period": _t("sur le %(label)s") % {"label": label},
            "prev_label": _t("la période précédente"),
            "cur_label": _t("Le %(label)s") % {"label": label},
            "start_label": _t("le début du %(label)s") % {"label": label},
            "unfinished": period.end >= today,
        }
    if period.period_type == "annee":
        return {
            "des": _t("de l'année %(label)s") % {"label": label},
            "plab": _t("l'année %(label)s") % {"label": label},
            "in_period": _t("sur l'année %(label)s") % {"label": label},
            "prev_label": _t("l'année %(year)s") % {"year": period.year - 1},
            "cur_label": _t("L'année %(label)s") % {"label": label},
            "start_label": _t("le début de l'année %(label)s") % {"label": label},
            "unfinished": period.end >= today,
        }
    return {
        "des": _t("de la période"),
        "plab": _t("la période"),
        "in_period": _t("sur la période"),
        "prev_label": _t("la période précédente"),
        "cur_label": _t("La période"),
        "start_label": _t("le début de la période"),
        "unfinished": period.end >= today,
    }


def _share_rows(rows: list[dict], budget_by_category: dict[int, dict], positive: bool) -> list[dict]:
    """The categories of a question with the verdict of their budget, when they have one."""
    shares = []
    for row in rows:
        budget = budget_by_category.get(row["category_id"]) if row["category_id"] is not None and not positive else None
        entry = {**row, "budget": None}
        if budget is not None:
            state = answers.verdict(budget["percentage"])
            entry["budget"] = {
                "word": _t("Dans le budget") if state.key == "ok" else state.word,
                "text": state.text,
                "percent": round(budget["percentage"]),
                "amount": budget["budget"],
            }
        elif row["category_id"] is None:
            entry["pending"] = True
        shares.append(entry)
    return shares


def build_other_way_context(db: Session, context: dict, today: date) -> dict:
    """The extras of the other way's Rapports, from the context of the report."""
    period = context["period"]
    words = period_words(period, today)
    budgets = {item["category"].id: item for item in context["budget_progress"]}
    expense_rows = _share_rows(context["expense_rows"], budgets, positive=False)
    income_rows = _share_rows(context["income_rows"], budgets, positive=True)

    # The twelve months: the columns of "Est-ce que le foyer épargne ?".
    months = context["cashflow_months"]
    twelve_result = sum((m["net"] for m in months), ZERO)
    twelve_income = sum((m["income"] for m in months), ZERO)
    biggest = max((abs(m["net"]) for m in months), default=ZERO) or Decimal("1")
    columns = []
    cumulative, running = [], ZERO
    for month in months:
        running += month["net"]
        cumulative.append(running)
        columns.append(
            {
                **month,
                "height": round(float(abs(month["net"]) / biggest * 100), 1),
                "rate": round(month["net"] / month["income"] * 100) if month["income"] else None,
            }
        )
    cumulative_path = _polyline([float(v) for v in cumulative])

    # Budgets.
    progress = context["budget_progress"]
    held = sum(1 for item in progress if item["percentage"] <= 100)
    budget_lines = [{**item, "verdict": answers.verdict(item["percentage"])} for item in progress]
    budget_view = {
        "has": bool(progress),
        "held": held,
        "count": len(progress),
        "spent": sum((item["spent"] for item in progress), ZERO),
        "budget": sum((item["budget"] for item in progress), ZERO),
        "saved": context["budget_saved"],
    }

    # Patrimoine.
    points = context["net_worth_points"]
    account = next((a for a in context["accounts"] if a.id == context["account_id"]), None)
    patrimoine = {
        "ok": bool(points),
        "last": points[-1]["total"] if points else ZERO,
        "delta": context["net_worth_delta"],
        "high": context["net_worth_high"],
        "low": context["net_worth_low"],
        "account": account.name if account else None,
    }
    balances = [(a, b) for a, b in crud.get_account_balances(db) if account is None or a.id == account.id]

    # Le Cap.
    entry = context["cap_entry"]
    pillar_bars = []
    for bar in context["cap_pillar_bars"] or []:
        ratio = (bar["actual"] / bar["planned"] * 100) if bar["planned"] else ZERO
        pillar_bars.append({**bar, "ratio": ratio, "verdict": answers.verdict(ratio)})
    worst = max(pillar_bars, key=lambda b: b["ratio"], default=None)
    cap_view = {
        "ok": entry is not None,
        "month": context["cap_month_label"].lower() if current_language() != "en" else context["cap_month_label"],
        "all_ok": all(b["ratio"] <= 100 for b in pillar_bars),
        "worst": worst["name"] if worst else "",
        "quote": entry.intention if entry is not None and entry.intention else "",
        "rate": context["savings_rate"],
        "bars": pillar_bars,
    }

    # Les courses.
    receipts = context["receipt_report"]
    families = receipts["family_rows"]
    shop_view = {
        "empty": not families,
        "total": abs(receipts["grand_total"]) if families else ZERO,
        "top": families and sorted(families, key=lambda r: abs(r["total"]), reverse=True)[0]["label"].lower() or "",
        "max_month": max((abs(v) for v in receipts["monthly_totals"]), default=ZERO) or Decimal("1"),
        "max_family": max((abs(r["total"]) for r in families), default=ZERO) or Decimal("1"),
    }

    # Qu'est-ce qui a changé ?
    prev_income, prev_expense = context["prev_income"], context["prev_expense"]
    has_reference = bool(prev_expense) or bool(prev_income)
    comparison = {
        "ref": has_reference and bool(prev_expense),
        "dep_delta": context["expense_total"] - prev_expense,
        "rec_delta": context["income_total"] - prev_income,
        "prev_label": words["prev_label"],
        "cur_label": words["cur_label"],
        "unfinished": words["unfinished"] and period.period_type == "mois",
        "pending": context["pending_expense_total"],
        "rows": [
            {"label": _t("Recettes"), "cur": context["income_total"], "prev": prev_income, "change": context["income_change"], "up_is_good": True},
            {"label": _t("Dépenses"), "cur": context["expense_total"], "prev": prev_expense, "change": context["expense_change"], "up_is_good": False},
            {
                "label": _t("Résultat net"),
                "cur": max(context["result_total"], ZERO),
                "prev": max(prev_income - prev_expense, ZERO),
                "change": context["result_change"],
                "up_is_good": True,
            },
        ],
    }
    for row in comparison["rows"]:
        top = max(row["cur"], row["prev"], Decimal("1"))
        row["cur_width"] = max(float(row["cur"] / top * 100), 1.0)
        row["prev_width"] = max(float(row["prev"] / top * 100), 1.0)

    # Le score Twiga.
    score = context["twiga_score"]
    used = round(budget_view["spent"] / budget_view["budget"] * 100) if budget_view["budget"] else None
    pending_count = crud.count_pending_transactions(db, context["account_id"])
    score_parts = [
        {
            "label": _t("Budgets"),
            "points": score["budget_points"],
            "max": 40,
            "why": _t("Tu as dépensé %(used)s %% de tes budgets %(des)s.") % {"used": used, "des": words["des"]}
            if used is not None
            else _t("Aucun budget défini : Twiga ne peut pas les noter."),
        },
        {
            "label": _t("Résultat"),
            "points": score["result_points"],
            "max": 30,
            "why": _t("Taux d'épargne %(des)s : %(rate)s %%.") % {"des": words["des"], "rate": context["savings_rate"]},
        },
        {
            "label": _t("Catégorisation"),
            "points": score["categorized_points"],
            "max": 20,
            "why": _t("%(n)s opérations à ranger dans La Savane (%(amount)s).")
            % {"n": pending_count, "amount": answers.format_amount(context["pending_expense_total"])}
            if pending_count
            else _t("Tout est rangé."),
        },
        {
            "label": _t("Projets"),
            "points": score["project_points"],
            "max": 10,
            "why": _t("Les projets en cours avancent à leur rythme."),
        },
    ]

    has_data = bool(
        context["income_total"] != 0 or context["expense_total"] != 0 or progress or expense_rows or income_rows
    )
    shifted_label = None
    if context["mois_shift_active"]:
        shifted_label = context["income_period_label"].lower() if current_language() != "en" else context["income_period_label"]
    sentences = answers.report_answers(
        has_data=has_data,
        des=words["des"],
        plab=words["plab"],
        period_start_label=words["start_label"],
        in_period=words["in_period"],
        expense_total=context["expense_total"],
        expense_rows=[{"name": r["name"], "amount": r["amount"], "percent": r["percent_of_total"]} for r in expense_rows],
        pending_expense=context["pending_expense_total"],
        income_total=context["income_total"],
        income_rows=[{"name": r["name"], "amount": r["amount"], "percent": r["percent_of_total"]} for r in income_rows],
        shifted_income_label=shifted_label,
        result=context["result_total"],
        twelve={"result": twelve_result, "income": twelve_income, "avg": twelve_result / 12},
        budgets=budget_view,
        patrimoine=patrimoine,
        cap=cap_view,
        shop=shop_view,
        change=comparison,
        score={"score": score["score"], "message": score["message"]},
    )
    titles = {
        "dep": _t("Dépenses %(des)s par catégorie") % {"des": words["des"]},
        "rec": _t("Recettes %(des)s par catégorie") % {"des": words["des"]},
        "bal": _t("Ce qui reste chaque mois, de %(first)s à %(last)s")
        % {"first": months[0]["label"].lower(), "last": months[-1]["label"].lower()}
        if months
        else _t("Ce qui reste chaque mois"),
        "bud": _t("Budgets %(des)s") % {"des": words["des"]},
        "pat": _t("Valeur nette %(des)s") % {"des": words["des"]},
        "cap": _t("Le Cap de %(month)s") % {"month": cap_view["month"]},
        "shop": _t("Courses par rayon — 12 derniers mois"),
        "chg": _t("%(cur)s comparé à %(prev)s") % {"cur": words["cur_label"], "prev": words["prev_label"]},
        "score": _t("Score Twiga"),
    }
    return {
        "words": words,
        "has_data": has_data,
        "expense_share_rows": expense_rows,
        "income_share_rows": income_rows,
        "columns": columns,
        "twelve_result": twelve_result,
        "twelve_average": twelve_result / 12,
        "cumulative_path": cumulative_path,
        "cumulative_total": cumulative[-1] if cumulative else ZERO,
        "budget_view": budget_view,
        "budget_lines": budget_lines,
        "patrimoine": patrimoine,
        "account_balances": balances,
        "accounts_total": sum((b for _, b in balances), ZERO),
        "cap_view": cap_view,
        "shop_view": shop_view,
        "comparison": comparison,
        "score_parts": score_parts,
        "pending_count": pending_count,
        "report_sentences": sentences,
        "report_titles": titles,
        "report_questions": [(key, str(label)) for key, label in answers.REPORT_QUESTIONS],
    }


def _polyline(values: list[float], width: int = 300, height: int = 80) -> str:
    """An SVG path through the values, drawn in a width x height box (min at the bottom)."""
    if not values:
        return ""
    low, high = min(0.0, min(values)), max(0.0, max(values))
    span = (high - low) or 1.0
    points = []
    for index, value in enumerate(values):
        x = (index + 0.5) * width / len(values)
        y = height - (value - low) / span * (height - 8) - 4
        points.append(f"{'M' if index == 0 else 'L'}{x:.1f} {y:.1f}")
    return "".join(points)
