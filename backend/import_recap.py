"""What the import recap needs to say about a statement that was just read.

Pure helpers (no session, no request): which account a statement most likely
belongs to, the span of dates it covers, and the transfers between the user's
own accounts that it contains. The route gathers the data, these functions
shape it, and tests/test_lot5c_settings.py covers them without a database.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date


def _slug(value: str) -> str:
    """Lowercase letters and digits only, accents removed: "Compte joint" and "compte-joint" match."""
    decomposed = unicodedata.normalize("NFKD", value or "")
    return re.sub(r"[^a-z0-9]+", "", decomposed.encode("ascii", "ignore").decode().lower())


def guess_account(accounts: list, filename: str, recent_account_names: list[str]):
    """The account a statement most likely belongs to, or None when there is no account.

    In order: an account whose name is written in the file name
    ("compte-joint-juin.csv"), then the account of the latest import (a
    household imports the same statement every month), then the first account.
    `accounts` are objects with a `name`; `recent_account_names` come newest first.
    """
    if not accounts:
        return None
    stem = _slug(filename.rsplit(".", 1)[0])
    named = [account for account in accounts if _slug(account.name) and _slug(account.name) in stem]
    if named:
        return max(named, key=lambda account: len(_slug(account.name)))
    by_name = {account.name: account for account in accounts}
    for name in recent_account_names:
        if name in by_name:
            return by_name[name]
    return accounts[0]


def date_span(dates: list[date]) -> tuple[date, date] | None:
    """The first and the last day a statement covers, or None for an empty one."""
    return (min(dates), max(dates)) if dates else None


def transfer_groups(rows: list[tuple[date, str | None]], account_name: str) -> list[dict]:
    """The internal transfers of a statement, grouped by destination.

    `rows` are (date, other account) for the lines the file flags as a transfer.
    Returns [{"from", "to", "count", "dates"}] sorted by destination.
    """
    groups: dict[str, list[date]] = {}
    for when, other in rows:
        if other:
            groups.setdefault(other, []).append(when)
    return [
        {"from": account_name, "to": other, "count": len(dates), "dates": sorted(dates)}
        for other, dates in sorted(groups.items())
    ]
