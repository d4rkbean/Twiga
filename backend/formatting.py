from datetime import date
from decimal import Decimal

_THIN_SPACE = " "


def format_amount(value: Decimal) -> str:
    quantized = value.quantize(Decimal("0.01"))
    sign = "-" if quantized < 0 else ""
    integer_part, _, decimal_part = f"{abs(quantized):.2f}".partition(".")

    groups = []
    while len(integer_part) > 3:
        groups.insert(0, integer_part[-3:])
        integer_part = integer_part[:-3]
    groups.insert(0, integer_part)

    return f"{sign}{_THIN_SPACE.join(groups)},{decimal_part} €"


def format_date(value: date) -> str:
    return value.strftime("%d/%m/%Y")
