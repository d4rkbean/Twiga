from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation


class ImportParseError(ValueError):
    pass


@dataclass
class ParsedTransaction:
    account_name: str
    date: date
    label: str
    amount: Decimal
    category_path: str | None = None
    payee: str | None = None
    memo: str | None = None
    transfer_account: str | None = None


def parse_decimal_amount(raw: str) -> Decimal:
    value = raw.strip().replace(" ", "").replace(" ", "")
    if not value:
        return Decimal("0.00")

    negative = value.startswith("-")
    if negative or value.startswith("+"):
        value = value[1:]

    if "," in value and "." in value:
        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "").replace(",", ".")
        else:
            value = value.replace(",", "")
    elif "," in value:
        value = value.replace(",", ".")

    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ImportParseError(f"Montant invalide : {raw!r}") from exc

    if negative:
        amount = -amount

    return amount.quantize(Decimal("0.01"))


DuplicateKey = tuple[object, date, Decimal, str]


def build_duplicate_key(account_key: object, tx_date: date, amount: Decimal, label: str) -> DuplicateKey:
    return (account_key, tx_date, amount, label.strip().casefold())


_VARIANT_MIN_LENGTH = 8


def _is_label_variant(one: str, other: str) -> bool:
    # Même opération exportée sous deux formats de libellé : selon le
    # fichier, la banque accole la date d'opération et répète le libellé
    # ("X1234 MAGASIN 5678 VILLE" vs "X1234 MAGASIN 5678 VILLE   26/04 P…").
    # L'égalité stricte laissait donc passer le doublon à chaque changement
    # de format d'export, et 276 lignes en double ont été trouvées dans une
    # vraie base à cause de ça — dont des salaires comptés deux fois.
    if one == other:
        return True
    short, long_ = (one, other) if len(one) <= len(other) else (other, one)
    # Longueur minimale : sur un libellé très court ("cb", "chq"), un simple
    # préfixe ne prouve rien et fusionnerait des opérations distinctes.
    return len(short) >= _VARIANT_MIN_LENGTH and long_.startswith(short)


def split_duplicates(
    transactions: list[ParsedTransaction],
    existing_keys: set[DuplicateKey] | None = None,
) -> tuple[list[ParsedTransaction], list[ParsedTransaction]]:
    # Indexé par (compte, date, montant) plutôt qu'en set de clés complètes :
    # le libellé ne peut plus être comparé par simple égalité, il faut le
    # confronter à tous ceux déjà vus pour la même opération (voir
    # _is_label_variant).
    seen: dict[tuple, list[str]] = {}
    for account_key, tx_date, amount, label in existing_keys or ():
        seen.setdefault((account_key, tx_date, amount), []).append(label)

    unique: list[ParsedTransaction] = []
    duplicates: list[ParsedTransaction] = []

    for tx in transactions:
        account_key, tx_date, amount, label = build_duplicate_key(
            tx.account_name, tx.date, tx.amount, tx.label
        )
        labels = seen.setdefault((account_key, tx_date, amount), [])
        if any(_is_label_variant(label, known) for known in labels):
            duplicates.append(tx)
        else:
            labels.append(label)
            unique.append(tx)

    return unique, duplicates
