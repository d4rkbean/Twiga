from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from imports.common import ImportParseError, ParsedTransaction, parse_decimal_amount

__all__ = [
    "OfxParseError",
    "iter_transaction_blocks",
    "parse_ofx_transactions",
    "read_ofx_file",
]

# OFX 1.x est du SGML : les balises de valeur (DTPOSTED, TRNAMT, ...) ne sont
# pas toujours fermées. On extrait donc chaque valeur jusqu'au prochain '<' ou
# saut de ligne plutôt que d'utiliser un parseur XML strict.
_STMTTRN_PATTERN = re.compile(r"<STMTTRN>(.*?)</STMTTRN>", re.IGNORECASE | re.DOTALL)
_TAG_PATTERN_CACHE: dict[str, re.Pattern[str]] = {}


class OfxParseError(ImportParseError):
    pass


def _extract_tag(block: str, tag: str) -> str | None:
    pattern = _TAG_PATTERN_CACHE.get(tag)
    if pattern is None:
        pattern = re.compile(rf"<{tag}>\s*([^<\r\n]*)", re.IGNORECASE)
        _TAG_PATTERN_CACHE[tag] = pattern

    match = pattern.search(block)
    if match is None:
        return None

    value = match.group(1).strip()
    return value or None


def _parse_ofx_date(raw: str) -> date:
    digits = raw[:8]
    try:
        return datetime.strptime(digits, "%Y%m%d").date()
    except ValueError as exc:
        raise OfxParseError(f"Date invalide : {raw!r}") from exc


def iter_transaction_blocks(content: str) -> list[str]:
    return _STMTTRN_PATTERN.findall(content)


def parse_ofx_transactions(content: str, account_name: str) -> list[ParsedTransaction]:
    blocks = iter_transaction_blocks(content)
    if not blocks:
        raise OfxParseError("Aucune transaction trouvée (balise <STMTTRN> absente).")

    transactions: list[ParsedTransaction] = []

    for index, block in enumerate(blocks, start=1):
        date_raw = _extract_tag(block, "DTPOSTED")
        amount_raw = _extract_tag(block, "TRNAMT")
        if date_raw is None or amount_raw is None:
            raise OfxParseError(f"Transaction {index} : DTPOSTED ou TRNAMT manquant.")

        name = _extract_tag(block, "NAME")
        memo = _extract_tag(block, "MEMO")
        label = name or memo or ""

        try:
            tx_date = _parse_ofx_date(date_raw)
            amount = parse_decimal_amount(amount_raw)
        except ImportParseError as exc:
            raise OfxParseError(f"Transaction {index} : {exc}") from exc

        transactions.append(
            ParsedTransaction(
                account_name=account_name,
                date=tx_date,
                label=label,
                amount=amount,
                payee=name,
                memo=memo if memo != label else None,
            )
        )

    return transactions


def read_ofx_file(path: str | Path) -> str:
    file_path = Path(path)
    try:
        return file_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return file_path.read_text(encoding="latin-1")
