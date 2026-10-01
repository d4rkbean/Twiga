from datetime import date
from decimal import Decimal

from backend.i18n import current_format

_THIN_SPACE = " "


def format_amount(value: Decimal) -> str:
    return format_amount_as(value, current_format())


def format_amount_as(value: Decimal, number_format: str) -> str:
    quantized = value.quantize(Decimal("0.01"))
    sign = "-" if quantized < 0 else ""
    integer_part, _, decimal_part = f"{abs(quantized):.2f}".partition(".")

    groups = []
    while len(integer_part) > 3:
        groups.insert(0, integer_part[-3:])
        integer_part = integer_part[:-3]
    groups.insert(0, integer_part)

    if number_format == "fr":
        # 1 234,56 € : espace fine entre les milliers, virgule décimale,
        # symbole après le montant.
        return f"{sign}{_THIN_SPACE.join(groups)},{decimal_part} €"
    # €1,234.56 : virgule entre les milliers, point décimal, symbole avant.
    return f"{sign}€{','.join(groups)}.{decimal_part}"


def format_date(value: date) -> str:
    return format_date_as(value, current_format())


def format_date_as(value: date, number_format: str) -> str:
    # Le format américain met le mois avant le jour ; français et international
    # (en-GB) partagent jour/mois/année.
    if number_format == "en-US":
        return value.strftime("%m/%d/%Y")
    return value.strftime("%d/%m/%Y")
