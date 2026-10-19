"""Where the minus sign is typographic and where it stays a plain hyphen.

Everything shown on a page uses the true minus sign (U+2212). Anything a
spreadsheet or a script reads back (CSV and JSON exports) keeps the ASCII
hyphen-minus.
"""

from datetime import date, timedelta
from decimal import Decimal

from backend.formatting import format_amount_as, format_amount_for_export

MINUS = "−"


def test_display_and_export_differ_only_by_the_minus_sign():
    assert format_amount_as(Decimal("-12.99"), "fr") == f"{MINUS}12,99 €"
    assert format_amount_as(Decimal("-12.99"), "fr", ascii_minus=True) == "-12,99 €"
    assert format_amount_as(Decimal("-12.99"), "en-US", ascii_minus=True) == "-€12.99"
    assert format_amount_for_export(Decimal("12.99")) == "12,99 €"


def test_a_page_shows_the_true_minus_sign(clients):
    html = clients["admin"].get(
        "/transactions/list/content", headers={"HX-Request": "true"}
    ).text
    assert f"{MINUS}750,00" in html
    assert "-750,00" not in html


def test_the_report_export_keeps_the_ascii_hyphen(clients):
    # The day of the demo rent: no income that day, so the result is negative.
    rent_day = date.today().replace(day=1) + timedelta(days=2)
    response = clients["admin"].get(
        f"/reports/export.csv?period_type=personnalise&date_from={rent_day}&date_to={rent_day}"
    )
    assert response.status_code == 200
    assert MINUS not in response.text
    assert "Résultat;-750,00 €" in response.text


def test_the_operations_exports_keep_the_ascii_hyphen(clients):
    csv_export = clients["admin"].get("/export/transactions.csv")
    assert csv_export.status_code == 200
    assert ";-750.00;" in csv_export.text
    assert MINUS not in csv_export.text

    report_rows = clients["admin"].get("/reports/transactions/export.csv?period_type=annee")
    assert MINUS not in report_rows.text
    assert report_rows.status_code == 200

    json_export = clients["admin"].get("/export/json")
    assert MINUS not in json_export.text
