from datetime import date
from decimal import Decimal

from backend.i18n import current_format

_THIN_SPACE = " "
# Vrai signe moins, de la largeur du « + » : le trait d'union est trop court et
# fait lire « -48,00 € » comme un tiret.
_MINUS = "\u2212"


def format_amount(value: Decimal) -> str:
    """Amount for the screen (filter `eur`): typographic minus sign."""
    return format_amount_as(value, current_format())


def format_amount_for_export(value: Decimal) -> str:
    """Same text for a file a spreadsheet will read: plain ASCII hyphen-minus."""
    return format_amount_as(value, current_format(), ascii_minus=True)


def format_amount_as(value: Decimal, number_format: str, ascii_minus: bool = False) -> str:
    quantized = Decimal(value).quantize(Decimal("0.01"))
    sign =("-" if ascii_minus else _MINUS) if quantized < 0 else ""
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


def format_integer(value: int) -> str:
    """A whole number with the thousands mark of the chosen format (1 482 or 1,482)."""
    grouped = f"{abs(int(value)):,}".replace(",", _THIN_SPACE if current_format() == "fr" else ",")
    return f"-{grouped}" if value < 0 else grouped


def format_kilobytes(size: int) -> str:
    """The size of a file in kilobytes with one decimal (3,2 or 3.2): the unit goes in the template."""
    text = f"{size / 1024:,.1f}".replace(",", " ")
    if current_format() == "fr":
        return text.replace(".", ",")
    return text.replace(" ", ",")


def format_date(value: date) -> str:
    return format_date_as(value, current_format())


def format_date_as(value: date, number_format: str) -> str:
    # Le format américain met le mois avant le jour ; français et international
    # (en-GB) partagent jour/mois/année.
    if number_format == "en-US":
        return value.strftime("%m/%d/%Y")
    return value.strftime("%d/%m/%Y")


def format_short_date(value: date) -> str:
    """Day and month only (02/09), for lists where the year is obvious."""
    return format_short_date_as(value, current_format())


def format_short_date_as(value: date, number_format: str) -> str:
    if number_format == "en-US":
        return value.strftime("%m/%d")
    return value.strftime("%d/%m")


def format_plain_amount(value: Decimal) -> str:
    """Amount for an input field: no currency, the decimal mark of the chosen format (54,10 or 54.10)."""
    text = f"{value.quantize(Decimal('0.01')):.2f}"
    return text.replace(".", ",") if current_format() == "fr" else text
