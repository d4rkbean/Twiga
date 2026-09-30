from __future__ import annotations

import difflib
import re
from calendar import monthrange
from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import lru_cache

import bcrypt
from sqlalchemy import and_, case, delete, func, or_, select, update
from sqlalchemy.orm import Session, selectinload

from backend.dates import format_date_long_fr, month_range, months_between, shift_month
from backend.models import (
    Account,
    AppState,
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
    User,
)
from backend.payment_methods import detect_payment_from_label
from backend.pillars import PILLAR_ORDER
from backend.receipt_families import RECEIPT_FAMILIES, guess_receipt_family
from imports.common import DuplicateKey, ParsedTransaction, build_duplicate_key, split_duplicates
from imports.qif_parser import QifImportResult


def get_next_pending_transaction(db: Session) -> Transaction | None:
    # Les transactions passées ("Passer") repassent après toutes celles
    # jamais encore vues, triées par date de skip (la plus ancienne d'abord)
    # pour ne pas bloquer indéfiniment sur la même transaction.
    #
    # is_transfer.is_(False) : un virement n'a normalement plus rien à faire
    # ici, _tag_as_transfer() le validated=True en même temps qu'il le tague
    # — mais update_transaction() (édition manuelle depuis le détail d'une
    # opération) laisse jusqu'ici passer un is_transfer=True sans forcer
    # validated=True, ce qui pouvait laisser un virement (re)marqué comme tel
    # traîner ici tant qu'il n'était pas validé par ailleurs. Ce filtre est
    # le filet de sécurité côté lecture, en plus du correctif à la source.
    stmt = (
        select(Transaction)
        .options(selectinload(Transaction.account))
        .where(Transaction.validated.is_(False), Transaction.is_transfer.is_(False))
        .order_by(
            Transaction.skipped_at.is_not(None),
            Transaction.skipped_at,
            Transaction.date,
            Transaction.id,
        )
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()


def get_top_level_categories(db: Session) -> list[Category]:
    # parent_id IS NULL est déjà la condition correcte et suffisante pour
    # "catégorie de premier niveau" — mais une ligne "Parent:Enfant" mal
    # importée AVANT le correctif (migration 8a25bd1e09e3) a aussi
    # parent_id NULL tant qu'elle n'a pas été nettoyée en base. On exclut
    # donc en plus tout nom contenant encore ":" par sécurité, pour que
    # La Savane n'affiche jamais ce genre de ligne à plat même si la
    # migration de nettoyage n'a pas encore tourné sur cet environnement.
    stmt = (
        select(Category)
        .where(Category.parent_id.is_(None), Category.name.notlike("%:%"))
        .order_by(Category.name)
    )
    return list(db.execute(stmt).scalars().all())


def get_budgetable_categories(db: Session) -> list[Category]:
    # Même liste que get_top_level_categories, moins les catégories de
    # revenu (salaire, autres revenus...) marquées excluded_from_budget —
    # voir Category.excluded_from_budget. Uniquement pour l'écran Budgets :
    # la catégorisation, les règles et les rapports continuent d'utiliser
    # get_top_level_categories sans filtrage, une transaction de salaire
    # devant rester catégorisable normalement.
    stmt = (
        select(Category)
        .where(
            Category.parent_id.is_(None),
            Category.name.notlike("%:%"),
            Category.excluded_from_budget.is_(False),
        )
        .order_by(Category.name)
    )
    return list(db.execute(stmt).scalars().all())


def find_matching_rule(db: Session, label: str) -> Rule | None:
    label_lower = label.lower()
    for rule in db.execute(select(Rule).options(selectinload(Rule.category))).scalars().all():
        if rule.keyword.lower() in label_lower:
            return rule
    return None


def _maybe_add_receipt_family_line(db: Session, transaction: Transaction, category: Category) -> None:
    # Commerces à famille de produit unique (boulangerie, primeur...) : une
    # règle dont le rayon est renseigné (Rule.receipt_family) fait ajouter
    # automatiquement une ligne de ticket unique couvrant tout le montant de
    # la transaction — inutile d'attendre une vraie facture à importer ou de
    # la saisir à la main quand il n'y a de toute façon qu'un seul rayon
    # possible. Jamais si la transaction a déjà des lignes (pas question
    # d'écraser une décomposition déjà faite, à la main ou depuis une vraie
    # facture) ni si la catégorie appliquée n'est pas "Courses" (seule où le
    # rapport par rayon a du sens — voir Rule.receipt_family).
    if category.name != "Courses":
        return
    has_items = db.execute(
        select(func.count())
        .select_from(ReceiptItem)
        .where(ReceiptItem.transaction_id == transaction.id)
    ).scalar_one()
    if has_items:
        return
    rule = find_matching_rule(db, transaction.raw_label)
    if rule is None or not rule.receipt_family:
        return
    add_receipt_item(db, transaction.id, transaction.label, abs(transaction.amount), rule.receipt_family)


def categorize_transaction(
    db: Session,
    transaction: Transaction,
    category: Category,
    label: str | None = None,
    payment_method: str | None = None,
) -> Transaction:
    if label and label.strip():
        transaction.label = label.strip()
    transaction.category_id = category.id
    transaction.validated = True
    if payment_method:
        transaction.payment_method = payment_method
    db.commit()
    db.refresh(transaction)
    _maybe_add_receipt_family_line(db, transaction, category)
    return transaction


def bulk_update_transactions(
    db: Session,
    transactions: list[Transaction],
    category: Category | None = None,
    payment_method: str | None = None,
) -> list[int]:
    # Contrairement à categorize_transaction (catégorie obligatoire), les
    # deux champs sont ici indépendants : la catégorisation en masse permet
    # d'appliquer UNIQUEMENT un mode de paiement, sans toucher à la
    # catégorie, et inversement. On ne modifie donc que ce qui est fourni.
    categorized_ids = []
    for transaction in transactions:
        if category is not None:
            transaction.category_id = category.id
            transaction.validated = True
            categorized_ids.append(transaction.id)
        if payment_method is not None:
            transaction.payment_method = payment_method
    db.commit()
    if category is not None:
        for transaction in transactions:
            _maybe_add_receipt_family_line(db, transaction, category)
    return categorized_ids


def detect_missing_payment_methods(db: Session) -> int:
    # raw_label (jamais modifié), pas label (éditable par l'utilisateur) :
    # même principe que get_existing_transaction_keys, pour une détection
    # fiable même sur une transaction déjà simplifiée dans La Savane.
    transactions = (
        db.execute(select(Transaction).where(Transaction.payment_method.is_(None)))
        .scalars()
        .all()
    )
    updated = 0
    for transaction in transactions:
        detected = detect_payment_from_label(transaction.raw_label)
        if detected is not None:
            transaction.payment_method = detected
            updated += 1
    db.commit()
    return updated


def skip_transaction(db: Session, transaction: Transaction, label: str | None = None) -> Transaction:
    if label and label.strip():
        transaction.label = label.strip()
    transaction.skipped_at = datetime.now()
    db.commit()
    db.refresh(transaction)
    return transaction


def reject_from_backlog(db: Session, transaction: Transaction) -> Transaction:
    # Distinct de skip_transaction() : voir le commentaire sur
    # Transaction.backlog_rejected_at. Ne touche jamais skipped_at, donc ne
    # change rien à la place de cette opération dans La Savane.
    transaction.backlog_rejected_at = datetime.now()
    db.commit()
    db.refresh(transaction)
    return transaction


def undo_transaction(db: Session, transaction: Transaction) -> Transaction:
    transaction.validated = False
    transaction.category_id = None
    transaction.skipped_at = None
    db.commit()
    db.refresh(transaction)
    return transaction


def count_pending_transactions(db: Session) -> int:
    # is_transfer.is_(False) : doit rester cohérent avec
    # get_next_pending_transaction (même filtre) pour que ce compte reflète
    # exactement le nombre d'opérations réellement enterables dans La
    # Savane, jamais gonflé par un virement resté non validé.
    stmt = (
        select(func.count())
        .select_from(Transaction)
        .where(Transaction.validated.is_(False), Transaction.is_transfer.is_(False))
    )
    return db.execute(stmt).scalar_one()


def list_accounts(db: Session) -> list[Account]:
    return list(db.execute(select(Account).order_by(Account.name)).scalars().all())


def get_payment_methods_dict(db: Session) -> dict[str, dict[str, str]]:
    # Même forme que l'ancien dict statique backend.payment_methods.
    # PAYMENT_METHODS ({name: {"icon", "label"}}) qu'il remplace, pour que
    # tous les templates existants (transactions/_new.html, _detail.html,
    # rules/*, inbox/_payment_step.html, backlog/_content.html...)
    # continuent de fonctionner sans modification — seule la source des
    # données change (table payment_methods plutôt qu'une constante Python),
    # ce qui rend enfin les moyens de paiement ajoutés/modifiés/supprimés
    # depuis Paramètres > Moyens de paiement réellement utilisables ailleurs
    # dans l'appli. Le nom (PaymentMethod.name) sert de clé/valeur stockée
    # dans Transaction.payment_method / Rule.payment_method, il n'y a pas de
    # colonne "code" séparée.
    methods = db.execute(select(PaymentMethod).order_by(PaymentMethod.display_order)).scalars().all()
    return {m.name: {"icon": m.icon, "label": m.name} for m in methods}


def get_existing_account_names(db: Session) -> set[str]:
    return {name for (name,) in db.execute(select(Account.name)).all()}


def get_existing_transaction_keys(db: Session) -> set[DuplicateKey]:
    # Comparaison sur raw_label (jamais modifié) et non label (éditable par
    # l'utilisateur dans La Savane), pour que la détection de doublons reste
    # fiable même après simplification manuelle d'un libellé.
    stmt = select(Transaction.date, Transaction.amount, Transaction.raw_label, Account.name).join(
        Account, Transaction.account_id == Account.id
    )
    return {
        build_duplicate_key(account_name, tx_date, amount, raw_label)
        for tx_date, amount, raw_label, account_name in db.execute(stmt).all()
    }


def get_existing_transactions_by_key(db: Session) -> dict[DuplicateKey, Transaction]:
    # Comme get_existing_transaction_keys, mais renvoie les Transaction elles-
    # mêmes (pas juste leurs clés) pour permettre de les corriger lors d'un
    # ré-import QIF : cf. import_qif_result.
    stmt = select(Transaction, Account.name).join(Account, Transaction.account_id == Account.id)
    return {
        build_duplicate_key(account_name, tx.date, tx.amount, tx.raw_label): tx
        for tx, account_name in db.execute(stmt).all()
    }


# --- Détection automatique des virements internes ---

_TRANSFER_DATE_TOLERANCE_DAYS = 3
_TRANSFER_AMOUNT_TOLERANCE = Decimal("1.00")
_TRANSFER_KEYWORDS = ("VIREMENT", "VIR", "TRANSFER")


def looks_like_transfer(label: str | None) -> bool:
    if not label:
        return False
    upper = label.upper()
    return any(keyword in upper for keyword in _TRANSFER_KEYWORDS)


def _amounts_match_as_transfer(amount_a: Decimal, amount_b: Decimal) -> bool:
    # Signes opposés (l'un débite, l'autre crédite) et valeurs absolues
    # proches à la tolérance de frais près (ex : virement de 500€ débité
    # 500€ mais crédité 499,50€ côté banque destinataire).
    if amount_a == 0 or amount_b == 0:
        return False
    if (amount_a > 0) == (amount_b > 0):
        return False
    return abs(abs(amount_a) - abs(amount_b)) <= _TRANSFER_AMOUNT_TOLERANCE


def detect_transfer_matches(
    db: Session, candidates: list[Transaction] | None = None
) -> list[tuple[Transaction, Transaction]]:
    # candidates=None -> détection manuelle sur tout l'historique (Paramètres
    # > Gérer les comptes > Détecter virements) : le pool ET les candidats
    # sont alors les mêmes transactions. candidates=<lignes fraîchement
    # importées> -> détection automatique après import : les candidats sont
    # comparés contre TOUT l'historique (pool), pas seulement entre eux,
    # pour retrouver l'autre jambe d'un virement importée plus tôt.
    pool_stmt = (
        select(Transaction)
        .options(selectinload(Transaction.account))
        .where(Transaction.is_transfer.is_(False))
        .order_by(Transaction.date)
    )
    pool = list(db.execute(pool_stmt).scalars().all())

    if candidates is None:
        candidates = pool

    matched_ids: set[int] = set()
    pairs: list[tuple[Transaction, Transaction]] = []

    for candidate in candidates:
        if candidate.id in matched_ids or candidate.is_transfer:
            continue
        for other in pool:
            if other.id == candidate.id or other.id in matched_ids:
                continue
            if other.account_id == candidate.account_id:
                continue
            if not _amounts_match_as_transfer(candidate.amount, other.amount):
                continue
            if abs((other.date - candidate.date).days) > _TRANSFER_DATE_TOLERANCE_DAYS:
                continue
            matched_ids.add(candidate.id)
            matched_ids.add(other.id)
            pairs.append((candidate, other))
            break

    return pairs


def _tag_as_transfer(transaction: Transaction) -> None:
    transaction.is_transfer = True
    # Un virement n'a pas de catégorie de dépense à assigner : exclu de La
    # Savane automatiquement, comme pour les virements détectés à l'import
    # QIF (voir import_qif_result).
    transaction.validated = True


def _pair_summary(tx_a: Transaction, tx_b: Transaction) -> dict:
    negative, positive = (tx_a, tx_b) if tx_a.amount < 0 else (tx_b, tx_a)
    return {
        "account_from": negative.account.name,
        "account_to": positive.account.name,
        "amount": abs(negative.amount),
        "date": negative.date,
    }


def auto_tag_transfers(
    db: Session, candidates: list[Transaction] | None = None
) -> list[dict]:
    pairs = detect_transfer_matches(db, candidates)
    summary = []
    for tx_a, tx_b in pairs:
        _tag_as_transfer(tx_a)
        _tag_as_transfer(tx_b)
        summary.append(_pair_summary(tx_a, tx_b))
    db.commit()
    return summary


def group_transfer_summary(pairs_info: list[dict]) -> list[dict]:
    groups: dict[tuple[str, str], dict] = {}
    for info in pairs_info:
        key = (info["account_from"], info["account_to"])
        group = groups.setdefault(
            key, {"account_from": info["account_from"], "account_to": info["account_to"], "count": 0, "dates": []}
        )
        group["count"] += 1
        group["dates"].append(info["date"])
    return sorted(groups.values(), key=lambda g: -g["count"])


def create_pending_check(
    db: Session,
    amount: Decimal,
    issued_date: date,
    category: Category,
    account: Account,
    check_number: str | None = None,
    payment_method: str | None = None,
    recipient: str | None = None,
) -> PendingCheck:
    pending_check = PendingCheck(
        check_number=check_number.strip() if check_number and check_number.strip() else None,
        payment_method=payment_method.strip() if payment_method and payment_method.strip() else None,
        # Signé négatif : un paiement en attente est toujours émis par
        # l'utilisateur (sortie d'argent), jamais reçu — le formulaire ne
        # demande qu'un montant positif, le signe est appliqué ici.
        amount=-abs(amount),
        issued_date=issued_date,
        category_id=category.id,
        account_id=account.id,
        recipient=recipient.strip() if recipient else None,
    )
    db.add(pending_check)
    db.commit()
    db.refresh(pending_check)
    return pending_check


def get_outstanding_pending_checks(db: Session) -> list[PendingCheck]:
    stmt = (
        select(PendingCheck)
        .options(selectinload(PendingCheck.category), selectinload(PendingCheck.account))
        .where(PendingCheck.matched_transaction_id.is_(None))
        .order_by(PendingCheck.issued_date)
    )
    return list(db.execute(stmt).scalars().all())


def get_matched_pending_checks(db: Session, limit: int = 10) -> list[PendingCheck]:
    stmt = (
        select(PendingCheck)
        .options(
            selectinload(PendingCheck.category),
            selectinload(PendingCheck.account),
            selectinload(PendingCheck.matched_transaction),
        )
        .where(PendingCheck.matched_transaction_id.is_not(None))
        .order_by(PendingCheck.matched_at.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def delete_pending_check(db: Session, pending_check: PendingCheck) -> None:
    db.delete(pending_check)
    db.commit()


_PENDING_PAYMENT_MATCH_WINDOW_DAYS = 10


def match_pending_checks(db: Session, candidates: list[Transaction]) -> list[dict]:
    # Rapprochement automatique (mêmes points d'appel que auto_tag_transfers :
    # juste après l'insertion de nouvelles transactions à l'import). Exige
    # TOUJOURS le montant exact (plus compte + date de cohérence) ET une
    # ancre textuelle retrouvée dans le libellé brut — jamais un montant
    # seul, qui peut coïncider par hasard :
    #   - check_number (chèque) : aucune limite de délai, un chèque peut
    #     mettre des semaines à être débité.
    #   - payment_method (Wero, PayPal...) : pas de référence précise pour
    #     ancrer le rapprochement, donc fenêtre resserrée
    #     (_PENDING_PAYMENT_MATCH_WINDOW_DAYS) pour limiter le risque de
    #     confondre deux paiements du même montant via le même service à
    #     quelques jours d'écart.
    outstanding = get_outstanding_pending_checks(db)
    if not outstanding:
        return []

    available = [tx for tx in candidates if not tx.validated and not tx.is_transfer]
    matched_summary = []
    for pending_check in outstanding:
        anchor = (pending_check.check_number or pending_check.payment_method or "").strip().lower()
        if not anchor:
            continue
        for transaction in available:
            if transaction.account_id != pending_check.account_id:
                continue
            if transaction.amount != pending_check.amount:
                continue
            if transaction.date < pending_check.issued_date:
                continue
            if not pending_check.check_number:
                days_since_issued = (transaction.date - pending_check.issued_date).days
                if days_since_issued > _PENDING_PAYMENT_MATCH_WINDOW_DAYS:
                    continue
            if anchor not in transaction.raw_label.lower():
                continue

            transaction.category_id = pending_check.category_id
            transaction.validated = True
            pending_check.matched_transaction_id = transaction.id
            pending_check.matched_at = datetime.utcnow()
            matched_summary.append(
                {
                    "check_number": pending_check.check_number,
                    "payment_method": pending_check.payment_method,
                    "recipient": pending_check.recipient,
                    "category_name": pending_check.category.name,
                    "amount": transaction.amount,
                }
            )
            available.remove(transaction)
            break
    if matched_summary:
        db.commit()
    return matched_summary


def confirm_transfer_pair_by_ids(db: Session, tx_a_id: int, tx_b_id: int) -> bool:
    tx_a = db.get(Transaction, tx_a_id)
    tx_b = db.get(Transaction, tx_b_id)
    if tx_a is None or tx_b is None:
        return False
    _tag_as_transfer(tx_a)
    _tag_as_transfer(tx_b)
    db.commit()
    return True


def mark_transaction_as_transfer(db: Session, transaction: Transaction, label: str | None = None) -> Transaction:
    if label and label.strip():
        transaction.label = label.strip()
    _tag_as_transfer(transaction)
    db.commit()
    db.refresh(transaction)
    return transaction


def bulk_insert_transactions(
    db: Session, account: Account, transactions: list[ParsedTransaction]
) -> dict:
    rows = [
        Transaction(
            date=tx.date,
            label=tx.label,
            raw_label=tx.label,
            amount=tx.amount,
            account_id=account.id,
            validated=False,
            payment_method=detect_payment_from_label(tx.label),
        )
        for tx in transactions
    ]
    db.add_all(rows)
    db.flush()
    transfer_pairs_info = auto_tag_transfers(db, rows)
    check_match_summary = match_pending_checks(db, [r for r in rows if not r.is_transfer])
    return {
        "imported_count": len(rows),
        "transfer_summary": group_transfer_summary(transfer_pairs_info),
        "check_match_summary": check_match_summary,
        "to_categorize_count": sum(1 for r in rows if not r.validated),
    }


def import_qif_result(db: Session, result: QifImportResult) -> dict:
    accounts_by_name: dict[str, Account] = {
        account.name: account for account in db.execute(select(Account)).scalars().all()
    }
    for parsed_account in result.accounts:
        if parsed_account.name not in accounts_by_name:
            account = Account(
                name=parsed_account.name,
                type=parsed_account.type,
                balance=parsed_account.balance,
            )
            db.add(account)
            accounts_by_name[parsed_account.name] = account
    db.flush()

    existing_categories_by_key: dict[tuple[str, int | None], Category] = {
        (category.name, category.parent_id): category
        for category in db.execute(select(Category)).scalars().all()
    }

    # result.categories est trié par chemin ("Alimentation" avant
    # "Alimentation:Restaurant"), donc le parent existe toujours déjà dans
    # categories_by_path au moment de résoudre un enfant.
    categories_by_path: dict[str, Category] = {}
    for parsed_category in result.categories:
        parent = (
            categories_by_path.get(parsed_category.parent_path)
            if parsed_category.parent_path
            else None
        )
        parent_id = parent.id if parent else None
        key = (parsed_category.name, parent_id)
        category = existing_categories_by_key.get(key)
        if category is None:
            category = Category(name=parsed_category.name, parent_id=parent_id)
            db.add(category)
            db.flush()
            existing_categories_by_key[key] = category
        categories_by_path[parsed_category.path] = category

    existing_transactions_by_key = get_existing_transactions_by_key(db)
    existing_keys = set(existing_transactions_by_key.keys())
    unique, duplicates = split_duplicates(result.transactions, existing_keys)

    rows = []
    for tx in unique:
        account = accounts_by_name.get(tx.account_name)
        if account is None:
            continue
        category = categories_by_path.get(tx.category_path) if tx.category_path else None
        is_transfer = tx.transfer_account is not None
        rows.append(
            Transaction(
                date=tx.date,
                label=tx.label,
                raw_label=tx.label,
                amount=tx.amount,
                account_id=account.id,
                category_id=category.id if category else None,
                # Un virement n'a pas de catégorie de dépense à assigner :
                # inutile de le faire passer par La Savane.
                validated=category is not None or is_transfer,
                is_transfer=is_transfer,
                payment_method=detect_payment_from_label(tx.label),
            )
        )
    db.add_all(rows)
    db.flush()
    # Ne redétecte pas ce que le QIF a déjà marqué explicitement comme
    # virement (tx.transfer_account, ci-dessus) : seules les lignes encore
    # non taguées passent par l'heuristique montant/date.
    transfer_pairs_info = auto_tag_transfers(db, [r for r in rows if not r.is_transfer])
    check_match_summary = match_pending_checks(db, [r for r in rows if not r.is_transfer])

    # Un doublon (même date + montant + libellé + compte) correspond à une
    # transaction déjà en base : si le fichier QIF ré-importé lui associe une
    # catégorie différente (ou qu'elle n'en avait pas), on corrige le lien
    # plutôt que d'ignorer purement l'info — utile après le bug de parsing
    # "/" qui a fait perdre des catégories lors d'un premier import.
    relinked_count = 0
    for tx in duplicates:
        if not tx.category_path:
            continue
        category = categories_by_path.get(tx.category_path)
        if category is None:
            continue
        key = build_duplicate_key(tx.account_name, tx.date, tx.amount, tx.label)
        existing_tx = existing_transactions_by_key.get(key)
        if existing_tx is None or existing_tx.category_id == category.id:
            continue
        was_uncategorized = existing_tx.category_id is None
        existing_tx.category_id = category.id
        if was_uncategorized and not existing_tx.is_transfer:
            existing_tx.validated = True
        relinked_count += 1

    db.commit()

    return {
        "imported_count": len(rows),
        "duplicate_count": len(duplicates),
        "relinked_count": relinked_count,
        "transfer_summary": group_transfer_summary(transfer_pairs_info),
        "check_match_summary": check_match_summary,
        "to_categorize_count": sum(1 for r in rows if not r.validated),
    }


def get_account_balances(db: Session) -> list[tuple[Account, Decimal]]:
    # account.balance est traité comme le solde d'ouverture avant toute
    # transaction importée ; le solde courant = solde d'ouverture + somme de
    # toutes les transactions (validées ou non : l'argent a déjà bougé,
    # que la catégorisation soit faite ou pas).
    stmt = (
        select(Account, func.coalesce(func.sum(Transaction.amount), 0))
        .outerjoin(Transaction, Transaction.account_id == Account.id)
        .group_by(Account.id)
        .order_by(Account.name)
    )
    return [(account, account.balance + total) for account, total in db.execute(stmt).all()]


def get_account_balances_with_monthly_evolution(
    db: Session, month_start: date, month_end: date
) -> list[dict]:
    # Solde réel (comme get_account_balances) + mouvement du mois en cours
    # pour chaque compte, pour les cartes du dashboard. Les virements internes
    # comptent normalement ici (débit d'un compte, crédit de l'autre), tout
    # comme dans le total global tous comptes (voir get_total_balance).
    balances = get_account_balances(db)

    stmt_month = (
        select(Transaction.account_id, func.coalesce(func.sum(Transaction.amount), 0))
        .where(Transaction.date >= month_start, Transaction.date <= month_end)
        .group_by(Transaction.account_id)
    )
    monthly_by_account = dict(db.execute(stmt_month).all())

    return [
        {
            "account": account,
            "balance": balance,
            "monthly_evolution": monthly_by_account.get(account.id, Decimal("0.00")),
        }
        for account, balance in balances
    ]


def get_accounts_overview(db: Session) -> list[dict]:
    # Pour la page Paramètres > Gérer les comptes : solde réel + décompte
    # complet par compte (nombre de transactions, virements internes...),
    # affiché pour que l'utilisateur sache si une suppression est sans
    # risque avant même d'essayer, et pour alimenter le détail diagnostic
    # de chaque compte (voir _row.html) sans requête supplémentaire.
    stmt = (
        select(
            Account,
            func.count(Transaction.id),
            func.coalesce(func.sum(Transaction.amount), 0),
            func.count(case((Transaction.is_transfer.is_(True), 1))),
            func.coalesce(
                func.sum(case((Transaction.is_transfer.is_(True), Transaction.amount), else_=0)), 0
            ),
        )
        .outerjoin(Transaction, Transaction.account_id == Account.id)
        .group_by(Account.id)
        .order_by(Account.name)
    )
    results = []
    for account, tx_count, tx_sum, transfer_count, transfer_sum in db.execute(stmt).all():
        results.append(
            {
                "account": account,
                "transaction_count": tx_count,
                "transactions_sum": tx_sum,
                "transfer_count": transfer_count,
                "transfer_sum": transfer_sum,
                "initial_balance": account.balance,
                "balance": account.balance + tx_sum,
            }
        )
    return results


# --- Diagnostic de solde (Paramètres > Gérer les comptes) ---

_UNUSUAL_AMOUNT_MULTIPLIER = Decimal("3")
_SUSPICIOUS_LIST_LIMIT = 15


def find_duplicate_transactions(db: Session) -> list[dict]:
    # Doublons potentiels : même date + montant + libellé, sur 2 transactions
    # ou plus, TOUS COMPTES CONFONDUS (contrairement à la détection de
    # doublons à l'import, qui inclut aussi account_id — voir
    # imports/common.build_duplicate_key). Volontairement plus large ici :
    # cet outil cherche des anomalies expliquant un écart de solde, y compris
    # une même transaction importée deux fois dans deux comptes différents.
    dup_key = (
        select(Transaction.date, Transaction.amount, Transaction.label)
        .group_by(Transaction.date, Transaction.amount, Transaction.label)
        .having(func.count(Transaction.id) >= 2)
        .subquery()
    )
    stmt = (
        select(Transaction)
        .options(selectinload(Transaction.account))
        .join(
            dup_key,
            and_(
                Transaction.date == dup_key.c.date,
                Transaction.amount == dup_key.c.amount,
                Transaction.label == dup_key.c.label,
            ),
        )
        .order_by(Transaction.date.desc(), Transaction.label)
    )
    transactions = list(db.execute(stmt).scalars().all())

    groups: dict[tuple, dict] = {}
    for tx in transactions:
        key = (tx.date, tx.amount, tx.label)
        group = groups.setdefault(
            key, {"date": tx.date, "amount": tx.amount, "label": tx.label, "transactions": []}
        )
        group["transactions"].append(tx)

    ordered = sorted(groups.values(), key=lambda g: g["date"], reverse=True)
    for group in ordered:
        group["count"] = len(group["transactions"])
    return ordered


def find_unusual_amount_transactions(
    db: Session, multiplier: Decimal = _UNUSUAL_AMOUNT_MULTIPLIER
) -> list[Transaction]:
    # Montant "hors norme" : au-delà de N fois la moyenne (en valeur
    # absolue) de TOUTES les transactions — un simple repère pour repérer
    # une saisie/un import manifestement erroné, pas un test statistique
    # rigoureux (pas d'écart-type, volontairement simple pour un outil de
    # diagnostic).
    avg_abs = db.execute(select(func.avg(func.abs(Transaction.amount)))).scalar_one()
    if not avg_abs:
        return []
    threshold = avg_abs * multiplier
    stmt = (
        select(Transaction)
        .options(selectinload(Transaction.account))
        .where(func.abs(Transaction.amount) > threshold)
        .order_by(func.abs(Transaction.amount).desc())
    )
    return list(db.execute(stmt).scalars().all())


def find_transactions_without_account(db: Session) -> list[Transaction]:
    # transactions.account_id est NOT NULL (contrainte de clé étrangère) :
    # ce cas est en théorie impossible tant que la base respecte son schéma.
    # Vérifié quand même par sécurité (diagnostic exhaustif), toujours vide
    # en pratique.
    stmt = select(Transaction).options(selectinload(Transaction.account)).where(
        Transaction.account_id.is_(None)
    )
    return list(db.execute(stmt).scalars().all())


def get_suspicious_transactions(db: Session) -> dict:
    duplicates = find_duplicate_transactions(db)
    unusual = find_unusual_amount_transactions(db)
    return {
        "duplicates": duplicates[:_SUSPICIOUS_LIST_LIMIT],
        "duplicates_total": len(duplicates),
        "unusual": unusual[:_SUSPICIOUS_LIST_LIMIT],
        "unusual_total": len(unusual),
        "no_account": find_transactions_without_account(db),
    }


def create_account(
    db: Session,
    name: str,
    type: str,
    initial_balance: Decimal,
    currency: str = "EUR",
    color: str | None = None,
    notes: str | None = None,
) -> Account:
    account = Account(
        name=name,
        type=type,
        balance=initial_balance,
        currency=currency or "EUR",
        color=color or None,
        notes=notes or None,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def update_account(
    db: Session,
    account: Account,
    name: str,
    type: str,
    initial_balance: Decimal,
    color: str | None,
    notes: str | None,
) -> Account:
    account.name = name
    account.type = type
    account.balance = initial_balance
    account.color = color or None
    account.notes = notes or None
    db.commit()
    db.refresh(account)
    return account


def get_account_transaction_count(db: Session, account_id: int) -> int:
    stmt = select(func.count()).select_from(Transaction).where(Transaction.account_id == account_id)
    return db.execute(stmt).scalar_one()


def delete_account(db: Session, account: Account) -> None:
    db.delete(account)
    db.commit()


def get_transaction_years(db: Session) -> list[int]:
    year_col = func.extract("year", Transaction.date)
    stmt = select(func.distinct(year_col)).order_by(year_col.desc())
    return [int(year) for (year,) in db.execute(stmt).all()]


def get_total_balance(db: Session) -> Decimal:
    # Solde total tous comptes = SUM(soldes initiaux) + SUM(TOUTES les
    # transactions), virements inclus. Un virement correctement apparié
    # (débit d'un compte + crédit d'un autre, même montant) s'annule déjà
    # tout seul dans une somme brute — l'inclure ne fausse donc rien.
    # Précédemment ("get_total_balance_excluding_transfers"), les virements
    # étaient explicitement EXCLUS de la somme dans l'idée d'éviter un écart
    # si un seul des deux mouvements était importé — mais c'est l'inverse
    # qui se produit : un virement non apparié (compte destinataire pas
    # encore importé, ou faux positif de la détection auto) fait alors
    # disparaître de cette somme un mouvement d'argent bien réel, rendant le
    # total incohérent avec la somme des soldes réels par compte (qui, eux,
    # incluent toujours toutes les transactions). Ce total doit toujours
    # rester égal à la somme de get_account_balances().
    opening = db.execute(select(func.coalesce(func.sum(Account.balance), 0))).scalar_one()
    moved = db.execute(select(func.coalesce(func.sum(Transaction.amount), 0))).scalar_one()
    return opening + moved


def get_income_total(
    db: Session, start: date, end: date, account_id: int | None = None
) -> Decimal:
    conditions = [
        Transaction.date >= start,
        Transaction.date <= end,
        Transaction.amount > 0,
        Transaction.is_transfer.is_(False),
    ]
    if account_id is not None:
        conditions.append(Transaction.account_id == account_id)
    stmt = select(func.coalesce(func.sum(Transaction.amount), 0)).where(*conditions)
    return db.execute(stmt).scalar_one()


def get_expense_total(
    db: Session, start: date, end: date, account_id: int | None = None
) -> Decimal:
    conditions = [
        Transaction.date >= start,
        Transaction.date <= end,
        Transaction.amount < 0,
        Transaction.is_transfer.is_(False),
    ]
    if account_id is not None:
        conditions.append(Transaction.account_id == account_id)
    stmt = select(func.coalesce(func.sum(Transaction.amount), 0)).where(*conditions)
    return -db.execute(stmt).scalar_one()


def _resolve_top_level_category(db: Session) -> Callable[[int | None], tuple[int | None, str]]:
    categories = {c.id: c for c in db.execute(select(Category)).scalars().all()}

    def resolve(category_id: int | None) -> tuple[int | None, str]:
        if category_id is None:
            return None, "Non catégorisé"
        category = categories.get(category_id)
        while category is not None and category.parent_id is not None:
            category = categories.get(category.parent_id)
        if category is None:
            return None, "Non catégorisé"
        return category.id, category.name

    return resolve


def _get_category_totals(
    db: Session, start: date, end: date, *, positive: bool, account_id: int | None = None
) -> list[tuple[int | None, str, Decimal]]:
    # Le signe du montant est le SEUL critère qui distingue recette et
    # dépense. Le nom ou l'identité de la catégorie n'entre jamais en jeu :
    # une catégorie "Salaire" avec un montant négatif compte comme une
    # dépense, une catégorie "Courses" avec un montant positif compte comme
    # une recette. L'id de catégorie (racine, None = non catégorisé) est
    # gardé avec le total pour permettre de rouvrir les transactions
    # exactes d'un secteur du donut (voir get_category_transactions).
    resolve = _resolve_top_level_category(db)
    sign_condition = Transaction.amount > 0 if positive else Transaction.amount < 0

    conditions = [
        Transaction.date >= start,
        Transaction.date <= end,
        sign_condition,
        Transaction.is_transfer.is_(False),
    ]
    if account_id is not None:
        conditions.append(Transaction.account_id == account_id)

    stmt = select(Transaction.category_id, Transaction.amount).where(*conditions)
    totals: dict[int | None, dict] = {}
    for category_id, amount in db.execute(stmt).all():
        top_id, top_name = resolve(category_id)
        magnitude = amount if positive else -amount
        entry = totals.setdefault(top_id, {"name": top_name, "amount": Decimal("0.00")})
        entry["amount"] += magnitude

    rows = [(cid, data["name"], data["amount"]) for cid, data in totals.items()]
    return sorted(rows, key=lambda item: item[2], reverse=True)


def get_category_spending(
    db: Session, start: date, end: date, account_id: int | None = None
) -> list[tuple[int | None, str, Decimal]]:
    return _get_category_totals(db, start, end, positive=False, account_id=account_id)


def get_category_income(
    db: Session, start: date, end: date, account_id: int | None = None
) -> list[tuple[int | None, str, Decimal]]:
    return _get_category_totals(db, start, end, positive=True, account_id=account_id)


def get_category_transactions(
    db: Session,
    start: date,
    end: date,
    category_id: int | None,
    *,
    positive: bool,
    account_id: int | None = None,
) -> list[Transaction]:
    # Mêmes critères que _get_category_totals (période, signe, jamais un
    # virement), plus le filtre catégorie : category_id=None cible "Non
    # catégorisé", sinon la catégorie racine ET ses sous-catégories (déjà
    # fusionnées dans le total du donut, donc dans la liste qui l'explique).
    sign_condition = Transaction.amount > 0 if positive else Transaction.amount < 0
    conditions = [
        Transaction.date >= start,
        Transaction.date <= end,
        sign_condition,
        Transaction.is_transfer.is_(False),
    ]
    if account_id is not None:
        conditions.append(Transaction.account_id == account_id)

    if category_id is None:
        conditions.append(Transaction.category_id.is_(None))
    else:
        child_ids = [c.id for c in get_child_categories(db, category_id)]
        conditions.append(Transaction.category_id.in_([category_id, *child_ids]))

    stmt = (
        select(Transaction)
        .options(selectinload(Transaction.account), selectinload(Transaction.category))
        .where(*conditions)
        .order_by(Transaction.date.desc(), Transaction.id.desc())
    )
    return list(db.execute(stmt).scalars().all())


def get_category_amount_for_period(
    db: Session,
    start: date,
    end: date,
    category_id: int | None,
    *,
    positive: bool,
    account_id: int | None = None,
    exact: bool = False,
) -> Decimal:
    # Même filtre que get_category_transactions (catégorie racine ET ses
    # sous-catégories, jamais un virement) mais agrégé en un seul montant :
    # sert à construire l'évolution mensuelle d'une catégorie (voir
    # get_category_trend), où seul le total par mois compte, pas le détail
    # des opérations.
    sign_condition = Transaction.amount > 0 if positive else Transaction.amount < 0
    conditions = [
        Transaction.date >= start,
        Transaction.date <= end,
        sign_condition,
        Transaction.is_transfer.is_(False),
    ]
    if account_id is not None:
        conditions.append(Transaction.account_id == account_id)

    if category_id is None:
        conditions.append(Transaction.category_id.is_(None))
    elif exact:
        # Sous-catégorie (ex. « Gaz ») : pas de descendants à agréger, et
        # pour la ligne « directement dans le parent » on ne veut surtout
        # pas y ajouter les sous-catégories voisines.
        conditions.append(Transaction.category_id == category_id)
    else:
        child_ids = [c.id for c in get_child_categories(db, category_id)]
        conditions.append(Transaction.category_id.in_([category_id, *child_ids]))

    magnitude_expr = Transaction.amount if positive else -Transaction.amount
    stmt = select(func.coalesce(func.sum(magnitude_expr), 0)).where(*conditions)
    return db.execute(stmt).scalar_one()


def get_category_trend(
    db: Session,
    category_id: int | None,
    months: list[tuple[date, date, str]],
    *,
    positive: bool,
    account_id: int | None = None,
    exact: bool = False,
) -> list[dict]:
    # Une requête agrégée par mois (comme get_cashflow_months) plutôt qu'une
    # seule requête group by mois sur toute la fenêtre : le filtre catégorie
    # (racine + sous-catégories, voir get_category_amount_for_period) varie
    # par catégorie, pas par mois, et ce nombre de mois reste toujours petit
    # et fixe (12), donc sans impact mesurable.
    return [
        {
            "start": start,
            "end": end,
            "label": label,
            "amount": get_category_amount_for_period(
                db, start, end, category_id, positive=positive, account_id=account_id, exact=exact
            ),
        }
        for start, end, label in months
    ]


def _get_monthly_totals(
    db: Session, start: date, end: date, *, positive: bool, account_id: int | None = None
) -> dict[date, Decimal]:
    month_col = func.date_trunc("month", Transaction.date)
    sign_condition = Transaction.amount > 0 if positive else Transaction.amount < 0
    conditions = [
        Transaction.date >= start,
        Transaction.date <= end,
        sign_condition,
        Transaction.is_transfer.is_(False),
    ]
    if account_id is not None:
        conditions.append(Transaction.account_id == account_id)
    stmt = select(month_col, func.sum(Transaction.amount)).where(*conditions).group_by(month_col)
    if positive:
        return {row[0].date(): row[1] for row in db.execute(stmt).all()}
    return {row[0].date(): -row[1] for row in db.execute(stmt).all()}


def get_monthly_expense_totals(
    db: Session, start: date, end: date, account_id: int | None = None
) -> dict[date, Decimal]:
    return _get_monthly_totals(db, start, end, positive=False, account_id=account_id)


def get_monthly_income_totals(
    db: Session, start: date, end: date, account_id: int | None = None
) -> dict[date, Decimal]:
    return _get_monthly_totals(db, start, end, positive=True, account_id=account_id)


def get_period_monthly_breakdown(
    db: Session, start: date, end: date, account_id: int | None = None, *, shift_income: bool = False
) -> list[dict]:
    # Détail mensuel de l'onglet Balance du rapport : TOUS les mois civils
    # de la période sélectionnée, y compris ceux sans transaction (0,00 €
    # plutôt qu'absents) — contrairement à l'ancien filtrage de
    # cashflow_months (fenêtre glissante de 12 mois ancrée sur aujourd'hui,
    # souvent hors de la période choisie sur une année passée par exemple).
    # income_by_month/expense_by_month ne contiennent que les mois AYANT des
    # transactions (GROUP BY) : le .get(..., 0) ci-dessous joue le rôle du
    # LEFT JOIN, chaque mois civil généré par months_between() est présent
    # même sans entrée dans ces dicts.
    #
    # shift_income=True ("Décalage période", voir reports.py) : les recettes
    # affichées pour le mois M sont celles du mois M-1 (le salaire perçu fin
    # M-1 qui finance les dépenses de M), les dépenses restent sur leur
    # propre mois M. La fenêtre de requête des recettes démarre donc un mois
    # avant `start` pour couvrir les recettes du tout premier mois affiché.
    months = months_between(start, end)
    income_query_start = shift_month(months[0][0], -1) if shift_income and months else start
    income_by_month = get_monthly_income_totals(db, income_query_start, end, account_id)
    expense_by_month = get_monthly_expense_totals(db, start, end, account_id)

    results = []
    cumulative = Decimal("0.00")
    for month_start, month_end, label in months:
        income_key = shift_month(month_start, -1) if shift_income else month_start
        income = income_by_month.get(income_key, Decimal("0.00"))
        expense = expense_by_month.get(month_start, Decimal("0.00"))
        net = income - expense
        cumulative += net
        results.append(
            {
                "start": month_start,
                "end": month_end,
                "label": label,
                "income": income,
                "expense": expense,
                "net": net,
                "cumulative": cumulative,
            }
        )
    return results


def get_budget_progress(
    db: Session, start: date, end: date, account_id: int | None = None
) -> list[dict]:
    budget_stmt = (
        select(Budget.category_id, func.sum(Budget.amount))
        .where(Budget.month >= start, Budget.month <= end)
        .group_by(Budget.category_id)
    )
    budget_totals = {category_id: total for category_id, total in db.execute(budget_stmt).all()}
    if not budget_totals:
        return []

    categories = {c.id: c for c in db.execute(select(Category)).scalars().all()}

    # BUG corrigé : un budget est toujours défini sur une catégorie de
    # premier niveau (voir routers/budgets.py, save_budgets n'itère que sur
    # get_top_level_categories), mais la quasi-totalité des transactions
    # sont catégorisées sur une SOUS-catégorie, jamais sur le parent nu.
    # Comparer directement Transaction.category_id == budget.category_id
    # ne matchait donc presque jamais rien : la consommation restait à 0
    # même avec des dépenses réelles. On agrège maintenant le parent ET
    # tous ses enfants directs.
    ids_by_budget_category: dict[int, list[int]] = {}
    all_relevant_ids: set[int] = set()
    for category_id in budget_totals:
        child_ids = [c.id for c in categories.values() if c.parent_id == category_id]
        relevant_ids = [category_id, *child_ids]
        ids_by_budget_category[category_id] = relevant_ids
        all_relevant_ids.update(relevant_ids)

    # Le budget lui-même n'est pas rattaché à un compte (schéma), mais la
    # consommation réelle peut être filtrée par compte comme le reste du
    # dashboard.
    spent_conditions = [
        Transaction.date >= start,
        Transaction.date <= end,
        Transaction.amount < 0,
        Transaction.is_transfer.is_(False),
        Transaction.category_id.in_(all_relevant_ids),
    ]
    if account_id is not None:
        spent_conditions.append(Transaction.account_id == account_id)

    # Une dépense ne consomme son budget que si elle est attribuée AU MÊME
    # PILIER que la catégorie qui porte ce budget. Sans cette condition, les
    # deux lectures du mois utilisaient deux règles d'attribution
    # différentes et se contredisaient :
    #
    #   - une opération marquée imprévue bascule dans le pilier Imprévu
    #     (resolve_transaction_pillar) mais consommait quand même le budget
    #     de sa catégorie. Une réparation de 434 € faisait afficher
    #     « Auto/moto à 86 % » alors que les frais courants de la voiture
    #     n'étaient qu'à 24 % de leur enveloppe — c'est précisément ce que la
    #     réserve d'imprévus est censée absorber ;
    #   - même effet pour une sous-catégorie dont le pilier diffère de celui
    #     de sa racine (Vétérinaire sous Animaux domestiques).
    #
    # Conséquence mesurée avant correctif sur septembre 2026 : la somme des
    # lignes de détail d'un pilier dépassait sa propre jauge de 478 €.
    # L'agrégation se fait donc ligne à ligne plutôt qu'en SQL — la fenêtre
    # est d'un mois, le volume reste faible.
    enfants_par_parent: dict[int, list[Category]] = {}
    for c in categories.values():
        if c.parent_id is not None:
            enfants_par_parent.setdefault(c.parent_id, []).append(c)
    pilier_du_budget = {
        cid: resolve_budget_pillar(categories[cid], enfants_par_parent.get(cid, []))
        for cid in budget_totals
        if cid in categories
    }
    racine_de = {
        cid: budget_cid
        for budget_cid, ids in ids_by_budget_category.items()
        for cid in ids
    }

    spent_by_category_id: dict[int, Decimal] = {}
    for transaction in db.execute(select(Transaction).where(*spent_conditions)).scalars().all():
        budget_cid = racine_de.get(transaction.category_id)
        if budget_cid is None:
            continue
        if resolve_transaction_pillar(transaction) != pilier_du_budget.get(budget_cid):
            continue
        spent_by_category_id[transaction.category_id] = spent_by_category_id.get(
            transaction.category_id, Decimal("0.00")
        ) - transaction.amount

    results = []
    for category_id, budget_amount in budget_totals.items():
        category = categories.get(category_id)
        if category is None:
            continue
        spent = sum(
            (spent_by_category_id.get(cid, Decimal("0.00")) for cid in ids_by_budget_category[category_id]),
            Decimal("0.00"),
        )
        percentage = (spent / budget_amount * 100) if budget_amount else Decimal("0.00")
        results.append(
            {
                "category": category,
                "spent": spent,
                "budget": budget_amount,
                "percentage": percentage,
                "percentage_display": round(percentage),
                "bar_width": min(round(percentage), 100),
            }
        )

    results.sort(key=lambda r: r["percentage"], reverse=True)
    return results


def get_budgets_for_month(db: Session, month_start: date) -> dict[int, Decimal]:
    stmt = select(Budget.category_id, Budget.amount).where(Budget.month == month_start)
    return {category_id: amount for category_id, amount in db.execute(stmt).all()}


def _previous_month_start(month_start: date) -> date:
    if month_start.month == 1:
        return date(month_start.year - 1, 12, 1)
    return date(month_start.year, month_start.month - 1, 1)


def save_budgets(db: Session, month_start: date, amounts: dict[int, Decimal]) -> None:
    existing = {
        b.category_id: b
        for b in db.execute(select(Budget).where(Budget.month == month_start)).scalars().all()
    }
    for category_id, amount in amounts.items():
        current = existing.get(category_id)
        if amount == 0:
            if current is not None:
                db.delete(current)
            continue
        if current is not None:
            current.amount = amount
        else:
            db.add(Budget(category_id=category_id, month=month_start, amount=amount))
    db.commit()


def get_savings_withdrawal(db: Session, month_start: date) -> Decimal:
    stmt = select(BudgetMonth.savings_withdrawal).where(BudgetMonth.month == month_start)
    return db.execute(stmt).scalars().first() or Decimal("0.00")


def save_savings_withdrawal(db: Session, month_start: date, amount: Decimal) -> None:
    # Même logique que save_budgets : un montant nul supprime la ligne
    # plutôt que d'en garder une à zéro, pour qu'un mois sans prélèvement
    # n'apparaisse pas dans les exports.
    existing = (
        db.execute(select(BudgetMonth).where(BudgetMonth.month == month_start)).scalars().all()
    )
    if amount == 0:
        for row in existing:
            db.delete(row)
    elif existing:
        existing[0].savings_withdrawal = amount
        for duplicate in existing[1:]:
            db.delete(duplicate)
    else:
        db.add(BudgetMonth(month=month_start, savings_withdrawal=amount))
    db.commit()


def copy_budgets_from_previous_month(db: Session, target_month_start: date) -> int:
    previous_month_start = _previous_month_start(target_month_start)
    previous_budgets = (
        db.execute(select(Budget).where(Budget.month == previous_month_start)).scalars().all()
    )
    if not previous_budgets:
        return 0

    existing = {
        b.category_id: b
        for b in db.execute(select(Budget).where(Budget.month == target_month_start)).scalars().all()
    }
    count = 0
    for previous in previous_budgets:
        target = existing.get(previous.category_id)
        if target is not None:
            target.amount = previous.amount
        else:
            db.add(
                Budget(
                    category_id=previous.category_id,
                    month=target_month_start,
                    amount=previous.amount,
                )
            )
        count += 1
    db.commit()
    return count


# --- "Le Cap" (rituel budgétaire mensuel) ---


def get_category_monthly_typical(
    db: Session, month_start: date, lookback: int = 3
) -> dict[int, Decimal]:
    """Dépense mensuelle « habituelle » par catégorie RACINE.

    Médiane des `lookback` derniers mois complets précédant `month_start`,
    et non moyenne : un mois avec une grosse dépense exceptionnelle
    (électroménager, vacances) tirerait la moyenne vers le haut et ferait
    proposer un budget que l'utilisateur ne tiendra pas.

    Même agrégation racine + enfants directs que get_budget_progress : les
    budgets se posent sur une catégorie de premier niveau alors que les
    transactions sont catégorisées sur une sous-catégorie.

    Sert à deux choses dans le rituel du Cap (voir routers/cap.py) : proposer
    un montant quand aucun budget n'existe encore, et répartir une enveloppe
    de pilier entre ses catégories au prorata du réel.
    """
    categories = {c.id: c for c in db.execute(select(Category)).scalars().all()}
    enfants: dict[int, list[int]] = {}
    for racine_id, categorie in categories.items():
        if categorie.parent_id is None:
            enfants[racine_id] = [racine_id] + [
                c.id for c in categories.values() if c.parent_id == racine_id
            ]
    if not enfants:
        return {}

    mois = [shift_month(month_start, -(i + 1)) for i in range(lookback)]
    debut = min(mois)
    _, fin = month_range(max(mois).year, max(mois).month)

    stmt = (
        select(Transaction.category_id, Transaction.date, func.sum(Transaction.amount))
        .where(
            Transaction.date >= debut,
            Transaction.date <= fin,
            Transaction.amount < 0,
            Transaction.is_transfer.is_(False),
            Transaction.category_id.isnot(None),
        )
        .group_by(Transaction.category_id, Transaction.date)
    )

    # (racine, 1er du mois) -> total dépensé
    par_mois: dict[tuple[int, date], Decimal] = {}
    racine_de: dict[int, int] = {}
    for racine_id, ids in enfants.items():
        for cid in ids:
            racine_de[cid] = racine_id
    for category_id, jour, total in db.execute(stmt).all():
        racine_id = racine_de.get(category_id)
        if racine_id is None:
            continue
        cle = (racine_id, date(jour.year, jour.month, 1))
        par_mois[cle] = par_mois.get(cle, Decimal("0.00")) + (-total)

    resultat: dict[int, Decimal] = {}
    for racine_id in enfants:
        # Les mois sans dépense comptent comme 0 : sinon une catégorie
        # dépensée une seule fois sur trois mois se verrait proposer son
        # montant plein tous les mois.
        valeurs = sorted(par_mois.get((racine_id, m), Decimal("0.00")) for m in mois)
        if not valeurs:
            continue
        milieu = len(valeurs) // 2
        mediane = (
            valeurs[milieu]
            if len(valeurs) % 2
            else (valeurs[milieu - 1] + valeurs[milieu]) / 2
        )
        if mediane > 0:
            resultat[racine_id] = Decimal(mediane).quantize(Decimal("0.01"))
    return resultat


def get_month_detail_by_pillar(
    db: Session, start: date, end: date
) -> dict[str, dict]:
    """Détail par catégorie d'un mois, groupé par pilier.

    Sert aux DEUX écrans qui montrent le même mois à deux niveaux de zoom :
    « Mon mois » (où j'en suis) et le bilan de l'étape 1 du rituel (où j'en
    étais). Une seule fonction pour que les deux racontent exactement la
    même chose.

    Chaque pilier reçoit ses catégories budgétées (montant prévu, consommé,
    pourcentage) ET, si besoin, une ligne « hors budget ».

    Cette dernière n'est pas un détail cosmétique : le total d'un pilier
    (get_pillar_actuals) compte TOUTES les dépenses du pilier, pas seulement
    celles des catégories budgétées. Sans cette ligne, la somme des lignes
    affichées serait inférieure à la jauge juste au-dessus, sans explication
    visible.
    """
    progres = get_budget_progress(db, start, end)
    reels = get_pillar_actuals(db, start, end)

    enfants_par_parent: dict[int, list[Category]] = {}
    for c in db.execute(select(Category)).scalars().all():
        if c.parent_id is not None:
            enfants_par_parent.setdefault(c.parent_id, []).append(c)

    groupes: dict[str, dict] = {
        code: {
            "categories": [],
            "budget": Decimal("0.00"),
            "spent": Decimal("0.00"),
            "unbudgeted": Decimal("0.00"),
        }
        for code in PILLAR_ORDER
    }
    for ligne in progres:
        categorie = ligne["category"]
        pilier = resolve_budget_pillar(categorie, enfants_par_parent.get(categorie.id, []))
        groupes[pilier]["categories"].append(ligne)
        groupes[pilier]["budget"] += ligne["budget"]
        groupes[pilier]["spent"] += ligne["spent"]

    for code, groupe in groupes.items():
        # Ce qui a été dépensé dans le pilier sans passer par une catégorie
        # budgétée. Depuis que get_budget_progress n'attribue une dépense
        # qu'au pilier qui la compte, cet écart ne peut plus être négatif :
        # les deux lectures se réconcilient par construction. Le garde-fou
        # reste par prudence, mais il ne masque plus rien.
        reste = reels.get(code, Decimal("0.00")) - groupe["spent"]
        groupe["unbudgeted"] = reste if reste > 0 else Decimal("0.00")
        groupe["categories"].sort(key=lambda l: l["percentage"], reverse=True)
    return groupes


def resolve_budget_pillar(category: Category, enfants: list[Category]) -> str:
    """Pilier d'une catégorie qui PORTE UN BUDGET (donc une racine).

    `resolve_category_pillar` fait hériter du parent vers l'enfant. Il manque
    le sens inverse, et c'est celui dont on a besoin ici : un budget se pose
    toujours sur une racine, alors que le pilier est souvent renseigné sur
    les sous-catégories.

    Cas réel : « Impôts » n'a pas de pilier propre, mais ses trois
    sous-catégories sont toutes Essentiel. Résoudre la racine nue la faisait
    retomber sur le défaut (Choix) — l'écran de catégories affichait bien
    Essentiel via les enfants, et l'enveloppe du Cap comptait Choix. Deux
    lectures contradictoires des mêmes données.

    Règle : pilier propre s'il existe, sinon celui de la majorité des
    enfants qui en ont un, sinon le défaut. La majorité se compte en nombre
    d'enfants — simple et stable d'un mois sur l'autre ; une pondération par
    la dépense réelle serait plus fine mais changerait de résultat au gré
    des mois. Égalité tranchée par PILLAR_ORDER, pour un résultat
    déterministe.
    """
    if category.pillar:
        return category.pillar
    votes: dict[str, int] = {}
    for enfant in enfants:
        if enfant.pillar:
            votes[enfant.pillar] = votes.get(enfant.pillar, 0) + 1
    if votes:
        maximum = max(votes.values())
        for code in PILLAR_ORDER:
            if votes.get(code) == maximum:
                return code
    return resolve_category_pillar(category)


INCOME_SOURCES: list[tuple[str, str, str]] = [
    (
        "recettes_precedent",
        "Les recettes du mois précédent",
        "Le salaire tombe en fin de mois et finance le mois suivant.",
    ),
    (
        "recettes_courant",
        "Les recettes du mois en cours",
        "Le salaire arrive pendant le mois qu'il finance.",
    ),
    (
        "virements",
        "Les virements reçus sur un compte",
        "Un pot commun alimenté par virement — vous cochez ceux qui financent ce mois.",
    ),
    ("fixe", "Un montant fixe", "Enveloppe décidée à l'avance, revenu irrégulier."),
]
INCOME_SOURCE_CODES = {code for code, _, _ in INCOME_SOURCES}


def get_cap_settings(db: Session) -> CapSettings:
    """Réglages du rituel — ligne unique, créée si absente.

    La migration c3f8a1d20b56 l'insère, mais on ne s'y fie pas : une base
    restaurée depuis un export antérieur n'aurait pas la ligne.
    """
    settings = db.get(CapSettings, 1)
    if settings is None:
        settings = CapSettings(id=1, income_source="recettes_precedent")
        db.add(settings)
        db.commit()
    return settings


def get_incoming_transfers_since_last_cap(
    db: Session, month_start: date, account_id: int | None
) -> list[Transaction]:
    """Virements ENTRANTS candidats au financement du mois.

    Fenêtre : depuis le 1er du mois précédent. Volontairement large plutôt
    que « les N derniers jours » — aucune fenêtre automatique ne distingue
    de façon fiable un virement de fin de mois qui finance le mois suivant
    d'un rajout fait en cours de mois pour le mois courant. C'est
    précisément pourquoi le rituel les fait COCHER au lieu de les sommer :
    on propose la matière, l'utilisateur tranche.
    """
    if account_id is None:
        return []
    debut = _previous_month_start(month_start)
    _, fin = month_range(month_start.year, month_start.month)
    stmt = (
        select(Transaction)
        .where(
            Transaction.account_id == account_id,
            Transaction.date >= debut,
            Transaction.date <= fin,
            Transaction.amount > 0,
            Transaction.is_transfer.is_(True),
        )
        .order_by(Transaction.date.desc())
    )
    return list(db.execute(stmt).scalars().all())


def get_income_prefill(db: Session, month_start: date) -> Decimal:
    """Montant proposé pour « ressources du mois », selon le réglage.

    Ne sert QU'À PROPOSER : le champ reste modifiable, et c'est la valeur
    saisie (CapEntry.planned_income) que le suivi utilise. Le moteur ignore
    donc totalement d'où vient l'argent — seule cette fonction le sait.
    """
    settings = get_cap_settings(db)
    source = settings.income_source

    if source == "fixe":
        return settings.income_fixed_amount or Decimal("0.00")

    if source == "recettes_courant":
        _, fin = month_range(month_start.year, month_start.month)
        return get_income_total(db, month_start, fin)

    if source == "virements":
        # Rien de présélectionné : c'est la liste à cocher du rituel qui
        # construit le total (voir routers/cap.py).
        return Decimal("0.00")

    precedent = _previous_month_start(month_start)
    debut, fin = month_range(precedent.year, precedent.month)
    return get_income_total(db, debut, fin)


def get_cap_allocation(db: Session, month_start: date) -> dict[str, dict]:
    """Répartition proposée pour le rituel du Cap : 3 piliers, N catégories.

    Le plan est stocké par CATÉGORIE (table budgets) ; les trois piliers n'en
    sont que la somme (voir get_pillar_budget_sums). Cette fonction prépare
    l'écran qui permet de décider aux deux niveaux.

    Pré-remplissage, par catégorie et dans cet ordre :
      1. le budget du mois précédent — « comme le mois dernier », le chemin
         rapide demandé ;
      2. sinon la dépense habituelle (médiane 3 mois) — pour qu'un premier
         mois ne s'ouvre jamais sur des zéros ;
      3. sinon rien, la catégorie n'est pas proposée.

    Seules les catégories racines qui ont un budget le mois précédent OU un
    historique de dépense apparaissent : ça écarte naturellement les
    catégories de recettes (aucune dépense) sans avoir à les reconnaître,
    et ça garde la liste courte.
    """
    precedent = get_budgets_for_month(db, _previous_month_start(month_start))
    habituel = get_category_monthly_typical(db, month_start)

    groupes: dict[str, dict] = {
        code: {"categories": [], "total": Decimal("0.00")} for code in PILLAR_ORDER
    }
    enfants_par_parent: dict[int, list[Category]] = {}
    for c in db.execute(select(Category)).scalars().all():
        if c.parent_id is not None:
            enfants_par_parent.setdefault(c.parent_id, []).append(c)

    for categorie in get_top_level_categories(db):
        budget = precedent.get(categorie.id)
        typique = habituel.get(categorie.id, Decimal("0.00"))
        if budget is None and typique <= 0:
            continue
        montant = budget if budget is not None else typique
        pilier = resolve_budget_pillar(categorie, enfants_par_parent.get(categorie.id, []))
        groupes[pilier]["categories"].append(
            {
                "category": categorie,
                "prefill": montant,
                "typical": typique,
                "from_previous": budget is not None,
            }
        )
        groupes[pilier]["total"] += montant

    for groupe in groupes.values():
        groupe["categories"].sort(key=lambda ligne: ligne["prefill"], reverse=True)
    return groupes


def get_pillar_budget_sums(db: Session, month_start: date) -> dict[str, Decimal]:
    # Pré-remplissage de l'étape 2 du wizard : somme des budgets du mois
    # groupée par pilier RÉSOLU de chaque catégorie budgétée (un budget est
    # toujours posé sur une catégorie racine, voir get_budget_progress).
    stmt = (
        select(Category, func.sum(Budget.amount))
        .join(Budget, Budget.category_id == Category.id)
        .where(Budget.month == month_start)
        .group_by(Category.id)
    )
    sums = {"essentiel": Decimal("0.00"), "choix": Decimal("0.00"), "imprevu": Decimal("0.00")}
    enfants_par_parent: dict[int, list[Category]] = {}
    for c in db.execute(select(Category)).scalars().all():
        if c.parent_id is not None:
            enfants_par_parent.setdefault(c.parent_id, []).append(c)
    for category, total in db.execute(stmt).all():
        # Même règle que get_cap_allocation : un budget porté par une racine
        # sans pilier propre prend celui de ses sous-catégories.
        pillar = resolve_budget_pillar(category, enfants_par_parent.get(category.id, []))
        sums[pillar] = sums.get(pillar, Decimal("0.00")) + total
    return sums


def get_pillar_actuals(
    db: Session, start: date, end: date, account_id: int | None = None
) -> dict[str, Decimal]:
    # Dépenses réelles de la période, groupées par pilier résolu de chaque
    # transaction (is_unexpected prioritaire sur la catégorie — voir
    # resolve_transaction_pillar). Mêmes exclusions que get_budget_progress
    # (virements exclus, montants négatifs = dépenses).
    conditions = [
        Transaction.date >= start,
        Transaction.date <= end,
        Transaction.amount < 0,
        Transaction.is_transfer.is_(False),
    ]
    if account_id is not None:
        conditions.append(Transaction.account_id == account_id)
    stmt = (
        select(Transaction)
        .where(*conditions)
        .options(selectinload(Transaction.category).selectinload(Category.parent))
    )
    sums = {"essentiel": Decimal("0.00"), "choix": Decimal("0.00"), "imprevu": Decimal("0.00")}
    for transaction in db.execute(stmt).scalars().all():
        pillar = resolve_transaction_pillar(transaction)
        sums[pillar] = sums.get(pillar, Decimal("0.00")) + (-transaction.amount)
    return sums


def get_unexpected_transactions(db: Session, start: date, end: date) -> list[Transaction]:
    stmt = (
        select(Transaction)
        .where(
            Transaction.date >= start,
            Transaction.date <= end,
            Transaction.is_unexpected.is_(True),
        )
        .order_by(Transaction.date)
    )
    return list(db.execute(stmt).scalars().all())


def get_cap_entry_for_month(db: Session, month_start: date) -> CapEntry | None:
    stmt = select(CapEntry).where(CapEntry.month == month_start)
    return db.execute(stmt).scalar_one_or_none()


def get_previous_cap_entry(db: Session, month_start: date) -> CapEntry | None:
    return get_cap_entry_for_month(db, shift_month(month_start, -1))


def has_any_cap_entry(db: Session) -> bool:
    stmt = select(func.count()).select_from(CapEntry)
    return db.execute(stmt).scalar_one() > 0


def save_cap_entry(
    db: Session,
    month_start: date,
    *,
    planned_income: Decimal,
    planned_essentiel: Decimal,
    planned_choix: Decimal,
    planned_imprevu: Decimal,
    intention: str | None = None,
    reflection_unexpected: str | None = None,
    reflection_regret: str | None = None,
    reflection_proud: str | None = None,
    reflection_worked_well: str | None = None,
) -> CapEntry:
    # Upsert façon save_budgets : une ligne par mois, pas de contrainte
    # unique en base, appliquée ici en code.
    entry = get_cap_entry_for_month(db, month_start)
    if entry is None:
        entry = CapEntry(month=month_start)
        db.add(entry)
    entry.planned_income = planned_income
    entry.planned_essentiel = planned_essentiel
    entry.planned_choix = planned_choix
    entry.planned_imprevu = planned_imprevu
    entry.intention = intention
    entry.reflection_unexpected = reflection_unexpected
    entry.reflection_regret = reflection_regret
    entry.reflection_proud = reflection_proud
    entry.reflection_worked_well = reflection_worked_well
    db.commit()
    db.refresh(entry)
    return entry


def get_cap_entry_history(db: Session) -> list[CapEntry]:
    stmt = select(CapEntry).order_by(CapEntry.month)
    return list(db.execute(stmt).scalars().all())


# --- Page Rapports (/reports) ---


def get_full_history_start(db: Session) -> date | None:
    return db.execute(select(func.min(Transaction.date))).scalar_one_or_none()


def get_report_transactions_page(
    db: Session,
    start: date,
    end: date,
    account_id: int | None,
    *,
    positive: bool,
    category_id: int | None = None,
    exact_category_id: int | None = None,
    uncategorized: bool = False,
    page: int = 1,
    page_size: int = 25,
) -> tuple[list[Transaction], int]:
    # Liste complète (paginée) des opérations d'un onglet Dépenses/Recettes
    # du rapport — remplace l'ancien get_top_transactions (limité à 5).
    # Contrairement à get_category_transactions (category_id=None y
    # signifie "non catégorisé", pas "toutes"), ici category_id=None ET
    # exact_category_id=None ET uncategorized=False => aucun filtre
    # catégorie, on montre tout — c'est l'état "pas de drill-down" du donut.
    # category_id filtre la catégorie ET ses enfants (clic sur une
    # catégorie racine ou une sous-catégorie normale) ; exact_category_id
    # filtre une seule catégorie sans rollup enfants (clic sur le seau "Non
    # détaillé" du drill-down, qui doit exclure les vraies
    # sous-catégories) ; uncategorized cible les opérations sans catégorie
    # (clic sur le seau "Non catégorisé" du donut).
    sign_condition = Transaction.amount > 0 if positive else Transaction.amount < 0
    conditions = [
        Transaction.date >= start,
        Transaction.date <= end,
        sign_condition,
        Transaction.is_transfer.is_(False),
    ]
    if account_id is not None:
        conditions.append(Transaction.account_id == account_id)
    if uncategorized:
        conditions.append(Transaction.category_id.is_(None))
    elif exact_category_id is not None:
        conditions.append(Transaction.category_id == exact_category_id)
    elif category_id is not None:
        child_ids = [c.id for c in get_child_categories(db, category_id)]
        conditions.append(Transaction.category_id.in_([category_id, *child_ids]))

    total = db.execute(select(func.count()).select_from(Transaction).where(*conditions)).scalar_one()

    stmt = (
        select(Transaction)
        .options(selectinload(Transaction.account), selectinload(Transaction.category))
        .where(*conditions)
        .order_by(Transaction.date.desc(), Transaction.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    transactions = list(db.execute(stmt).scalars().all())
    return transactions, total


def get_report_transactions_all(
    db: Session,
    start: date,
    end: date,
    account_id: int | None,
    *,
    positive: bool,
    category_id: int | None = None,
    exact_category_id: int | None = None,
    uncategorized: bool = False,
) -> list[Transaction]:
    # Même filtre que get_report_transactions_page, sans pagination : pour
    # l'export CSV du tableau "Toutes les dépenses/recettes" d'un onglet du
    # rapport (voir routers/reports.py, export_report_transactions_csv), qui
    # doit exporter TOUT ce qui correspond aux filtres affichés, pas
    # seulement la page actuellement visible à l'écran.
    sign_condition = Transaction.amount > 0 if positive else Transaction.amount < 0
    conditions = [
        Transaction.date >= start,
        Transaction.date <= end,
        sign_condition,
        Transaction.is_transfer.is_(False),
    ]
    if account_id is not None:
        conditions.append(Transaction.account_id == account_id)
    if uncategorized:
        conditions.append(Transaction.category_id.is_(None))
    elif exact_category_id is not None:
        conditions.append(Transaction.category_id == exact_category_id)
    elif category_id is not None:
        child_ids = [c.id for c in get_child_categories(db, category_id)]
        conditions.append(Transaction.category_id.in_([category_id, *child_ids]))

    stmt = (
        select(Transaction)
        .options(selectinload(Transaction.account), selectinload(Transaction.category))
        .where(*conditions)
        .order_by(Transaction.date.desc(), Transaction.id.desc())
    )
    return list(db.execute(stmt).scalars().all())


def get_subcategory_breakdown(
    db: Session,
    start: date,
    end: date,
    parent_category_id: int,
    account_id: int | None = None,
    *,
    positive: bool,
) -> list[dict]:
    # Détail (drill-down) d'UNE catégorie de premier niveau déjà affichée
    # dans le donut du rapport : répartition par sous-catégorie, plus un seau
    # "Non détaillé" pour les transactions catégorisées directement sur le
    # parent (jamais sur une de ses sous-catégories).
    children = get_child_categories(db, parent_category_id)
    child_ids = [c.id for c in children]
    children_by_id = {c.id: c for c in children}

    sign_condition = Transaction.amount > 0 if positive else Transaction.amount < 0
    conditions = [
        Transaction.date >= start,
        Transaction.date <= end,
        sign_condition,
        Transaction.is_transfer.is_(False),
        Transaction.category_id.in_([parent_category_id, *child_ids]),
    ]
    if account_id is not None:
        conditions.append(Transaction.account_id == account_id)

    stmt = select(Transaction.category_id, Transaction.amount).where(*conditions)
    totals: dict[int, dict] = {}
    for category_id, amount in db.execute(stmt).all():
        magnitude = amount if positive else -amount
        child = children_by_id.get(category_id)
        key = category_id if child is not None else -1  # -1 = directement sur le parent
        name = child.name if child is not None else "Non détaillé"
        # child.icon peut être None (colonne nullable) même quand la
        # sous-catégorie existe bien : le ternaire précédent ne couvrait que
        # le cas "aucune sous-catégorie trouvée", pas "trouvée mais sans
        # icône" — Jinja affiche alors littéralement "None" (ex. "None
        # Électricité") au lieu de rien, {{ None }} n'étant jamais une
        # chaîne vide côté template.
        icon = (child.icon if child is not None else None) or "🏷️"
        entry = totals.setdefault(
            key,
            {
                "name": name,
                "icon": icon,
                "amount": Decimal("0.00"),
                # category_id=None pour "Non détaillé" (transactions posées
                # directement sur le parent) : le template s'en sert pour
                # filtrer la liste de transactions sans agréger les autres
                # sous-catégories (voir get_report_transactions_page,
                # exact_category_id).
                "category_id": category_id if child is not None else None,
            },
        )
        entry["amount"] += magnitude

    # Toutes les sous-catégories, même sans dépense sur la période (montant
    # à 0) : sinon on ne peut pas ouvrir l'évolution d'une facture
    # bimestrielle (gaz, eau...) le mois où elle n'est pas tombée.
    for child in children:
        totals.setdefault(
            child.id,
            {
                "name": child.name,
                "icon": child.icon or "🏷️",
                "amount": Decimal("0.00"),
                "category_id": child.id,
            },
        )

    rows = list(totals.values())
    rows.sort(key=lambda r: (-r["amount"], r["name"]))
    return rows


def get_cashflow_months(
    db: Session, months: list[tuple[date, date, str]], account_id: int | None = None
) -> list[dict]:
    # Alimente le graphique cashflow TOUJOURS visible du rapport (12 mois
    # glissants) : recettes/dépenses/net par mois, plus le top 3 des
    # catégories de dépense de chaque mois pour l'infobulle riche façon
    # Finary — un seul passage par mois plutôt qu'une requête séparée par
    # infobulle, ce nombre de mois étant toujours petit et fixe (12).
    result = []
    for start, end, label in months:
        income = get_income_total(db, start, end, account_id)
        expense = get_expense_total(db, start, end, account_id)
        top_categories = get_category_spending(db, start, end, account_id)[:3]
        # Le pendant en recettes : l'infobulle du graphique de flux affichait
        # le top DÉPENSES quelle que soit la barre survolée, y compris celle
        # des recettes (afterBody s'exécute une fois pour toute l'infobulle).
        top_income_categories = get_category_income(db, start, end, account_id)[:3]
        result.append(
            {
                "start": start,
                "end": end,
                "label": label,
                "income": income,
                "expense": expense,
                "net": income - expense,
                "top_categories": [
                    {"name": name, "amount": amount} for _, name, amount in top_categories
                ],
                "top_income_categories": [
                    {"name": name, "amount": amount} for _, name, amount in top_income_categories
                ],
            }
        )
    return result


def get_net_worth_series(
    db: Session, start: date, end: date, account_id: int | None = None, *, daily: bool = False
) -> dict:
    # Série cumulative du patrimoine entre start et end, un point par jour
    # (périodes courtes : Mois/Trimestre/Semestre) ou par mois (Année/
    # Personnalisé, généralement une plus longue période). Calculée en deux
    # requêtes agrégées (solde d'ouverture à `start`, puis mouvements par
    # compartiment) plutôt qu'une somme courante par transaction individuelle
    # — ce volume de points (quelques centaines maximum) reste largement
    # gérable en Python ensuite.
    accounts = [db.get(Account, account_id)] if account_id is not None else list_accounts(db)
    accounts = [a for a in accounts if a is not None]
    if not accounts:
        return {"accounts": [], "points": []}

    opening_conditions = [Transaction.date < start]
    if account_id is not None:
        opening_conditions.append(Transaction.account_id == account_id)
    opening_stmt = (
        select(Transaction.account_id, func.coalesce(func.sum(Transaction.amount), 0))
        .where(*opening_conditions)
        .group_by(Transaction.account_id)
    )
    opening_by_account = dict(db.execute(opening_stmt).all())

    bucket_unit = "day" if daily else "month"
    bucket_expr = func.date_trunc(bucket_unit, Transaction.date)
    bucket_conditions = [Transaction.date >= start, Transaction.date <= end]
    if account_id is not None:
        bucket_conditions.append(Transaction.account_id == account_id)
    bucket_stmt = (
        select(Transaction.account_id, bucket_expr, func.sum(Transaction.amount))
        .where(*bucket_conditions)
        .group_by(Transaction.account_id, bucket_expr)
    )
    deltas_by_account: dict[int, dict[date, Decimal]] = {}
    for acc_id, bucket, total in db.execute(bucket_stmt).all():
        deltas_by_account.setdefault(acc_id, {})[bucket.date()] = total

    buckets: list[date] = []
    if daily:
        cursor = start
        while cursor <= end:
            buckets.append(cursor)
            cursor += timedelta(days=1)
    else:
        cursor = date(start.year, start.month, 1)
        while cursor <= end:
            buckets.append(cursor)
            y, m = cursor.year, cursor.month + 1
            if m == 13:
                y, m = y + 1, 1
            cursor = date(y, m, 1)

    running = {
        account.id: account.balance + opening_by_account.get(account.id, Decimal("0.00"))
        for account in accounts
    }
    points = []
    for bucket in buckets:
        per_account = {}
        total = Decimal("0.00")
        for account in accounts:
            delta = deltas_by_account.get(account.id, {}).get(bucket, Decimal("0.00"))
            running[account.id] += delta
            per_account[account.id] = running[account.id]
            total += running[account.id]
        points.append({"date": bucket, "accounts": per_account, "total": total})

    return {"accounts": accounts, "points": points}


def compute_twiga_score(db: Session, start: date, end: date, account_id: int | None = None) -> dict:
    # Score "fun" 0-100 sur la période sélectionnée : budgets respectés (40),
    # résultat positif (30), tout catégorisé (20), projets dans les temps
    # (10). Un critère sans donnée applicable (aucun budget/aucune
    # transaction/aucun projet sur la période) obtient le plein score de son
    # critère plutôt qu'un 0 — on ne pénalise jamais l'absence de ce qu'il
    # n'y a rien à respecter.
    budget_progress = get_budget_progress(db, start, end, account_id)
    if budget_progress:
        respected = sum(1 for item in budget_progress if item["percentage"] <= 100)
        budget_points = round(40 * respected / len(budget_progress))
    else:
        budget_points = 40

    income_total = get_income_total(db, start, end, account_id)
    expense_total = get_expense_total(db, start, end, account_id)
    result_points = 30 if (income_total - expense_total) >= 0 else 0

    tx_conditions = [
        Transaction.date >= start,
        Transaction.date <= end,
        Transaction.is_transfer.is_(False),
    ]
    if account_id is not None:
        tx_conditions.append(Transaction.account_id == account_id)
    total_tx = db.execute(select(func.count()).select_from(Transaction).where(*tx_conditions)).scalar_one()
    if total_tx:
        categorized_tx = db.execute(
            select(func.count())
            .select_from(Transaction)
            .where(*tx_conditions, Transaction.category_id.is_not(None))
        ).scalar_one()
        categorized_points = round(20 * categorized_tx / total_tx)
    else:
        categorized_points = 20

    projects = list_projects(db)
    if projects:
        on_track = 0
        period_months = max(Decimal("1"), Decimal((end - start).days + 1) / Decimal("30.44"))
        for project in projects:
            months_remaining = max(
                1, (project.target_date.year - end.year) * 12 + (project.target_date.month - end.month)
            )
            required_monthly = max(
                Decimal("0.00"), (project.target_amount - project.current_amount) / months_remaining
            )
            required_for_period = required_monthly * period_months
            saved_stmt = select(func.coalesce(func.sum(ProjectMovement.amount), 0)).where(
                ProjectMovement.project_id == project.id,
                ProjectMovement.date >= start,
                ProjectMovement.date <= end,
            )
            saved = db.execute(saved_stmt).scalar_one()
            if required_for_period <= 0 or saved >= required_for_period:
                on_track += 1
        project_points = round(10 * on_track / len(projects))
    else:
        project_points = 10

    total_score = budget_points + result_points + categorized_points + project_points

    if total_score >= 90:
        message = "🦒 La girafe est fière de toi !"
    elif total_score >= 70:
        message = "🦒 Tu tiens le bon bout !"
    elif total_score >= 50:
        message = "🦒 Twiga tend le cou pour voir mieux..."
    else:
        message = "🦒 Aïe, trop de feuilles mangées ce mois-ci !"

    return {
        "score": total_score,
        "budget_points": budget_points,
        "result_points": result_points,
        "categorized_points": categorized_points,
        "project_points": project_points,
        "message": message,
    }


def list_projects(db: Session) -> list[Project]:
    return list(db.execute(select(Project).order_by(Project.target_date)).scalars().all())


def create_project(
    db: Session, name: str, target_amount: Decimal, target_date: date, current_amount: Decimal
) -> Project:
    project = Project(
        name=name,
        target_amount=target_amount,
        target_date=target_date,
        current_amount=current_amount,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def update_project(
    db: Session,
    project: Project,
    name: str,
    target_amount: Decimal,
    target_date: date,
    current_amount: Decimal,
) -> Project:
    project.name = name
    project.target_amount = target_amount
    project.target_date = target_date
    project.current_amount = current_amount
    db.commit()
    db.refresh(project)
    return project


def delete_project(db: Session, project: Project) -> None:
    db.delete(project)
    db.commit()


def compute_monthly_effort(
    target_amount: Decimal, current_amount: Decimal, target_date: date, today: date
) -> Decimal:
    remaining = target_amount - current_amount
    if remaining <= 0:
        return Decimal("0.00")

    months_remaining = (target_date.year - today.year) * 12 + (target_date.month - today.month)
    months_remaining = max(months_remaining, 1)
    return (remaining / months_remaining).quantize(Decimal("0.01"))


def get_project_movements(db: Session, project_id: int, limit: int = 10) -> list[ProjectMovement]:
    stmt = (
        select(ProjectMovement)
        .where(ProjectMovement.project_id == project_id)
        .order_by(ProjectMovement.date.desc(), ProjectMovement.id.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def add_project_funds(
    db: Session, project: Project, amount: Decimal, note: str | None
) -> Project:
    project.current_amount = project.current_amount + amount
    db.add(ProjectMovement(project_id=project.id, date=date.today(), amount=amount, note=note))
    db.commit()
    db.refresh(project)
    return project


def spend_project_funds(
    db: Session, project: Project, amount: Decimal, note: str | None
) -> Project:
    project.current_amount = project.current_amount - amount
    db.add(ProjectMovement(project_id=project.id, date=date.today(), amount=-amount, note=note))
    db.commit()
    db.refresh(project)
    return project


def _category_and_descendant_ids(db: Session, category_id: int) -> list[int]:
    categories = db.execute(select(Category)).scalars().all()
    ids = [category_id]
    ids.extend(c.id for c in categories if c.parent_id == category_id)
    return ids


def get_child_categories(db: Session, parent_id: int) -> list[Category]:
    stmt = select(Category).where(Category.parent_id == parent_id).order_by(Category.name)
    return list(db.execute(stmt).scalars().all())


def resolve_top_level_category(category: Category | None) -> Category | None:
    if category is None:
        return None
    while category.parent is not None:
        category = category.parent
    return category


_DEFAULT_PILLAR = "choix"


def resolve_category_pillar(category: Category | None) -> str:
    # Un seul niveau de remontée (pas de boucle façon resolve_top_level_category) :
    # les catégories de cette appli n'ont que 2 niveaux utiles pour "Le Cap"
    # (racine + sous-catégorie) — une sous-catégorie sans pilier propre
    # hérite de son parent direct, qui porte lui-même sa propre valeur
    # résolue (jamais NULL implicite plus haut dans l'arbre). Défaut "choix"
    # si rien n'est défini nulle part, jamais une exception : cette fonction
    # doit toujours renvoyer une valeur utilisable pour agréger.
    if category is None:
        return _DEFAULT_PILLAR
    if category.pillar:
        return category.pillar
    if category.parent is not None and category.parent.pillar:
        return category.parent.pillar
    return _DEFAULT_PILLAR


def resolve_transaction_pillar(transaction: Transaction) -> str:
    # Priorité 1 : is_unexpected l'emporte toujours sur la catégorie, quelle
    # qu'elle soit (voir Transaction.is_unexpected) — une dépense taguée
    # imprévue reste 🆘 même si sa catégorie est par ailleurs 🏠 Essentiel.
    if transaction.is_unexpected:
        return "imprevu"
    return resolve_category_pillar(transaction.category)


def _build_transaction_filter_conditions(
    db: Session,
    *,
    account_id: int | None = None,
    category_id: int | None = None,
    category_exact: bool = False,
    uncategorized_only: bool = False,
    start: date | None = None,
    end: date | None = None,
    type_filter: str | None = None,
    search: str | None = None,
    amount_min: Decimal | None = None,
    amount_max: Decimal | None = None,
    payment_method: str | None = None,
) -> list:
    conditions = []
    if account_id is not None:
        conditions.append(Transaction.account_id == account_id)
    if uncategorized_only:
        conditions.append(Transaction.category_id.is_(None))
    elif category_id is not None:
        if category_exact:
            conditions.append(Transaction.category_id == category_id)
        else:
            conditions.append(
                Transaction.category_id.in_(_category_and_descendant_ids(db, category_id))
            )
    if start is not None:
        conditions.append(Transaction.date >= start)
    if end is not None:
        conditions.append(Transaction.date <= end)
    if type_filter == "income":
        conditions.append(Transaction.amount > 0)
        conditions.append(Transaction.is_transfer.is_(False))
    elif type_filter == "expense":
        conditions.append(Transaction.amount < 0)
        conditions.append(Transaction.is_transfer.is_(False))
    elif type_filter == "transfer":
        conditions.append(Transaction.is_transfer.is_(True))
    if search:
        conditions.append(Transaction.label.ilike(f"%{search}%"))
    # Filtre sur la valeur ABSOLUE du montant : un utilisateur qui tape
    # "min 20 / max 100" pense à l'ampleur d'une dépense ou d'une recette,
    # pas au signe (même raisonnement que le tri par montant, voir
    # _TRANSACTION_SORT_ORDERS) — sans ça, "min 20" exclurait à tort toutes
    # les dépenses (négatives, donc "inférieures" à 20 au sens signé).
    if amount_min is not None:
        conditions.append(func.abs(Transaction.amount) >= amount_min)
    if amount_max is not None:
        conditions.append(func.abs(Transaction.amount) <= amount_max)
    if payment_method:
        conditions.append(Transaction.payment_method == payment_method)
    return conditions


_TRANSACTION_SORT_ORDERS = {
    "date_desc": (Transaction.date.desc(), Transaction.id.desc()),
    "date_asc": (Transaction.date.asc(), Transaction.id.asc()),
    # Tri par AMPLEUR (valeur absolue), pas par valeur signée : "décroissant"
    # doit montrer la plus grosse dépense OU la plus grosse recette en
    # premier, peu importe le signe — pas simplement la valeur numérique la
    # plus haute (qui mettrait -1€ avant -500€, contre-intuitif pour une
    # dépense).
    "amount_desc": (func.abs(Transaction.amount).desc(), Transaction.id.desc()),
    "amount_asc": (func.abs(Transaction.amount).asc(), Transaction.id.desc()),
}


def list_transactions(
    db: Session,
    *,
    account_id: int | None = None,
    category_id: int | None = None,
    category_exact: bool = False,
    uncategorized_only: bool = False,
    start: date | None = None,
    end: date | None = None,
    type_filter: str | None = None,
    search: str | None = None,
    amount_min: Decimal | None = None,
    amount_max: Decimal | None = None,
    payment_method: str | None = None,
    sort: str = "date_desc",
    page: int = 1,
    page_size: int = 25,
) -> tuple[list[Transaction], int]:
    conditions = _build_transaction_filter_conditions(
        db,
        account_id=account_id,
        category_id=category_id,
        category_exact=category_exact,
        uncategorized_only=uncategorized_only,
        start=start,
        end=end,
        type_filter=type_filter,
        search=search,
        amount_min=amount_min,
        amount_max=amount_max,
        payment_method=payment_method,
    )

    count_stmt = select(func.count()).select_from(Transaction).where(*conditions)
    total = db.execute(count_stmt).scalar_one()

    order_by = _TRANSACTION_SORT_ORDERS.get(sort, _TRANSACTION_SORT_ORDERS["date_desc"])
    stmt = (
        select(Transaction)
        .options(selectinload(Transaction.account), selectinload(Transaction.category))
        .where(*conditions)
        .order_by(*order_by)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    transactions = list(db.execute(stmt).scalars().all())
    return transactions, total


def get_transactions_total_amount(
    db: Session,
    *,
    account_id: int | None = None,
    category_id: int | None = None,
    category_exact: bool = False,
    uncategorized_only: bool = False,
    start: date | None = None,
    end: date | None = None,
    type_filter: str | None = None,
    search: str | None = None,
    amount_min: Decimal | None = None,
    amount_max: Decimal | None = None,
    payment_method: str | None = None,
) -> Decimal:
    conditions = _build_transaction_filter_conditions(
        db,
        account_id=account_id,
        category_id=category_id,
        category_exact=category_exact,
        uncategorized_only=uncategorized_only,
        start=start,
        end=end,
        type_filter=type_filter,
        search=search,
        amount_min=amount_min,
        amount_max=amount_max,
        payment_method=payment_method,
    )
    stmt = select(func.coalesce(func.sum(Transaction.amount), 0)).where(*conditions)
    return db.execute(stmt).scalar_one()


def group_transactions_by_date(transactions: list[Transaction]) -> list[dict]:
    # Regroupe une liste déjà triée en groupes par jour, avec un intitulé
    # long en français ("mercredi 5 août 2026") pour l'en-tête de section de
    # la liste des opérations. L'ORDRE des groupes suit le premier élément
    # rencontré pour chaque date (dict Python = ordre d'insertion) : correct
    # avec un tri par date, mais un tri par montant peut entrelacer les
    # groupes différemment — sans jamais perdre ni dupliquer de ligne.
    groups: dict[date, list[Transaction]] = {}
    for transaction in transactions:
        groups.setdefault(transaction.date, []).append(transaction)
    return [
        {"date": day, "label": format_date_long_fr(day), "transactions": txs}
        for day, txs in groups.items()
    ]


def update_transaction(
    db: Session,
    transaction: Transaction,
    label: str,
    category: Category | None,
    amount: Decimal,
    transaction_date: date,
    account: Account,
    is_transfer: bool,
    payment_method: str | None = None,
    note: str | None = None,
    is_unexpected: bool = False,
) -> Transaction:
    transaction.label = label
    transaction.category_id = category.id if category else None
    transaction.amount = amount
    transaction.date = transaction_date
    transaction.account_id = account.id
    transaction.is_transfer = is_transfer
    transaction.is_unexpected = is_unexpected
    if is_transfer or category is not None:
        # Même règle que categorize_transaction() / bulk_update_transactions()
        # : assigner une catégorie (ou marquer un virement) depuis le
        # formulaire d'édition d'une opération individuelle doit la valider,
        # exactement comme la catégorisation depuis La Savane ou la barre de
        # sélection groupée — sans ce couplage, catégoriser une opération
        # encore en attente directement depuis Opérations la laissait
        # validated=False malgré sa catégorie, et elle continuait donc
        # d'apparaître dans La Savane.
        #
        # Volontairement asymétrique : category=None ne repasse PAS
        # validated à False (pas de retour silencieux vers La Savane au
        # simple effacement de la catégorie) — "📥 Savane" reste la seule
        # action explicite pour ça, même principe que bulk_update_transactions.
        transaction.validated = True
    # Champs du formulaire au même titre que les autres (contrairement à
    # categorize_transaction, où payment_method n'est appliqué que s'il est
    # fourni) : les vider doit pouvoir effacer une valeur existante.
    transaction.payment_method = payment_method
    transaction.note = note.strip() if note and note.strip() else None
    db.commit()
    db.refresh(transaction)
    if category is not None:
        _maybe_add_receipt_family_line(db, transaction, category)
    return transaction


def create_manual_transaction(
    db: Session,
    label: str,
    category: Category | None,
    amount: Decimal,
    transaction_date: date,
    account: Account,
    is_transfer: bool,
    payment_method: str | None = None,
    note: str | None = None,
) -> Transaction:
    # Saisie manuelle (régularisation, achat en espèces...) : jamais issue
    # d'un import, donc pas de libellé "brut" distinct — raw_label reprend
    # le libellé saisi. validated=True d'emblée : contrairement à un import,
    # l'utilisateur catégorise déjà tout en la créant, elle n'a pas besoin de
    # repasser par La Savane.
    transaction = Transaction(
        label=label,
        raw_label=label,
        category_id=category.id if category else None,
        amount=amount,
        date=transaction_date,
        account_id=account.id,
        is_transfer=is_transfer,
        payment_method=payment_method,
        note=note.strip() if note and note.strip() else None,
        validated=True,
    )
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    return transaction


def delete_transaction(db: Session, transaction: Transaction) -> None:
    db.delete(transaction)
    db.commit()


def bulk_delete_transactions(db: Session, transactions: list[Transaction]) -> int:
    count = len(transactions)
    for transaction in transactions:
        db.delete(transaction)
    db.commit()
    return count


def unvalidate_transaction(db: Session, transaction: Transaction) -> Transaction:
    transaction.validated = False
    db.commit()
    db.refresh(transaction)
    return transaction


def bulk_unvalidate_transactions(db: Session, transactions: list[Transaction]) -> int:
    for transaction in transactions:
        transaction.validated = False
    db.commit()
    return len(transactions)


def bulk_mark_as_transfer(db: Session, transactions: list[Transaction]) -> int:
    for transaction in transactions:
        _tag_as_transfer(transaction)
    db.commit()
    return len(transactions)


def mark_transaction_unexpected(db: Session, transaction: Transaction) -> Transaction:
    transaction.is_unexpected = True
    db.commit()
    db.refresh(transaction)
    return transaction


def bulk_mark_as_unexpected(db: Session, transactions: list[Transaction]) -> int:
    for transaction in transactions:
        transaction.is_unexpected = True
    db.commit()
    return len(transactions)


def bulk_unmark_transfer(db: Session, transactions: list[Transaction]) -> int:
    # Renvoyée dans La Savane (validated=False) : ce n'était pas vraiment un
    # virement, elle a donc besoin d'une vraie catégorie de dépense/recette.
    for transaction in transactions:
        transaction.is_transfer = False
        transaction.validated = False
    db.commit()
    return len(transactions)


# --- Routine mensuelle ---


def get_or_create_app_state(db: Session) -> AppState:
    state = db.get(AppState, 1)
    if state is None:
        state = AppState(id=1, last_routine_month=None)
        db.add(state)
        db.commit()
        db.refresh(state)
    return state


def mark_routine_seen(db: Session, month_start: date) -> None:
    state = get_or_create_app_state(db)
    state.last_routine_month = month_start
    db.commit()


def set_session_secret(db: Session, session_secret: str) -> None:
    # Persiste le secret de signature des cookies de session (voir
    # backend/auth.py, load_session_secret) : généré une seule fois au tout
    # premier démarrage, partagé par TOUTES les sessions de TOUS les
    # utilisateurs — indépendant de tout mot de passe individuel désormais
    # (voir User, l'authentification est multi-utilisateur).
    state = get_or_create_app_state(db)
    state.session_secret = session_secret
    db.commit()


# --- Utilisateurs (authentification multi-utilisateur) ---


def get_user(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def get_user_by_username(db: Session, username: str) -> User | None:
    return db.execute(select(User).where(User.username == username)).scalar_one_or_none()


def list_users(db: Session) -> list[User]:
    return list(db.execute(select(User).order_by(User.username)).scalars().all())


def create_user(db: Session, username: str, password: str, role: str) -> User:
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    user = User(
        username=username,
        hashed_password=hashed,
        role=role,
        is_active=True,
        created_at=datetime.utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user_profile(
    db: Session, user_id: int, display_name: str, username: str
) -> str | None:
    # Auto-service (voir routers/profile.py) : l'utilisateur modifie SON
    # PROPRE nom affiché/nom d'utilisateur, jamais son rôle ni celui d'un
    # autre (ça reste réservé à l'admin via routers/users.py). Renvoie un
    # message d'erreur (str) si échec, None si succès — même convention que
    # les routes qui appellent cette fonction pour construire leur réponse.
    user = get_user(db, user_id)
    if user is None:
        return "Utilisateur introuvable."
    username = username.strip()
    if not username:
        return "Le nom d'utilisateur est obligatoire."
    existing = get_user_by_username(db, username)
    if existing is not None and existing.id != user_id:
        return f'Un utilisateur "{username}" existe déjà.'
    user.username = username
    user.display_name = display_name.strip() or None
    db.commit()
    return None


def set_user_role(db: Session, user_id: int, role: str) -> None:
    user = get_user(db, user_id)
    if user is None:
        return
    user.role = role
    db.commit()


def set_user_password(db: Session, user_id: int, password: str) -> None:
    user = get_user(db, user_id)
    if user is None:
        return
    user.hashed_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    db.commit()


def set_user_active(db: Session, user_id: int, is_active: bool) -> None:
    user = get_user(db, user_id)
    if user is None:
        return
    user.is_active = is_active
    db.commit()


def delete_user(db: Session, user_id: int) -> None:
    user = get_user(db, user_id)
    if user is None:
        return
    db.delete(user)
    db.commit()


def touch_last_login(db: Session, user_id: int) -> None:
    user = get_user(db, user_id)
    if user is None:
        return
    user.last_login = datetime.utcnow()
    db.commit()


def get_overall_budget_consumption(db: Session, start: date, end: date) -> Decimal:
    progress = get_budget_progress(db, start, end)
    if not progress:
        return Decimal("0")

    total_spent = sum((item["spent"] for item in progress), Decimal("0.00"))
    total_budget = sum((item["budget"] for item in progress), Decimal("0.00"))
    if total_budget == 0:
        return Decimal("0")
    return total_spent / total_budget * 100


def get_monthly_project_savings(db: Session, start: date, end: date) -> Decimal:
    stmt = select(func.coalesce(func.sum(ProjectMovement.amount), 0)).where(
        ProjectMovement.date >= start, ProjectMovement.date <= end
    )
    return db.execute(stmt).scalar_one()


def detect_subscriptions(db: Session, today: date, lookback_months: int = 6) -> list[dict]:
    # Heuristique : même libellé (normalisé), présent sur au moins 2 mois
    # calendaires différents, montants tous à ±5% de leur moyenne. Ne
    # regarde que les dépenses (un abonnement est toujours une dépense).
    start_year, start_month = today.year, today.month - lookback_months
    while start_month <= 0:
        start_month += 12
        start_year -= 1
    lookback_start = date(start_year, start_month, 1)

    stmt = (
        select(Transaction)
        .where(
            Transaction.date >= lookback_start,
            Transaction.date <= today,
            Transaction.amount < 0,
            Transaction.is_transfer.is_(False),
        )
        .order_by(Transaction.date)
    )
    transactions = db.execute(stmt).scalars().all()

    groups: dict[str, list[Transaction]] = {}
    for tx in transactions:
        key = tx.label.strip().lower()
        if key:
            groups.setdefault(key, []).append(tx)

    subscriptions = []
    for txs in groups.values():
        months_seen = {(t.date.year, t.date.month) for t in txs}
        if len(months_seen) < 2:
            continue

        amounts = [abs(t.amount) for t in txs]
        average = sum(amounts) / len(amounts)
        if average == 0:
            continue

        tolerance = Decimal("0.05")
        if all(abs(amount - average) / average <= tolerance for amount in amounts):
            subscriptions.append(
                {
                    "label": txs[-1].label,
                    "amount": average.quantize(Decimal("0.01")),
                    "occurrences": len(txs),
                }
            )

    return subscriptions


# --- Catégorisation en masse du backlog ---


def _backlog_conditions() -> list:
    # Une transaction "Rejetée" dans le backlog (reject_from_backlog) doit
    # sortir de cette vue — sinon elle réapparaîtrait à l'identique juste
    # après avoir été rejetée, comme si le clic n'avait rien fait. Filtre sur
    # backlog_rejected_at, PAS skipped_at ("Passer" dans La Savane) : les
    # deux actions sont distinctes, voir le commentaire sur
    # Transaction.backlog_rejected_at dans models.py.
    return [
        Transaction.validated.is_(False),
        Transaction.is_transfer.is_(False),
        Transaction.backlog_rejected_at.is_(None),
    ]


def get_backlog_transactions(db: Session) -> list[Transaction]:
    stmt = (
        select(Transaction)
        .options(selectinload(Transaction.account))
        .where(*_backlog_conditions())
        .order_by(Transaction.date, Transaction.id)
    )
    return list(db.execute(stmt).scalars().all())


def count_backlog_transactions(db: Session) -> int:
    # Requête bon marché utilisée comme détecteur de péremption du cache de
    # suggestions côté routeur : si ce compte change (import, validation ou
    # rejet fait ailleurs que via le backlog...), le cache est reconstruit.
    stmt = select(func.count()).select_from(Transaction).where(*_backlog_conditions())
    return db.execute(stmt).scalar_one()


def get_categorized_label_samples(db: Session, limit: int = 600) -> list[tuple[str, str, int]]:
    # Échantillon des libellés déjà catégorisés, dédupliqué par raw_label
    # (un même commerçant génère souvent des centaines de lignes identiques)
    # pour garder le calcul de similarité rapide même sur un gros historique
    # (le backlog compare CHAQUE transaction en attente à CET échantillon :
    # avec plusieurs milliers de transactions des deux côtés, le limit ci-
    # dessus borne le coût à du raisonnable — voir suggest_backlog_category).
    # Les plus récents d'abord : en cas de doublon de raw_label catégorisé
    # différemment par le passé, on garde la catégorisation la plus récente
    # (et un commerçant récent est aussi plus représentatif du format de
    # libellé actuel de la banque, qui peut changer avec le temps).
    stmt = (
        select(Transaction.raw_label, Transaction.label, Transaction.category_id)
        .where(
            Transaction.validated.is_(True),
            Transaction.category_id.is_not(None),
            Transaction.is_transfer.is_(False),
        )
        .order_by(Transaction.id.desc())
        .limit(limit)
    )
    rows = db.execute(stmt).all()

    seen: set[str] = set()
    samples: list[tuple[str, str, int]] = []
    for raw_label, label, category_id in rows:
        # Normalisé une seule fois ici plutôt qu'à chaque comparaison dans
        # suggest_backlog_category, qui est appelée une fois par transaction
        # en attente et reboucle sur tout cet échantillon à chaque fois.
        key = raw_label.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        samples.append((key, label, category_id))
    return samples


# En dessous de ce ratio, la meilleure correspondance trouvée est trop
# faible pour être une suggestion utile : mieux vaut ne rien proposer.
# Seuil relevé de 0.35 à 0.50 en même temps que le passage d'une similarité
# caractère par caractère à une similarité mot à mot (voir
# _significant_words) : 0.35 sur des chaînes brutes laissait passer
# n'importe quoi, puisque deux libellés bancaires sans aucun rapport
# partagent déjà la moitié de leurs caractères rien qu'avec l'habillage de
# la banque ("CARTE JJ/MM/AA ... CB*NNNN", "VIR SEPA ...").
BACKLOG_SUGGESTION_THRESHOLD = 0.50

# Mots à ignorer pour rapprocher deux libellés : l'habillage bancaire et les
# civilités ne désignent aucun commerçant. Réutilise les listes déjà
# constituées pour les suggestions de règles, sans les modifier (elles ont
# leur propre sémantique là-bas), et y ajoute ce qui est spécifique au
# rapprochement de libellés.
# Construit à la première utilisation et non à l'import : les deux listes
# réutilisées sont définies plus bas dans ce fichier.
@lru_cache(maxsize=1)
def _matching_stopwords() -> frozenset[str]:
    return frozenset(
        _GENERIC_RULE_TERMS
        | _GENERIC_RULE_FILLER_WORDS
        | {"WEB", "INST", "DEPUIS", "VERS", "MADAME", "MONSIEUR", "MME", "MLLE", "COMPTE"}
    )


@lru_cache(maxsize=4096)
def _significant_words(raw_label: str) -> frozenset[str]:
    # Ne garde que ce qui identifie réellement un commerçant : les chiffres
    # (dates, numéros de carte, références d'échéance) et l'habillage de la
    # banque sont retirés. Sans ça, "CARTE 09/12/24 MICROSOFT CB*1264" et
    # "CARTE 07/08/26 AL JARO VO CB*1264" se ressemblent à 60 % alors
    # qu'elles n'ont rien en commun.
    text = re.sub(r"\d+", " ", raw_label.upper())
    text = re.sub(r"[^A-ZÀ-ÖØ-Ý]+", " ", text)
    stopwords = _matching_stopwords()
    return frozenset(w for w in text.split() if len(w) >= 3 and w not in stopwords)


def _shared_word_count(target: frozenset[str], sample: frozenset[str]) -> int:
    # Égalité stricte, ou préfixe commun d'au moins 4 lettres pour rattraper
    # les variantes d'un même commerçant ("ACME" / "ACMEPRESSE").
    count = 0
    for word in target:
        if word in sample or any(
            len(other) >= 4 and len(word) >= 4 and (other.startswith(word) or word.startswith(other))
            for other in sample
        ):
            count += 1
    return count


def suggest_backlog_category(
    transaction: Transaction,
    samples: list[tuple[str, str, int]],
    categories_by_id: dict[int, Category],
) -> dict | None:
    if not transaction.raw_label.strip():
        return None

    # Similarité MOT À MOT sur les seuls mots signifiants, et non plus
    # caractère par caractère sur la chaîne brute. Un mot signifiant en
    # commun est exigé : sans ce garde-fou, "CLUB DE TENNIS DE LYON" était
    # rapproché de "VIR SEPA C.P.A.M. DE LYON" (46 %) sur le seul "LYON",
    # et un virement de Livret A était suggéré en "Salaire net" parce que
    # les deux libellés contenaient "Virement".
    target_words = _significant_words(transaction.raw_label)
    if not target_words:
        return None

    best_ratio = 0.0
    best_sample: tuple[str, int] | None = None
    for raw_label, label, category_id in samples:
        sample_words = _significant_words(raw_label)
        if not sample_words:
            continue
        shared = _shared_word_count(target_words, sample_words)
        if not shared:
            continue
        # Jaccard : les mots communs rapportés à l'ensemble des mots des deux
        # libellés, pour qu'un libellé très long ne matche pas un libellé
        # court sur un seul mot partagé.
        ratio = shared / (len(target_words) + len(sample_words) - shared)
        if ratio > best_ratio:
            best_ratio = ratio
            best_sample = (label, category_id)
            if best_ratio == 1.0:
                break

    if best_sample is None or best_ratio < BACKLOG_SUGGESTION_THRESHOLD:
        return None

    based_on_label, category_id = best_sample
    category = categories_by_id.get(category_id)
    if category is None:
        return None

    return {
        "category": category,
        "based_on_label": based_on_label,
        "confidence": round(best_ratio * 100),
    }


def suggest_category_with_confidence(db: Session, transaction: Transaction) -> dict | None:
    # Source de suggestion unique pour La Savane (une transaction à la
    # fois) : une règle explicite (mot-clé défini par l'utilisateur) prime
    # toujours sur la similarité floue et vaut une confiance de 100 %
    # puisqu'elle a été choisie déliberément ; sinon on retombe sur le même
    # moteur que la catégorisation de masse (suggest_backlog_category), pour
    # que les deux fonctionnalités partagent la même intelligence plutôt que
    # deux logiques divergentes.
    matched_rule = find_matching_rule(db, transaction.raw_label)
    if matched_rule is not None:
        return {"category": matched_rule.category, "based_on_label": None, "confidence": 100}

    samples = get_categorized_label_samples(db)
    categories_by_id = {c.id: c for c in db.execute(select(Category)).scalars().all()}
    return suggest_backlog_category(transaction, samples, categories_by_id)


# Moyens de paiement / intermédiaires génériques : un libellé qui ne
# contient QUE ça ne désigne aucun commerçant précis (un même "Paypal" ou
# "Chèque émis" recouvre des achats de nature totalement différente d'une
# fois sur l'autre). Une règle basée dessus matcherait large et mal
# catégoriserait les prochaines transactions au lieu de bien faire — donc
# jamais de suggestion de règle pour ces libellés-là. Repris en partie de
# backend.payment_methods._DETECTION_RULES (mêmes mots-clés bruts), plus
# PayPal (jamais un moyen de paiement à part entière dans cette appli, mais
# tout aussi générique pour cet usage) et EMIS (systématique sur "CHEQUE
# EMIS <numéro>", jamais un commerçant).
_GENERIC_RULE_TERMS = {
    "PAYPAL",
    "CARTE",
    "CB",
    "TPE",
    "CHEQUE",
    "CHQ",
    "CHEQ",
    "EMIS",
    "VIREMENT",
    "VIR",
    "PRELEVEMENT",
    "PRELVT",
    "PRLV",
    "SEPA",
    "RETRAIT",
    "DAB",
    "GAB",
    "ESPECES",
    "AVOIR",
    "REMBOURSEMENT",
}
# Bruit d'habillage (raison sociale, glue grammaticale) qui entoure souvent
# ces libellés génériques sans jamais désigner un commerçant identifiable
# (ex. "PayPal Europe S.a.r.l. et Cie S.", "VIR SEPA PayPal").
_GENERIC_RULE_FILLER_WORDS = {
    "EUROPE",
    "ET",
    "DE",
    "DU",
    "LA",
    "LE",
    "S",
    "A",
    "R",
    "L",
    "SA",
    "SARL",
    "SAS",
    "CIE",
}


def _is_generic_rule_keyword(keyword: str | None) -> bool:
    words = re.findall(r"[^\W\d_]+", (keyword or "").upper())
    if not words:
        return True
    allowed = _GENERIC_RULE_TERMS | _GENERIC_RULE_FILLER_WORDS
    return all(word in allowed for word in words)


def record_rule_suggestion(db: Session, keyword: str, category_id: int) -> RuleSuggestion | None:
    """Mémorise une proposition de règle, ou incrémente son compteur.

    Renvoie None si la proposition a déjà été refusée : un « Non merci »
    vaut pour de bon, sinon la même suggestion reviendrait à chaque
    catégorisation du même libellé.
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return None
    existante = db.execute(
        select(RuleSuggestion).where(
            func.lower(RuleSuggestion.keyword) == keyword.lower(),
            RuleSuggestion.category_id == category_id,
        )
    ).scalars().first()
    if existante is not None:
        if existante.dismissed:
            return None
        existante.occurrences += 1
        db.commit()
        return existante
    suggestion = RuleSuggestion(keyword=keyword, category_id=category_id)
    db.add(suggestion)
    db.commit()
    return suggestion


def list_pending_rule_suggestions(db: Session) -> list[RuleSuggestion]:
    # Les plus fréquentes d'abord : une proposition vue dix fois fait gagner
    # plus de temps qu'un achat unique.
    stmt = (
        select(RuleSuggestion)
        .where(RuleSuggestion.dismissed.is_(False))
        .order_by(RuleSuggestion.occurrences.desc(), RuleSuggestion.created_at.desc())
    )
    return list(db.execute(stmt).scalars().all())


def count_pending_rule_suggestions(db: Session) -> int:
    return db.scalar(
        select(func.count()).select_from(RuleSuggestion).where(RuleSuggestion.dismissed.is_(False))
    ) or 0


def dismiss_rule_suggestion(db: Session, suggestion_id: int) -> None:
    suggestion = db.get(RuleSuggestion, suggestion_id)
    if suggestion is not None:
        suggestion.dismissed = True
        db.commit()


def clear_rule_suggestions_for(db: Session, keyword: str) -> None:
    """Retire les propositions devenues sans objet parce qu'une règle existe.

    Appelé à la création d'une règle, d'où qu'elle vienne : la proposition
    ne doit pas survivre à sa propre réalisation.
    """
    keyword = (keyword or "").strip().lower()
    if not keyword:
        return
    lignes = db.execute(
        select(RuleSuggestion).where(func.lower(RuleSuggestion.keyword) == keyword)
    ).scalars().all()
    for ligne in lignes:
        db.delete(ligne)
    if lignes:
        db.commit()


def maybe_rule_suggestion(
    db: Session, transaction: Transaction, category: Category
) -> dict | None:
    # Partagé entre le backlog (catégorisation en masse) et La Savane (carte
    # par carte) : dès qu'une transaction vient d'être catégorisée sans
    # qu'aucune règle ne couvre déjà son libellé, on propose d'en créer une
    # — objectif : qu'un commerçant récurrent devienne une règle dès sa
    # première rencontre plutôt que de repasser indéfiniment par la
    # suggestion floue (voir suggest_backlog_category), pour qu'au bout de
    # quelques mois d'usage la quasi-totalité des opérations connues soit
    # déjà auto-catégorisée par une règle.
    if find_matching_rule(db, transaction.raw_label) is not None:
        return None
    if _is_generic_rule_keyword(transaction.label):
        return None
    # Persistée en plus d'être renvoyée : l'affichage immédiat reste le bon
    # moment pour décider, mais ce qui n'est pas traité doit se retrouver
    # dans la page Règles au lieu de disparaître (voir RuleSuggestion).
    # record_rule_suggestion renvoie None si la proposition a déjà été
    # refusée — on ne la repropose alors pas non plus à l'écran.
    if record_rule_suggestion(db, transaction.label, category.id) is None:
        return None
    return {
        "transaction_id": transaction.id,
        "keyword": transaction.label,
        "category_id": category.id,
        "category_name": category.name,
    }


def _normalized_rule_receipt_family(category: Category, receipt_family: str | None) -> str | None:
    # Réservé aux règles ciblant "Courses" (seule catégorie où le rapport
    # par rayon a du sens, voir Rule.receipt_family) : silencieusement
    # ignoré plutôt que rejeté si la catégorie choisie n'est pas Courses,
    # cohérent avec le fait que le champ reste affiché dans le formulaire
    # quelle que soit la catégorie sélectionnée (pas de JS conditionnel sur
    # une liste de sous-catégories chargée dynamiquement en HTMX).
    if category.name != "Courses" or not receipt_family:
        return None
    return receipt_family


def create_rule(
    db: Session,
    keyword: str,
    category: Category,
    payment_method: str | None = None,
    receipt_family: str | None = None,
) -> Rule:
    rule = Rule(
        keyword=keyword,
        category_id=category.id,
        payment_method=payment_method,
        receipt_family=_normalized_rule_receipt_family(category, receipt_family),
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    # Une proposition ne doit pas survivre à sa propre réalisation, d'où
    # qu'elle vienne — la page Règles, La Savane ou la catégorisation en
    # masse créent toutes leurs règles par ici.
    clear_rule_suggestions_for(db, keyword)
    return rule


# --- Gestion des règles (page Paramètres) ---


def _escape_like(value: str) -> str:
    # Un mot-clé contenant "%" ou "_" (ex. "50% RABAIS") doit être traité
    # comme du texte littéral dans le LIKE, pas comme un joker SQL.
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def get_rules_with_usage(db: Session) -> list[dict]:
    # "Utilisation" = nombre de transactions dont le libellé brut contient le
    # mot-clé — le même critère que find_matching_rule, mesuré indépendamment
    # par règle (pas de simulation du "premier match gagne" de La Savane, qui
    # répondrait à une question différente : "combien de fois ce mot-clé
    # apparaît" plutôt que "combien de fois CETTE règle déciderait seule").
    rules = (
        db.execute(
            select(Rule).options(selectinload(Rule.category).selectinload(Category.parent))
        )
        .scalars()
        .all()
    )
    results = []
    for rule in rules:
        pattern = f"%{_escape_like(rule.keyword)}%"
        usage_count = db.execute(
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.raw_label.ilike(pattern, escape="\\"))
        ).scalar_one()
        results.append({"rule": rule, "usage_count": usage_count})
    results.sort(key=lambda item: item["usage_count"], reverse=True)
    return results


def update_rule(
    db: Session,
    rule: Rule,
    keyword: str,
    category: Category,
    payment_method: str | None = None,
    receipt_family: str | None = None,
) -> Rule:
    rule.keyword = keyword
    rule.category_id = category.id
    rule.payment_method = payment_method
    rule.receipt_family = _normalized_rule_receipt_family(category, receipt_family)
    db.commit()
    db.refresh(rule)
    return rule


def delete_rule(db: Session, rule: Rule) -> None:
    db.delete(rule)
    db.commit()


# --- Gestion des catégories (page Paramètres) ---


def get_categories_tree(db: Session) -> list[Category]:
    # order_by est défini sur la relation children elle-même (voir models.py)
    # donc chaque niveau revient déjà trié par sort_order puis nom, quel que
    # soit le mécanisme de chargement utilisé.
    stmt = (
        select(Category)
        .where(Category.parent_id.is_(None))
        .options(selectinload(Category.children))
        .order_by(Category.sort_order, Category.name)
    )
    return list(db.execute(stmt).scalars().all())


def create_category(db: Session, name: str, parent: Category | None) -> Category:
    max_order = db.execute(
        select(func.coalesce(func.max(Category.sort_order), -1)).where(
            Category.parent_id == (parent.id if parent else None)
        )
    ).scalar_one()
    category = Category(name=name, parent_id=parent.id if parent else None, sort_order=max_order + 1)
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


def seed_starter_categories(db: Session) -> dict[str, int]:
    # Ajoute le jeu de catégories de départ (voir backend/starter_categories.py)
    # sans jamais rien modifier ni dupliquer : une catégorie dont le nom existe
    # déjà au même niveau (même parent) est laissée telle quelle, y compris son
    # pilier. Idempotent : relancer l'action ne crée plus rien. Une seule
    # transaction, contrairement à create_category qui valide à chaque ligne.
    from backend.starter_categories import STARTER_CATEGORIES

    def next_sort_order(parent_id: int | None) -> int:
        return db.execute(
            select(func.coalesce(func.max(Category.sort_order), -1) + 1).where(
                Category.parent_id == parent_id
            )
        ).scalar_one()

    created_parents = 0
    created_children = 0
    for starter in STARTER_CATEGORIES:
        parent = db.execute(
            select(Category).where(Category.name == starter.name, Category.parent_id.is_(None))
        ).scalar_one_or_none()
        if parent is None:
            parent = Category(
                name=starter.name,
                parent_id=None,
                sort_order=next_sort_order(None),
                pillar=starter.pillar,
                excluded_from_budget=starter.excluded_from_budget,
            )
            db.add(parent)
            db.flush()
            created_parents += 1

        for child_name, child_pillar in starter.children:
            exists = db.execute(
                select(Category.id).where(Category.name == child_name, Category.parent_id == parent.id)
            ).first()
            if exists is not None:
                continue
            db.add(
                Category(
                    name=child_name,
                    parent_id=parent.id,
                    sort_order=next_sort_order(parent.id),
                    pillar=child_pillar,
                )
            )
            db.flush()
            created_children += 1

    db.commit()
    return {"parents": created_parents, "children": created_children}


def update_category_name(db: Session, category: Category, name: str) -> Category:
    category.name = name
    db.commit()
    db.refresh(category)
    return category


def update_category_pillar(db: Session, category: Category, pillar: str | None) -> Category:
    # pillar=None est une valeur valide (pas juste "absence de changement") :
    # c'est "↳ Hériter du parent" pour une sous-catégorie, ou "non défini"
    # pour une catégorie racine — voir resolve_category_pillar pour la
    # résolution qui en découle.
    category.pillar = pillar
    db.commit()
    db.refresh(category)
    return category


def update_category_budget_exclusion(
    db: Session, category: Category, excluded: bool
) -> Category:
    category.excluded_from_budget = excluded
    db.commit()
    db.refresh(category)
    return category


def reset_subcategory_pillar_overrides(db: Session) -> int:
    stmt = (
        update(Category)
        .where(Category.parent_id.is_not(None))
        .values(pillar=None)
    )
    result = db.execute(stmt)
    db.commit()
    return result.rowcount


def get_category_usage(db: Session, category_id: int) -> dict[str, int]:
    return {
        "transactions": db.execute(
            select(func.count()).select_from(Transaction).where(Transaction.category_id == category_id)
        ).scalar_one(),
        "budgets": db.execute(
            select(func.count()).select_from(Budget).where(Budget.category_id == category_id)
        ).scalar_one(),
        "rules": db.execute(
            select(func.count()).select_from(Rule).where(Rule.category_id == category_id)
        ).scalar_one(),
        # category_id est nullable sur recurring_patterns, mais la contrainte
        # de clé étrangère bloque quand même la suppression tant qu'une ligne
        # y pointe encore (voir reassign_category_references) — doit être
        # compté ici au même titre que les autres, sous peine de proposer un
        # "aucune référence, suppression sûre" qui plante en base.
        "recurring_patterns": db.execute(
            select(func.count())
            .select_from(RecurringPattern)
            .where(RecurringPattern.category_id == category_id)
        ).scalar_one(),
        "children": db.execute(
            select(func.count()).select_from(Category).where(Category.parent_id == category_id)
        ).scalar_one(),
    }


def reassign_category_references(db: Session, from_category_id: int, to_category_id: int) -> None:
    # Transactions, budgets, règles et abonnements récurrents pointent tous
    # vers categories.id avec une contrainte de clé étrangère (NOT NULL pour
    # budgets/rules, nullable pour recurring_patterns mais quand même
    # bloquante côté FK tant qu'une ligne y pointe) : les réaffecter avant
    # suppression évite une violation de contrainte, pas seulement une perte
    # silencieuse de catégorisation.
    db.execute(
        update(Transaction)
        .where(Transaction.category_id == from_category_id)
        .values(category_id=to_category_id)
    )
    db.execute(
        update(Budget).where(Budget.category_id == from_category_id).values(category_id=to_category_id)
    )
    db.execute(
        update(Rule).where(Rule.category_id == from_category_id).values(category_id=to_category_id)
    )
    db.execute(
        update(RecurringPattern)
        .where(RecurringPattern.category_id == from_category_id)
        .values(category_id=to_category_id)
    )
    db.commit()


def delete_category(db: Session, category: Category) -> None:
    db.delete(category)
    db.commit()


# --- Justificatifs de transaction (ticket photo / facture PDF) ---


def get_receipt_items(db: Session, transaction_id: int) -> list[ReceiptItem]:
    stmt = (
        select(ReceiptItem)
        .where(ReceiptItem.transaction_id == transaction_id)
        .order_by(ReceiptItem.sort_order, ReceiptItem.id)
    )
    return list(db.execute(stmt).scalars().all())


def _next_receipt_item_sort_order(db: Session, transaction_id: int) -> int:
    max_sort = db.execute(
        select(func.coalesce(func.max(ReceiptItem.sort_order), -1)).where(
            ReceiptItem.transaction_id == transaction_id
        )
    ).scalar_one()
    return max_sort + 1


def add_receipt_item(
    db: Session,
    transaction_id: int,
    label: str,
    amount: Decimal,
    family: str | None = None,
) -> ReceiptItem:
    item = ReceiptItem(
        transaction_id=transaction_id,
        label=label,
        amount=amount,
        family=family,
        sort_order=_next_receipt_item_sort_order(db, transaction_id),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def bulk_add_receipt_items(db: Session, transaction_id: int, items: list[dict]) -> None:
    # Suggestions extraites d'une facture PDF (voir
    # receipts_storage.parse_receipt_lines) : insérées telles quelles pour
    # relecture, jamais garanties exactes — l'utilisateur corrige/supprime
    # directement les lignes depuis transactions/_receipt.html. Le rayon
    # vient en priorité de l'en-tête de section de la facture elle-même
    # (item["family"], bien plus fiable) ; à défaut, deviné par mot-clé
    # (guess_receipt_family) — laissé vide si ni l'un ni l'autre ne
    # reconnaît le libellé, jamais imposé sans que l'utilisateur puisse le
    # changer.
    next_sort = _next_receipt_item_sort_order(db, transaction_id)
    for offset, item in enumerate(items):
        db.add(
            ReceiptItem(
                transaction_id=transaction_id,
                label=item["label"],
                amount=item["amount"],
                family=item.get("family") or guess_receipt_family(item["label"]),
                sort_order=next_sort + offset,
            )
        )
    db.commit()


def update_receipt_item(
    db: Session, item: ReceiptItem, label: str, amount: Decimal, family: str | None
) -> ReceiptItem:
    item.label = label
    item.amount = amount
    item.family = family
    db.commit()
    db.refresh(item)
    return item


def delete_receipt_item(db: Session, item: ReceiptItem) -> None:
    db.delete(item)
    db.commit()


def get_receipt_family_months(db: Session, months: list[tuple[date, date, str]]) -> dict:
    # Onglet "Courses" du rapport : montant par rayon et par mois sur la
    # fenêtre glissante, plus une mesure de COUVERTURE (combien de courses
    # ont un détail de ticket, combien n'en ont pas). Sans cette couverture,
    # un mois sans ticket importé se lit comme un mois sans dépense.
    #
    # Attention à l'interprétation : les lignes de ticket valent le prix
    # produit AVANT remises, bons d'achat et titres-restaurant — ce rapport
    # mesure ce qui est ACHETÉ, pas ce qui est payé (voir la note affichée
    # dans reports/_content.html).
    if not months:
        return {"months": [], "family_rows": [], "monthly_totals": [], "coverage": {}}

    window_start, window_end = months[0][0], months[-1][1]

    rows = db.execute(
        select(
            ReceiptItem.family,
            Transaction.date,
            func.sum(ReceiptItem.amount),
        )
        .join(Transaction, Transaction.id == ReceiptItem.transaction_id)
        .where(Transaction.date >= window_start, Transaction.date <= window_end)
        .group_by(ReceiptItem.family, Transaction.date)
    ).all()

    # {famille: [montant par mois]} — indexé sur la position du mois pour
    # rester aligné avec l'ordre d'affichage (du plus ancien au plus récent).
    totals: dict[str | None, list[Decimal]] = {}
    monthly_totals = [Decimal("0.00")] * len(months)
    for family, tx_date, amount in rows:
        for index, (start, end, _label) in enumerate(months):
            if start <= tx_date <= end:
                totals.setdefault(family, [Decimal("0.00")] * len(months))
                totals[family][index] += amount
                monthly_totals[index] += amount
                break

    family_rows = []
    for code, icon, label in RECEIPT_FAMILIES:
        if code in totals:
            family_rows.append({"code": code, "icon": icon, "label": label, "monthly": totals.pop(code)})
    for code in sorted(c for c in totals if c is not None):
        family_rows.append({"code": code, "icon": "🏷️", "label": code, "monthly": totals.pop(code)})
    if None in totals:
        family_rows.append(
            {"code": None, "icon": "🏷️", "label": "Sans rayon", "monthly": totals.pop(None)}
        )

    active_months = sum(1 for total in monthly_totals if total > 0) or 1
    for row in family_rows:
        row["total"] = sum(row["monthly"], Decimal("0.00"))
        row["average"] = (row["total"] / active_months).quantize(Decimal("0.01"))
        # Tendance = dernier mois NON VIDE comparé au précédent non vide :
        # comparer au dernier mois calendaire ferait afficher une chute à
        # chaque début de mois, avant le premier ticket importé.
        filled = [(i, v) for i, v in enumerate(row["monthly"]) if v > 0]
        row["trend"] = None
        if len(filled) >= 2:
            row["trend"] = filled[-1][1] - filled[-2][1]

    # Couverture : uniquement le nombre de courses détaillées. Compter les
    # courses "sans détail" a été essayé puis retiré — faute de savoir quelle
    # opération AURAIT dû avoir un ticket, la seule approximation possible
    # (les autres opérations des mêmes catégories) donnait 288 sur une
    # catégorie "Courses" fourre-tout, un dénominateur qui faisait passer le
    # rapport pour vide sans rien apprendre.
    detailed_count = db.execute(
        select(func.count(func.distinct(ReceiptItem.transaction_id)))
        .join(Transaction, Transaction.id == ReceiptItem.transaction_id)
        .where(Transaction.date >= window_start, Transaction.date <= window_end)
    ).scalar_one()

    return {
        "months": [label for _s, _e, label in months],
        "family_rows": family_rows,
        "monthly_totals": monthly_totals,
        "grand_total": sum(monthly_totals, Decimal("0.00")),
        "coverage": {"detailed": detailed_count},
    }


def get_receipt_item_counts(db: Session, transaction_ids: list[int]) -> dict[int, int]:
    # Nombre de lignes de ticket par transaction, en UNE requête pour toute
    # la page affichée (voir routers/transactions._build_list_context) :
    # interroger transaction par transaction ferait une requête par ligne de
    # la liste. Renvoie uniquement les transactions qui en ont au moins une.
    if not transaction_ids:
        return {}
    stmt = (
        select(ReceiptItem.transaction_id, func.count(ReceiptItem.id))
        .where(ReceiptItem.transaction_id.in_(transaction_ids))
        .group_by(ReceiptItem.transaction_id)
    )
    return {tx_id: count for tx_id, count in db.execute(stmt).all()}


def delete_receipt_items_for_transaction(db: Session, transaction_id: int) -> int:
    # Appelé avant d'insérer les lignes d'un nouvel import (voir
    # routers/receipts.py) : ré-importer une facture doit REMPLACER le détail
    # précédent, pas s'y ajouter. Sans ça, un second import (typiquement
    # après un premier passage raté) doublait silencieusement toutes les
    # lignes — constaté sur une vraie facture importée deux fois (46 lignes
    # pour 21 produits, total à 141,02 € au lieu de 67,21 €).
    result = db.execute(
        delete(ReceiptItem).where(ReceiptItem.transaction_id == transaction_id)
    )
    db.commit()
    return result.rowcount or 0


# --- Recherche globale (en-tête) ---


def search_transactions_quick(db: Session, query: str, limit: int = 5) -> list[Transaction]:
    # label (simplifié) OU raw_label (brut) OU note : trois façons de
    # retrouver une transaction par le texte, peu importe laquelle contient
    # la requête.
    needle = f"%{query}%"
    stmt = (
        select(Transaction)
        .where(
            or_(
                Transaction.label.ilike(needle),
                Transaction.raw_label.ilike(needle),
                Transaction.note.ilike(needle),
            )
        )
        .order_by(Transaction.date.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def search_categories_quick(db: Session, query: str, limit: int = 5) -> list[Category]:
    stmt = (
        select(Category)
        .where(Category.name.ilike(f"%{query}%"))
        .order_by(Category.name)
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def search_projects_quick(db: Session, query: str, limit: int = 5) -> list[Project]:
    stmt = (
        select(Project)
        .where(Project.name.ilike(f"%{query}%"))
        .order_by(Project.name)
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


# --- Détection des abonnements récurrents (Paramètres) ---

# Bornes en jours entre deux occurrences consécutives pour chaque fréquence.
_RECURRING_FREQUENCY_BUCKETS: list[tuple[int, int, str]] = [
    (6, 8, "weekly"),
    (25, 35, "monthly"),
    (85, 95, "quarterly"),
    (360, 370, "yearly"),
]
# Valeur canonique stockée en base (colonne frequency_days) : un jour "type"
# par fréquence, pas la moyenne brute observée (plus stable d'une exécution
# à l'autre, et suffisant pour classer/afficher).
_RECURRING_FREQUENCY_CANONICAL_DAYS: dict[str, int] = {
    "weekly": 7,
    "monthly": 30,
    "quarterly": 90,
    "yearly": 365,
}
_RECURRING_FREQUENCY_LABELS_FR: dict[str, str] = {
    "weekly": "Hebdomadaire",
    "monthly": "Mensuel",
    "quarterly": "Trimestriel",
    "yearly": "Annuel",
}


def _classify_recurring_gap(days: int) -> str | None:
    for low, high, frequency in _RECURRING_FREQUENCY_BUCKETS:
        if low <= days <= high:
            return frequency
    return None


def _add_months(d: date, months: int) -> date:
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, monthrange(year, month)[1])
    return date(year, month, day)


def _advance_recurring_date(d: date, frequency: str) -> date:
    if frequency == "weekly":
        return d + timedelta(days=7)
    if frequency == "monthly":
        return _add_months(d, 1)
    if frequency == "quarterly":
        return _add_months(d, 3)
    return _add_months(d, 12)  # yearly


def _next_expected_recurring_date(last_date: date, frequency: str, today: date) -> date:
    # BUG corrigé : ajouter UNE SEULE fois frequency_days à la dernière
    # occurrence donnait une date passée (parfois 2024/2025) dès que
    # l'abonnement n'avait pas été revu depuis plusieurs périodes — on
    # avance donc autant de fois que nécessaire pour retomber sur la
    # prochaine échéance réellement future (>= aujourd'hui).
    next_date = _advance_recurring_date(last_date, frequency)
    while next_date < today:
        next_date = _advance_recurring_date(next_date, frequency)
    return next_date


def _dominant(values: list) -> object | None:
    counts: dict = {}
    for value in values:
        if value is not None:
            counts[value] = counts.get(value, 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.get)


# Mots génériques (jargon bancaire) à ignorer lors du nettoyage d'un
# libellé : sans ça, deux abonnements totalement différents partageant
# juste "PRELEVEMENT" fusionneraient à tort.
_RECURRING_KEYWORD_STOPWORDS = {
    "prelevement", "prlv", "prelvt", "virement", "vir", "cb", "carte",
    "paiement", "achat", "facture", "tpe", "sepa", "ecommerce",
}


def _clean_recurring_label(raw_label: str) -> str:
    # Retient TOUS les mots significatifs (pas juste le premier) : purement
    # alphabétiques (donc les numéros de référence, codes carte, codes
    # postaux, dates jj/mm... sont naturellement exclus puisqu'ils
    # contiennent des chiffres), d'au moins 3 lettres, hors mots génériques
    # de banque, dédupliqués en conservant l'ordre. "X1234 ACME 75001
    # PARIS 08/06" et "...05/07" (même abonnement, juste la date qui
    # change chaque mois) donnent ainsi tous deux "ACME PARIS" — un
    # nettoyage complet plutôt qu'un seul mot-clé isolé, pour ne pas perdre
    # "PARIS" qui distingue ce commerçant d'un autre partageant "ACME".
    tokens = re.split(r"[^A-Za-zÀ-ÿ]+", raw_label)
    stopwords = {w.upper() for w in _RECURRING_KEYWORD_STOPWORDS}
    kept: list[str] = []
    for token in tokens:
        if len(token) < 3:
            continue
        upper = token.upper()
        if upper in stopwords:
            continue
        if upper not in kept:
            kept.append(upper)
    return " ".join(kept) if kept else raw_label.strip().upper()


def _stored_recurring_aliases(db: Session) -> dict[str, str]:
    # Une fusion manuelle ("Fusionner") stocke un label_pattern combiné,
    # ex. "ACME|ACMEPRESSE" (voir merge_recurring_patterns) : ce mapping
    # fait retomber chaque mot-clé individuel sur ce libellé canonique dès
    # la prochaine détection, pour que la fusion reste effective dans la
    # durée sans avoir besoin d'une colonne dédiée.
    rows = db.execute(select(RecurringPattern)).scalars().all()
    aliases: dict[str, str] = {}
    for row in rows:
        parts = [p.strip().upper() for p in row.label_pattern.split("|") if p.strip()]
        if len(parts) > 1:
            for part in parts:
                aliases[part] = row.label_pattern
    return aliases


def detect_recurring_patterns(db: Session, today: date | None = None) -> list[dict]:
    today = today or date.today()

    # Uniquement des dépenses validées (jamais un virement) : un abonnement
    # est toujours une dépense confirmée, pas une suggestion en attente dans
    # La Savane ni un virement entre comptes suivis.
    stmt = (
        select(Transaction)
        .options(selectinload(Transaction.category))
        .where(
            Transaction.validated.is_(True),
            Transaction.amount < 0,
            Transaction.is_transfer.is_(False),
        )
        .order_by(Transaction.date)
    )
    transactions = list(db.execute(stmt).scalars().all())
    if not transactions:
        return []

    # Étape 1 : pré-groupement par libellé brut EXACT (rapide), pour ne
    # traiter ensuite qu'un libellé distinct à la fois.
    exact_groups: dict[str, list[Transaction]] = {}
    for tx in transactions:
        key = tx.raw_label.strip().lower()
        if key:
            exact_groups.setdefault(key, []).append(tx)

    # Étape 2 : nettoyage de chaque libellé distinct (tous les mots
    # significatifs, pas juste le premier), résolu via les fusions
    # manuelles déjà enregistrées le cas échéant (voir
    # _stored_recurring_aliases).
    aliases = _stored_recurring_aliases(db)
    cleaned_by_key: dict[str, str] = {}
    for key in exact_groups:
        cleaned = _clean_recurring_label(key)
        cleaned_by_key[key] = aliases.get(cleaned, cleaned)

    # Étape 3 : fusion floue des libellés NETTOYÉS entre eux — seuil abaissé
    # à 0.5 (au lieu de 0.8) : deux occurrences du même abonnement peuvent
    # ne garder qu'un mot en commun une fois les codes/dates retirés (ex :
    # "ACME" seul vs "ACME PARIS"), donc exiger une similarité aussi
    # stricte que 0.8 en rejetait beaucoup à tort. Comparer le texte déjà
    # NETTOYÉ (pas le libellé brut) est ce qui rend un seuil aussi bas sûr :
    # le bruit qui aurait fait chuter la similarité a déjà été retiré.
    distinct_cleaned = sorted(set(cleaned_by_key.values()))
    cleaned_cluster: dict[str, int] = {}
    next_cluster_id = 0
    for cleaned in distinct_cleaned:
        matched_cluster = None
        for existing_cleaned, cluster_id in cleaned_cluster.items():
            if difflib.SequenceMatcher(None, cleaned, existing_cleaned).ratio() > 0.5:
                matched_cluster = cluster_id
                break
        if matched_cluster is None:
            matched_cluster = next_cluster_id
            next_cluster_id += 1
        cleaned_cluster[cleaned] = matched_cluster

    merged: dict[int, list[Transaction]] = {}
    merged_labels: dict[int, list[str]] = {}
    for key, txs in exact_groups.items():
        cluster_id = cleaned_cluster[cleaned_by_key[key]]
        merged.setdefault(cluster_id, []).extend(txs)
        merged_labels.setdefault(cluster_id, []).extend([cleaned_by_key[key]] * len(txs))

    patterns = []
    for cluster_id, txs in merged.items():
        # Au moins 2 occurrences (pas 3) pour repérer aussi les abonnements
        # récents qui n'ont encore qu'un seul renouvellement observé.
        if len(txs) < 2:
            continue
        txs = sorted(txs, key=lambda t: t.date)

        amounts = [abs(t.amount) for t in txs]
        average = sum(amounts) / len(amounts)
        if average == 0:
            continue
        tolerance = average * Decimal("0.05")
        if not all(abs(a - average) <= tolerance for a in amounts):
            continue

        gaps = [(b.date - a.date).days for a, b in zip(txs, txs[1:])]
        classified = [c for c in (_classify_recurring_gap(gap) for gap in gaps) if c is not None]
        if not classified:
            continue
        frequency = max(set(classified), key=classified.count)

        last_tx = txs[-1]
        payment_method = _dominant([t.payment_method for t in txs])
        category = _dominant([t.category for t in txs])
        label_pattern = _dominant(merged_labels[cluster_id]) or (last_tx.label or last_tx.raw_label).strip()

        # Toutes les transactions validées sont regardées, sans limite de
        # date — mais un abonnement pas revu depuis longtemps est signalé
        # "inactif/annulé ?" plutôt que caché : > 3 mois (90 jours) sans
        # occurrence -> probablement résilié ; <= 45 jours -> toujours actif.
        days_since_last = (today - last_tx.date).days
        activity_status = "inactive" if days_since_last > 90 else "active"

        patterns.append(
            {
                "label_pattern": label_pattern,
                "amount": average.quantize(Decimal("0.01")),
                "frequency": frequency,
                "frequency_label": _RECURRING_FREQUENCY_LABELS_FR[frequency],
                "frequency_days": _RECURRING_FREQUENCY_CANONICAL_DAYS[frequency],
                "last_date": last_tx.date,
                "next_expected": _next_expected_recurring_date(last_tx.date, frequency, today),
                "seen_this_month": any(
                    t.date.year == today.year and t.date.month == today.month for t in txs
                ),
                "activity_status": activity_status,
                "days_since_last": days_since_last,
                "category": category,
                "payment_method": payment_method,
                "occurrences": len(txs),
            }
        )

    patterns.sort(key=lambda p: p["amount"], reverse=True)
    return patterns


def find_possible_duplicate_recurring_groups(patterns: list[dict]) -> list[list[dict]]:
    # Filet de sécurité en plus du regroupement ci-dessus, pour le cas où
    # deux motifs FINAUX distincts sont quand même le même abonnement (ex :
    # "ACME" vs "ACMEPRESSE" — une marque avec plusieurs produits, deux
    # mots-clés réellement différents mais liés). Repose UNIQUEMENT sur une
    # relation de sous-chaîne, pas sur un score de similarité flou : un
    # ratio difflib dans la zone juste sous le seuil de fusion automatique
    # (0.5, voir detect_recurring_patterns) ne distingue pas de façon fiable
    # un vrai quasi-doublon d'un rapprochement fortuit (ex : "EDF ELEC" vs
    # "FREE MOBILE" score déjà 0.42 sans aucun rapport réel) — proposé à
    # l'utilisateur via "Fusionner" plutôt que fusionné d'office.
    groups: list[list[dict]] = []
    used: set[int] = set()
    for i, a in enumerate(patterns):
        if i in used:
            continue
        key_a = a["label_pattern"].split("|")[0]
        group = [a]
        for j in range(i + 1, len(patterns)):
            if j in used:
                continue
            key_b = patterns[j]["label_pattern"].split("|")[0]
            if key_a == key_b:
                continue
            if key_a in key_b or key_b in key_a:
                group.append(patterns[j])
                used.add(j)
        if len(group) > 1:
            used.add(i)
            groups.append(group)
    return groups


def get_recurring_pattern_statuses(db: Session) -> dict[str, str]:
    rows = db.execute(select(RecurringPattern)).scalars().all()
    return {row.label_pattern: row.status for row in rows}


def _recurring_monthly_equivalent(amount: Decimal, frequency: str) -> Decimal:
    if frequency == "weekly":
        return amount * Decimal("30") / Decimal("7")
    if frequency == "monthly":
        return amount
    if frequency == "quarterly":
        return amount / Decimal("3")
    return amount / Decimal("12")  # yearly


def get_recurring_patterns_overview(db: Session, today: date | None = None) -> dict:
    patterns = detect_recurring_patterns(db, today)
    statuses = get_recurring_pattern_statuses(db)
    for pattern in patterns:
        pattern["status"] = statuses.get(pattern["label_pattern"], "pending")

    active = [p for p in patterns if p["status"] != "ignored"]
    monthly_total = sum(
        (_recurring_monthly_equivalent(p["amount"], p["frequency"]) for p in active),
        Decimal("0.00"),
    )

    return {
        "recurring_patterns": patterns,
        "recurring_active_count": len(active),
        "recurring_monthly_total": monthly_total.quantize(Decimal("0.01")),
        "recurring_duplicate_groups": find_possible_duplicate_recurring_groups(patterns),
    }


def set_recurring_pattern_status(
    db: Session,
    label_pattern: str,
    amount: Decimal,
    frequency_days: int,
    category_id: int | None,
    status: str,
) -> None:
    existing = db.execute(
        select(RecurringPattern).where(RecurringPattern.label_pattern == label_pattern)
    ).scalar_one_or_none()
    if existing is not None:
        existing.amount = amount
        existing.frequency_days = frequency_days
        existing.category_id = category_id
        existing.status = status
    else:
        db.add(
            RecurringPattern(
                label_pattern=label_pattern,
                amount=amount,
                frequency_days=frequency_days,
                category_id=category_id,
                status=status,
            )
        )
    db.commit()


def merge_recurring_patterns(
    db: Session,
    label_patterns: list[str],
    amount: Decimal,
    frequency_days: int,
    category_id: int | None,
) -> str:
    # Un motif fusionné se souvient de TOUS les mots-clés d'origine dans son
    # label_pattern ("ACME|ACMEPRESSE"), pas juste un seul choisi
    # arbitrairement : detect_recurring_patterns (_stored_recurring_aliases)
    # relit cette liste à chaque détection pour que la fusion reste
    # effective d'une visite à l'autre, sans colonne dédiée en base.
    parts: list[str] = []
    for label in label_patterns:
        for part in label.split("|"):
            part = part.strip().upper()
            if part and part not in parts:
                parts.append(part)
    canonical_label = "|".join(parts)

    # Les anciennes lignes correspondant aux motifs d'origine sont
    # supprimées : elles sont remplacées par la ligne fusionnée ci-dessous,
    # sans quoi elles resteraient comme décisions orphelines obsolètes.
    for label in label_patterns:
        existing = db.execute(
            select(RecurringPattern).where(RecurringPattern.label_pattern == label)
        ).scalar_one_or_none()
        if existing is not None:
            db.delete(existing)

    set_recurring_pattern_status(
        db, canonical_label, amount, frequency_days, category_id, "confirmed"
    )
    return canonical_label


