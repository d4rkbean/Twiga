"""Restauration depuis une sauvegarde JSON (l'inverse de export.py).

Conflits gérés par UPSERT sur l'id exporté : une ligne déjà présente (même
id) est mise à jour, une ligne absente est créée. Choisi plutôt qu'un simple
"ignorer les doublons" car le cas d'usage visé — migrer dev vers prod — veut
que la base cible reflète fidèlement l'export, pas seulement compléter ce
qui manque.

Les id sont préservés tels quels (pas de ré-assignation) pour garder les
relations (compte, catégorie, projet...) intactes sans avoir à retracer un
graphe de correspondance ancien id -> nouvel id. Conséquence directe : les
séquences Postgres des colonnes id auto-incrémentées ne suivent pas
automatiquement des id insérés explicitement, et doivent être recalées
après coup (_reset_sequence) sous peine de collision au prochain insert
normal fait par l'application après la restauration.
"""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import text
from sqlalchemy.orm import Session

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


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _parse_decimal(value) -> Decimal:
    if value is None:
        return Decimal("0.00")
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return Decimal("0.00")


def _account_fields(row: dict) -> dict:
    return {
        "name": row["name"],
        "type": row["type"],
        "balance": _parse_decimal(row.get("balance")),
        "color": row.get("color"),
        "notes": row.get("notes"),
        "currency": row.get("currency", "EUR"),
    }


def _payment_method_fields(row: dict) -> dict:
    return {
        "name": row["name"],
        "icon": row["icon"],
        "is_default": row.get("is_default", False),
        "display_order": row.get("display_order", 0),
    }


def _category_fields(row: dict) -> dict:
    return {
        "name": row["name"],
        "icon": row.get("icon"),
        "parent_id": row.get("parent_id"),
        "sort_order": row.get("sort_order", 0),
        "pillar": row.get("pillar"),
        "excluded_from_budget": row.get("excluded_from_budget", False),
    }


def _transaction_fields(row: dict) -> dict:
    return {
        "date": _parse_date(row["date"]),
        "label": row["label"],
        "raw_label": row["raw_label"],
        "amount": _parse_decimal(row.get("amount")),
        "account_id": row["account_id"],
        "category_id": row.get("category_id"),
        "validated": row.get("validated", False),
        "is_transfer": row.get("is_transfer", False),
        "skipped_at": _parse_datetime(row.get("skipped_at")),
        # Absents des sauvegardes antérieures à leur ajout au schéma : .get()
        # avec None par défaut plutôt que row[...] pour rester compatible
        # avec un export plus ancien.
        "backlog_rejected_at": _parse_datetime(row.get("backlog_rejected_at")),
        "payment_method": row.get("payment_method"),
        "note": row.get("note"),
        "is_unexpected": row.get("is_unexpected", False),
    }


def _receipt_item_fields(row: dict) -> dict:
    return {
        "transaction_id": row["transaction_id"],
        "label": row["label"],
        "amount": _parse_decimal(row.get("amount")),
        "family": row.get("family"),
        "sort_order": row.get("sort_order", 0),
    }


def _budget_fields(row: dict) -> dict:
    return {
        "category_id": row["category_id"],
        "month": _parse_date(row["month"]),
        "amount": _parse_decimal(row.get("amount")),
    }


def _rule_suggestion_fields(row: dict) -> dict:
    return {
        "keyword": row["keyword"],
        "category_id": row["category_id"],
        "occurrences": row.get("occurrences") or 1,
        "created_at": _parse_datetime(row.get("created_at")),
        "dismissed": bool(row.get("dismissed")),
    }


def _cap_settings_fields(row: dict) -> dict:
    return {
        "income_source": row.get("income_source") or "recettes_precedent",
        "income_account_id": row.get("income_account_id"),
        "income_fixed_amount": _parse_decimal(row.get("income_fixed_amount"))
        if row.get("income_fixed_amount") is not None
        else None,
    }


def _budget_month_fields(row: dict) -> dict:
    return {
        "month": _parse_date(row["month"]),
        "savings_withdrawal": _parse_decimal(row.get("savings_withdrawal")),
    }


def _project_fields(row: dict) -> dict:
    return {
        "name": row["name"],
        "target_amount": _parse_decimal(row.get("target_amount")),
        "target_date": _parse_date(row["target_date"]),
        "current_amount": _parse_decimal(row.get("current_amount")),
    }


def _project_movement_fields(row: dict) -> dict:
    return {
        "project_id": row["project_id"],
        "date": _parse_date(row["date"]),
        "amount": _parse_decimal(row.get("amount")),
        "note": row.get("note"),
    }


def _cap_entry_fields(row: dict) -> dict:
    return {
        "month": _parse_date(row["month"]),
        "planned_income": _parse_decimal(row.get("planned_income")),
        "planned_essentiel": _parse_decimal(row.get("planned_essentiel")),
        "planned_choix": _parse_decimal(row.get("planned_choix")),
        "planned_imprevu": _parse_decimal(row.get("planned_imprevu")),
        "intention": row.get("intention"),
        "reflection_unexpected": row.get("reflection_unexpected"),
        "reflection_regret": row.get("reflection_regret"),
        "reflection_proud": row.get("reflection_proud"),
        "reflection_worked_well": row.get("reflection_worked_well"),
        "created_at": _parse_datetime(row.get("created_at")) or datetime.utcnow(),
    }


def _rule_fields(row: dict) -> dict:
    return {
        "keyword": row["keyword"],
        "category_id": row["category_id"],
        "payment_method": row.get("payment_method"),
    }


def _recurring_pattern_fields(row: dict) -> dict:
    return {
        "label_pattern": row["label_pattern"],
        "amount": _parse_decimal(row.get("amount")),
        "frequency_days": row["frequency_days"],
        "status": row["status"],
        "category_id": row.get("category_id"),
    }


def _pending_check_fields(row: dict) -> dict:
    return {
        "check_number": row.get("check_number"),
        "payment_method": row.get("payment_method"),
        "amount": _parse_decimal(row.get("amount")),
        "issued_date": _parse_date(row["issued_date"]),
        "recipient": row.get("recipient"),
        "category_id": row["category_id"],
        "account_id": row["account_id"],
        "matched_transaction_id": row.get("matched_transaction_id"),
        "matched_at": _parse_datetime(row.get("matched_at")),
    }


# Ordre de dépendance : comptes/moyens de paiement/catégories avant tout ce
# qui les référence, transactions avant leurs receipt_items, projets avant
# leurs mouvements, transactions avant les chèques rapprochés — le même
# ordre que build_full_export produit ses clés, qui est déjà l'ordre de
# dépendance correct. Users et AppState volontairement absents (voir
# commentaire dans export.py).
_SECTIONS: list[tuple[str, type, callable]] = [
    ("accounts", Account, _account_fields),
    ("payment_methods", PaymentMethod, _payment_method_fields),
    ("categories", Category, _category_fields),
    ("transactions", Transaction, _transaction_fields),
    ("receipt_items", ReceiptItem, _receipt_item_fields),
    ("budgets", Budget, _budget_fields),
    ("budget_months", BudgetMonth, _budget_month_fields),
    # après accounts : income_account_id est une clé étrangère vers accounts
    ("cap_settings", CapSettings, _cap_settings_fields),
    ("projects", Project, _project_fields),
    ("project_movements", ProjectMovement, _project_movement_fields),
    ("cap_entries", CapEntry, _cap_entry_fields),
    ("rules", Rule, _rule_fields),
    # après categories, dont rule_suggestions référence une clé
    ("rule_suggestions", RuleSuggestion, _rule_suggestion_fields),
    ("recurring_patterns", RecurringPattern, _recurring_pattern_fields),
    ("pending_checks", PendingCheck, _pending_check_fields),
]


def _upsert(db: Session, model: type, row_id: int, values: dict) -> None:
    existing = db.get(model, row_id)
    if existing is not None:
        for key, value in values.items():
            setattr(existing, key, value)
    else:
        db.add(model(id=row_id, **values))


def _reset_sequence(db: Session, table_name: str) -> None:
    db.execute(
        text(
            f"SELECT setval(pg_get_serial_sequence('{table_name}', 'id'), "
            f"COALESCE((SELECT MAX(id) FROM {table_name}), 1))"
        )
    )


def restore_from_export(db: Session, data: dict, progress: dict) -> dict:
    """`progress` est un dict partagé, mis à jour au fil de l'import pour
    qu'un endpoint séparé puisse le lire pendant que ça tourne en tâche de
    fond (voir routers/export.py) : {"status", "total", "processed",
    "error", "summary"}.
    """
    total = sum(len(data.get(key, [])) for key, _, _ in _SECTIONS)
    progress.update({"status": "running", "total": total, "processed": 0, "error": None, "summary": None})

    summary: dict[str, int] = {}
    try:
        for key, model, field_fn in _SECTIONS:
            rows = data.get(key, [])
            if model is Category:
                # Deux passes, pas une simple restauration ligne à ligne
                # dans l'ordre des id : rien dans le schéma ne garantit
                # qu'un parent a un id plus petit que ses enfants (une
                # catégorie existante peut être reparentée sous une
                # catégorie créée après elle — cas réel constaté : "TV"
                # id 227 créée après sa sous-catégorie "Câble" id 124).
                # Trier par id croissant ne suffit donc pas à garantir que
                # le parent existe déjà quand l'enfant est inséré, d'où le
                # FK sur parent_id qui casserait sinon la restauration sur
                # une base vierge (typiquement la prod). On insère donc
                # d'abord toutes les catégories avec parent_id=None, puis
                # on fixe parent_id une fois que tous les id existent.
                for row in rows:
                    fields = field_fn(row)
                    fields["parent_id"] = None
                    _upsert(db, model, row["id"], fields)
                    progress["processed"] += 1
                db.flush()
                for row in rows:
                    parent_id = row.get("parent_id")
                    if parent_id is not None:
                        db.get(model, row["id"]).parent_id = parent_id
                db.flush()
            else:
                for row in rows:
                    _upsert(db, model, row["id"], field_fn(row))
                    progress["processed"] += 1
                db.flush()
            summary[key] = len(rows)

        db.commit()

        # Recalées seulement après le commit final : une séquence Postgres
        # n'est de toute façon jamais annulée par un rollback (elle n'est
        # pas transactionnelle), donc autant ne le faire qu'une fois
        # l'import entièrement réussi.
        for _key, model, _field_fn in _SECTIONS:
            _reset_sequence(db, model.__tablename__)
        db.commit()

        progress.update({"status": "done", "summary": summary})
        return summary
    except Exception as exc:
        db.rollback()
        progress.update({"status": "error", "error": str(exc)})
        raise
