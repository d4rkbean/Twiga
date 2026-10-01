from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from backend.i18n import gettext as _t
from imports.common import (
    ImportParseError,
    ParsedTransaction,
    build_duplicate_key,
    parse_decimal_amount,
    split_duplicates,
)

__all__ = [
    "ParsedTransaction",
    "build_duplicate_key",
    "split_duplicates",
    "ParsedAccount",
    "ParsedCategory",
    "QifImportResult",
    "QifParseError",
    "parse_qif",
    "parse_qif_file",
]

DEFAULT_ACCOUNT_NAME = "Compte importé"

# HomeBank exporte les dates au format français jour/mois/année par défaut ;
# les formats US et ISO sont tentés en repli pour rester compatible avec
# d'autres exports QIF (Quicken, GnuCash).
_DATE_FORMATS = (
    "%d/%m/%Y",
    "%d/%m/%y",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%Y-%m-%d",
    "%Y/%m/%d",
)

_TRANSACTION_HEADERS_TO_IGNORE = ("!type:class", "!type:memorized")


class QifParseError(ImportParseError):
    pass


@dataclass
class ParsedAccount:
    name: str
    type: str
    balance: Decimal = Decimal("0.00")


@dataclass
class ParsedCategory:
    path: str
    name: str
    parent_path: str | None = None


@dataclass
class QifImportResult:
    accounts: list[ParsedAccount]
    categories: list[ParsedCategory]
    transactions: list[ParsedTransaction]
    payees: set[str]


def _parse_date(raw: str) -> date:
    value = raw.strip()

    apostrophe_match = re.match(r"^(\d{1,2})/(\d{1,2})'(\d{2,4})$", value)
    if apostrophe_match:
        first, second, year = apostrophe_match.groups()
        year = year if len(year) == 4 else f"20{year}"
        value = f"{first}/{second}/{year}"

    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue

    raise QifParseError(_t("Date invalide : %(raw)r") % {"raw": raw})


def _build_categories(category_paths: set[str]) -> list[ParsedCategory]:
    # HomeBank utilise "/" comme séparateur de hiérarchie dans le NOM des
    # catégories (ex: "Loisirs/culture/sport"), pas ":". Notre schéma ne gère
    # que 2 niveaux (catégorie + sous-catégorie) : on ne coupe donc QU'UNE
    # SEULE FOIS, au DERNIER "/" — tout ce qui précède devient le nom du
    # parent TEL QUEL (jamais redécoupé une seconde fois, même s'il contient
    # encore un "/" en interne pour un chemin HomeBank à 3+ niveaux aplati
    # sur 2), et le dernier segment devient la sous-catégorie.
    #
    # Ancien bug : le code qui lisait le champ L des transactions coupait au
    # PREMIER "/" et ne gardait que ce qui précède (`.split("/", 1)[0]`),
    # perdant purement et simplement tout le reste ("Loisirs/culture/sport"
    # devenait juste "Loisirs", "culture/sport" disparaissait).
    entries: dict[str, str | None] = {}
    names: dict[str, str] = {}

    for raw_path in category_paths:
        path = raw_path.strip()
        if not path:
            continue

        if "/" in path:
            parent_name, child_name = path.rsplit("/", 1)
        else:
            parent_name, child_name = None, path

        names[path] = child_name
        entries[path] = parent_name

        if parent_name is not None:
            # Le nom du parent est déjà résolu tel quel : setdefault plutôt
            # qu'une affectation directe, pour ne pas écraser une entrée déjà
            # présente si CE parent est LUI-MÊME référencé directement
            # ailleurs (auquel cas il aura sa propre entrée, potentiellement
            # avec un vrai parent au-dessus).
            names.setdefault(parent_name, parent_name)
            entries.setdefault(parent_name, None)

    categories = []
    for path in sorted(entries):
        categories.append(ParsedCategory(path=path, name=names[path], parent_path=entries[path]))

    return categories


def parse_qif(content: str, default_account_name: str = DEFAULT_ACCOUNT_NAME) -> QifImportResult:
    accounts: dict[str, ParsedAccount] = {}
    category_paths: set[str] = set()
    transactions: list[ParsedTransaction] = []
    payees: set[str] = set()

    section: str | None = None
    pending: dict[str, str] = {}
    current_account_name: str | None = None

    for line_no, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("!"):
            header = line.lower()
            if header == "!type:cat":
                section = "category"
            elif header == "!account":
                section = "account_def"
            elif header.startswith("!type:") and header not in _TRANSACTION_HEADERS_TO_IGNORE:
                section = "transaction"
                if current_account_name is None:
                    current_account_name = default_account_name
                    accounts.setdefault(
                        current_account_name,
                        ParsedAccount(name=current_account_name, type=line.split(":", 1)[1]),
                    )
            else:
                section = None
            pending = {}
            continue

        if line == "^":
            try:
                if section == "account_def" and "N" in pending:
                    name = pending["N"]
                    current_account_name = name
                    accounts[name] = ParsedAccount(
                        name=name,
                        type=pending.get("T", "Bank"),
                        balance=parse_decimal_amount(pending["$"]) if "$" in pending else Decimal("0.00"),
                    )
                elif section == "category" and "N" in pending:
                    category_paths.add(pending["N"])
                elif section == "transaction" and current_account_name is not None:
                    amount_raw = pending.get("T") or pending.get("U")
                    if "D" in pending and amount_raw is not None:
                        # Les transactions "split" (codes S/$/E répétés) ne sont pas
                        # supportées : le schéma ne stocke qu'une seule catégorie
                        # par transaction. Seule la catégorie principale (L) est lue.
                        category_value = pending.get("L")
                        category_path = None
                        transfer_account = None
                        if category_value:
                            if category_value.startswith("[") and category_value.endswith("]"):
                                transfer_account = category_value[1:-1]
                            else:
                                # Le "/" fait partie du nom hiérarchique de la
                                # catégorie HomeBank (ex: "Loisirs/culture/
                                # sport") : on le préserve intégralement ici.
                                # _build_categories se charge de le découper
                                # au DERNIER "/" pour en tirer parent/sous-
                                # catégorie — le couper au premier "/" ici
                                # perdrait tout ce qui suit.
                                category_path = category_value.strip()
                                category_paths.add(category_path)

                        payee = pending.get("P")
                        memo = pending.get("M")
                        label = payee or memo or ""
                        if payee:
                            payees.add(payee)

                        transactions.append(
                            ParsedTransaction(
                                account_name=current_account_name,
                                date=_parse_date(pending["D"]),
                                label=label,
                                amount=parse_decimal_amount(amount_raw),
                                category_path=category_path,
                                payee=payee,
                                memo=memo,
                                transfer_account=transfer_account,
                            )
                        )
            except ImportParseError as exc:
                raise QifParseError(_t("Ligne %(line)s : %(error)s") % {"line": line_no, "error": exc}) from exc

            pending = {}
            continue

        code, value = line[0], line[1:]
        pending[code] = value

    return QifImportResult(
        accounts=list(accounts.values()),
        categories=_build_categories(category_paths),
        transactions=transactions,
        payees=payees,
    )


def parse_qif_file(
    path: str | Path, default_account_name: str = DEFAULT_ACCOUNT_NAME
) -> QifImportResult:
    file_path = Path(path)
    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = file_path.read_text(encoding="latin-1")

    return parse_qif(content, default_account_name=default_account_name)
