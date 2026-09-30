import csv
import io
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.models import (
    Account,
    Budget,
    BudgetMonth,
    CapEntry,
    CapSettings,
    Category,
    PaymentMethod,
    PendingCheck,
    Project,
    ProjectMovement,
    ReceiptItem,
    RecurringPattern,
    Rule,
    RuleSuggestion,
    Transaction,
)


def _serialize_account(account: Account) -> dict:
    return {
        "id": account.id,
        "name": account.name,
        "type": account.type,
        "balance": str(account.balance),
        "color": account.color,
        "notes": account.notes,
        "currency": account.currency,
    }


def _serialize_payment_method(payment_method: PaymentMethod) -> dict:
    return {
        "id": payment_method.id,
        "name": payment_method.name,
        "icon": payment_method.icon,
        "is_default": payment_method.is_default,
        "display_order": payment_method.display_order,
    }


def _serialize_category(category: Category) -> dict:
    return {
        "id": category.id,
        "name": category.name,
        "icon": category.icon,
        "parent_id": category.parent_id,
        "sort_order": category.sort_order,
        "pillar": category.pillar,
        "excluded_from_budget": category.excluded_from_budget,
    }


def _serialize_transaction(transaction: Transaction) -> dict:
    return {
        "id": transaction.id,
        "date": transaction.date.isoformat(),
        "label": transaction.label,
        "raw_label": transaction.raw_label,
        "amount": str(transaction.amount),
        "account_id": transaction.account_id,
        "category_id": transaction.category_id,
        "validated": transaction.validated,
        "is_transfer": transaction.is_transfer,
        "skipped_at": transaction.skipped_at.isoformat() if transaction.skipped_at else None,
        "backlog_rejected_at": (
            transaction.backlog_rejected_at.isoformat() if transaction.backlog_rejected_at else None
        ),
        "payment_method": transaction.payment_method,
        "note": transaction.note,
        "is_unexpected": transaction.is_unexpected,
    }


def _serialize_receipt_item(item: ReceiptItem) -> dict:
    return {
        "id": item.id,
        "transaction_id": item.transaction_id,
        "label": item.label,
        "amount": str(item.amount),
        "family": item.family,
        "sort_order": item.sort_order,
    }


def _serialize_budget(budget: Budget) -> dict:
    return {
        "id": budget.id,
        "category_id": budget.category_id,
        "month": budget.month.isoformat(),
        "amount": str(budget.amount),
    }


def _serialize_budget_month(entry: BudgetMonth) -> dict:
    return {
        "id": entry.id,
        "month": entry.month.isoformat(),
        "savings_withdrawal": str(entry.savings_withdrawal),
    }


def _serialize_rule_suggestion(row: RuleSuggestion) -> dict:
    return {
        "id": row.id,
        "keyword": row.keyword,
        "category_id": row.category_id,
        "occurrences": row.occurrences,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "dismissed": row.dismissed,
    }


def _serialize_cap_settings(row: CapSettings) -> dict:
    return {
        "id": row.id,
        "income_source": row.income_source,
        "income_account_id": row.income_account_id,
        "income_fixed_amount": (
            str(row.income_fixed_amount) if row.income_fixed_amount is not None else None
        ),
    }


def _serialize_project(project: Project) -> dict:
    return {
        "id": project.id,
        "name": project.name,
        "target_amount": str(project.target_amount),
        "target_date": project.target_date.isoformat(),
        "current_amount": str(project.current_amount),
    }


def _serialize_project_movement(movement: ProjectMovement) -> dict:
    return {
        "id": movement.id,
        "project_id": movement.project_id,
        "date": movement.date.isoformat(),
        "amount": str(movement.amount),
        "note": movement.note,
    }


def _serialize_rule(rule: Rule) -> dict:
    return {
        "id": rule.id,
        "keyword": rule.keyword,
        "category_id": rule.category_id,
        "payment_method": rule.payment_method,
    }


def _serialize_cap_entry(entry: CapEntry) -> dict:
    return {
        "id": entry.id,
        "month": entry.month.isoformat(),
        "planned_income": str(entry.planned_income),
        "planned_essentiel": str(entry.planned_essentiel),
        "planned_choix": str(entry.planned_choix),
        "planned_imprevu": str(entry.planned_imprevu),
        "intention": entry.intention,
        "reflection_unexpected": entry.reflection_unexpected,
        "reflection_regret": entry.reflection_regret,
        "reflection_proud": entry.reflection_proud,
        "reflection_worked_well": entry.reflection_worked_well,
        "created_at": entry.created_at.isoformat(),
    }


def _serialize_recurring_pattern(pattern: RecurringPattern) -> dict:
    return {
        "id": pattern.id,
        "label_pattern": pattern.label_pattern,
        "amount": str(pattern.amount),
        "frequency_days": pattern.frequency_days,
        "status": pattern.status,
        "category_id": pattern.category_id,
    }


def _serialize_pending_check(check: PendingCheck) -> dict:
    return {
        "id": check.id,
        "check_number": check.check_number,
        "payment_method": check.payment_method,
        "amount": str(check.amount),
        "issued_date": check.issued_date.isoformat(),
        "recipient": check.recipient,
        "category_id": check.category_id,
        "account_id": check.account_id,
        "matched_transaction_id": check.matched_transaction_id,
        "matched_at": check.matched_at.isoformat() if check.matched_at else None,
    }


# Ordre de dépendance, réutilisé tel quel par restore.py : comptes/moyens de
# paiement/catégories avant tout ce qui les référence, transactions avant
# leurs receipt_items, projets avant leurs mouvements. Les comptes
# utilisateurs (User) et l'état applicatif (AppState, secret de session)
# sont volontairement exclus de la sauvegarde/restauration — une migration
# dev -> prod doit garder les identifiants et le secret de session propres à
# chaque environnement plutôt que d'écraser ceux de la prod.
def build_full_export(db: Session) -> dict:
    return {
        "exported_at": datetime.now().isoformat(),
        "accounts": [
            _serialize_account(a) for a in db.execute(select(Account).order_by(Account.id)).scalars().all()
        ],
        "payment_methods": [
            _serialize_payment_method(p)
            for p in db.execute(select(PaymentMethod).order_by(PaymentMethod.id)).scalars().all()
        ],
        "categories": [
            _serialize_category(c)
            for c in db.execute(select(Category).order_by(Category.id)).scalars().all()
        ],
        "transactions": [
            _serialize_transaction(t)
            for t in db.execute(select(Transaction).order_by(Transaction.id)).scalars().all()
        ],
        "receipt_items": [
            _serialize_receipt_item(i)
            for i in db.execute(select(ReceiptItem).order_by(ReceiptItem.id)).scalars().all()
        ],
        "budgets": [
            _serialize_budget(b) for b in db.execute(select(Budget).order_by(Budget.id)).scalars().all()
        ],
        "budget_months": [
            _serialize_budget_month(e)
            for e in db.execute(select(BudgetMonth).order_by(BudgetMonth.id)).scalars().all()
        ],
        "cap_settings": [
            _serialize_cap_settings(r)
            for r in db.execute(select(CapSettings).order_by(CapSettings.id)).scalars().all()
        ],
        "projects": [
            _serialize_project(p) for p in db.execute(select(Project).order_by(Project.id)).scalars().all()
        ],
        "project_movements": [
            _serialize_project_movement(m)
            for m in db.execute(select(ProjectMovement).order_by(ProjectMovement.id)).scalars().all()
        ],
        "cap_entries": [
            _serialize_cap_entry(e)
            for e in db.execute(select(CapEntry).order_by(CapEntry.id)).scalars().all()
        ],
        "rules": [_serialize_rule(r) for r in db.execute(select(Rule).order_by(Rule.id)).scalars().all()],
        "rule_suggestions": [
            _serialize_rule_suggestion(r)
            for r in db.execute(select(RuleSuggestion).order_by(RuleSuggestion.id)).scalars().all()
        ],
        "recurring_patterns": [
            _serialize_recurring_pattern(p)
            for p in db.execute(select(RecurringPattern).order_by(RecurringPattern.id)).scalars().all()
        ],
        "pending_checks": [
            _serialize_pending_check(c)
            for c in db.execute(select(PendingCheck).order_by(PendingCheck.id)).scalars().all()
        ],
    }


def _category_and_subcategory_names(category: Category | None) -> tuple[str, str]:
    if category is None:
        return "", ""
    if category.parent is not None:
        return category.parent.name, category.name
    return category.name, ""


def build_transactions_csv(db: Session) -> str:
    stmt = (
        select(Transaction)
        .options(
            selectinload(Transaction.account),
            selectinload(Transaction.category).selectinload(Category.parent),
        )
        .order_by(Transaction.date, Transaction.id)
    )
    transactions = db.execute(stmt).scalars().all()

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(
        ["date", "libelle_simplifie", "libelle_brut", "montant", "categorie", "sous_categorie", "compte"]
    )
    for transaction in transactions:
        category_name, subcategory_name = _category_and_subcategory_names(transaction.category)
        writer.writerow(
            [
                transaction.date.isoformat(),
                transaction.label,
                transaction.raw_label,
                str(transaction.amount),
                category_name,
                subcategory_name,
                transaction.account.name,
            ]
        )
    return buffer.getvalue()
