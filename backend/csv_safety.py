"""CSV exports that a spreadsheet cannot run as formulas.

A label, a note, a category or an account name typed in Twiga (or imported
from a bank statement) can start with "=", "+", "-" or "@": opened in Excel or
LibreOffice, such a cell is run as a formula (=HYPERLINK(...), =WEBSERVICE(...)
send data elsewhere). Every text cell that starts with one of those characters,
a tab or a carriage return gets a leading apostrophe, which the spreadsheet
shows as plain text.

Amounts stay numbers: a cell made only of a sign, digits, separators and a
currency or percent sign ("-12.50", "-1 234,56 €", "-5 %") is left as it is.
It cannot hold a formula.
"""

from __future__ import annotations

import csv
import re

_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")
_NUMBER = re.compile(r"[+-]?[\d\s  .,']*\d[\d\s  .,']*\s*(?:€|%|EUR)?\s*")


def escape_cell(value):
    if not isinstance(value, str) or not value.startswith(_FORMULA_STARTS):
        return value
    if _NUMBER.fullmatch(value):
        return value
    return "'" + value


class _SafeWriter:
    def __init__(self, writer) -> None:
        self._writer = writer

    def writerow(self, row):
        return self._writer.writerow([escape_cell(cell) for cell in row])

    def writerows(self, rows) -> None:
        for row in rows:
            self.writerow(row)


def writer(buffer, **options) -> _SafeWriter:
    """csv.writer whose text cells are escaped, see the module docstring."""
    return _SafeWriter(csv.writer(buffer, **options))
