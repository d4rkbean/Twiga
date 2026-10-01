from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from imports.common import ImportParseError, ParsedTransaction, parse_decimal_amount

from backend.i18n import gettext as _t

__all__ = [
    "CsvColumnMapping",
    "CsvPreview",
    "CsvParseError",
    "DATE_FORMAT_CHOICES",
    "detect_delimiter",
    "guess_column_mapping",
    "detect_date_format",
    "preview_csv",
    "parse_csv_transactions",
    "read_csv_file",
]

_DELIMITER_CANDIDATES = (";", ",")

# Formats testés dans l'ordre : JJ/MM d'abord (convention française par défaut),
# puis MM/JJ et ISO en repli pour rester compatible avec d'autres exports bancaires.
DATE_FORMAT_CHOICES = (
    "%d/%m/%Y",
    "%d/%m/%y",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d-%m-%Y",
)

_DATE_HEADER_HINTS = ("date",)
_LABEL_HEADER_HINTS = ("libell", "label", "description", "desc", "memo", "tiers", "beneficiaire", "bénéficiaire", "payee")
_AMOUNT_HEADER_HINTS = ("montant", "amount", "somme", "valeur")


class CsvParseError(ImportParseError):
    pass


@dataclass
class CsvColumnMapping:
    date_column: int
    label_column: int
    amount_column: int


@dataclass
class CsvPreview:
    delimiter: str
    header: list[str]
    sample_rows: list[list[str]]
    guessed_mapping: CsvColumnMapping
    detected_date_format: str | None


def detect_delimiter(sample: str) -> str:
    first_lines = "\n".join(sample.splitlines()[:5])
    try:
        dialect = csv.Sniffer().sniff(first_lines, delimiters="".join(_DELIMITER_CANDIDATES))
        if dialect.delimiter in _DELIMITER_CANDIDATES:
            return dialect.delimiter
    except csv.Error:
        pass

    counts = {delimiter: first_lines.count(delimiter) for delimiter in _DELIMITER_CANDIDATES}
    if any(counts.values()):
        return max(counts, key=counts.get)
    return ";"


def _read_rows(content: str, delimiter: str) -> list[list[str]]:
    reader = csv.reader(io.StringIO(content), delimiter=delimiter)
    return [row for row in reader if any(cell.strip() for cell in row)]


def _guess_column(header: list[str], hints: tuple[str, ...]) -> int | None:
    for index, name in enumerate(header):
        normalized = name.strip().lower()
        if any(hint in normalized for hint in hints):
            return index
    return None


def guess_column_mapping(header: list[str]) -> CsvColumnMapping:
    date_col = _guess_column(header, _DATE_HEADER_HINTS)
    label_col = _guess_column(header, _LABEL_HEADER_HINTS)
    amount_col = _guess_column(header, _AMOUNT_HEADER_HINTS)

    used = {column for column in (date_col, label_col, amount_col) if column is not None}
    fallback = [index for index in range(len(header)) if index not in used]

    if date_col is None and fallback:
        date_col = fallback.pop(0)
    if label_col is None and fallback:
        label_col = fallback.pop(0)
    if amount_col is None and fallback:
        amount_col = fallback.pop(0)

    last_index = max(len(header) - 1, 0)
    return CsvColumnMapping(
        date_column=date_col if date_col is not None else 0,
        label_column=label_col if label_col is not None else min(1, last_index),
        amount_column=amount_col if amount_col is not None else min(2, last_index),
    )


def _try_parse_date(value: str, fmt: str) -> bool:
    try:
        datetime.strptime(value.strip(), fmt)
        return True
    except ValueError:
        return False


def detect_date_format(samples: list[str]) -> str | None:
    candidates = [value for value in samples if value.strip()]
    if not candidates:
        return None

    for fmt in DATE_FORMAT_CHOICES:
        if all(_try_parse_date(value, fmt) for value in candidates):
            return fmt
    return None


def parse_date_with_format(raw: str, date_format: str) -> date:
    try:
        return datetime.strptime(raw.strip(), date_format).date()
    except ValueError as exc:
        raise CsvParseError(_t("Date invalide : %(raw)r (format attendu %(format)s)") % {"raw": raw, "format": date_format}) from exc


def preview_csv(content: str, sample_size: int = 5) -> CsvPreview:
    delimiter = detect_delimiter(content)
    rows = _read_rows(content, delimiter)
    if not rows:
        raise CsvParseError(_t("Fichier CSV vide."))

    header, *data_rows = rows
    sample_rows = data_rows[:sample_size]
    mapping = guess_column_mapping(header)

    date_samples = [row[mapping.date_column] for row in sample_rows if len(row) > mapping.date_column]
    detected_format = detect_date_format(date_samples)

    return CsvPreview(
        delimiter=delimiter,
        header=header,
        sample_rows=sample_rows,
        guessed_mapping=mapping,
        detected_date_format=detected_format,
    )


def parse_csv_transactions(
    content: str,
    account_name: str,
    mapping: CsvColumnMapping,
    date_format: str,
    delimiter: str | None = None,
) -> list[ParsedTransaction]:
    delimiter = delimiter or detect_delimiter(content)
    rows = _read_rows(content, delimiter)
    if not rows:
        return []

    _header, *data_rows = rows
    max_col = max(mapping.date_column, mapping.label_column, mapping.amount_column)
    transactions: list[ParsedTransaction] = []

    for row_no, row in enumerate(data_rows, start=2):
        if len(row) <= max_col:
            raise CsvParseError(_t("Ligne %(row)s : colonnes manquantes.") % {"row": row_no})

        try:
            tx_date = parse_date_with_format(row[mapping.date_column], date_format)
            amount = parse_decimal_amount(row[mapping.amount_column])
        except ImportParseError as exc:
            raise CsvParseError(_t("Ligne %(row)s : %(error)s") % {"row": row_no, "error": exc}) from exc

        transactions.append(
            ParsedTransaction(
                account_name=account_name,
                date=tx_date,
                label=row[mapping.label_column].strip(),
                amount=amount,
            )
        )

    return transactions


def read_csv_file(path: str | Path) -> str:
    file_path = Path(path)
    try:
        return file_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return file_path.read_text(encoding="latin-1")
