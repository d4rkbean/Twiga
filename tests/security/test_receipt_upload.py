"""Receipt PDFs: a size limit read in chunks, and pypdf 6 still reads a ticket."""

import io
from datetime import date
from decimal import Decimal

import pytest

from backend import crud
from backend.database import SessionLocal
from backend.models import ReceiptItem, Transaction


@pytest.fixture
def transaction_id(security_data):
    with SessionLocal() as db:
        transaction = Transaction(
            date=date.today(),
            label="Hypermarket",
            raw_label="HYPERMARKET",
            amount=Decimal("-12.50"),
            account_id=security_data["account_id"],
            validated=True,
        )
        db.add(transaction)
        db.commit()
        db.add(ReceiptItem(transaction_id=transaction.id, label="Milk", amount=Decimal("-1.20"), sort_order=0))
        db.commit()
        created = transaction.id
    yield created
    with SessionLocal() as db:
        db.query(ReceiptItem).filter(ReceiptItem.transaction_id == created).delete()
        db.query(Transaction).filter(Transaction.id == created).delete()
        db.commit()


def _blank_pdf() -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_a_receipt_pdf_over_5_mb_is_refused_and_the_detail_is_kept(signed_in, transaction_id):
    oversized = b"%PDF-1.4\n" + b"0" * (5 * 1024 * 1024)

    response = signed_in["editor"].post(
        f"/transactions/receipts/{transaction_id}/upload",
        files={"file": ("ticket.pdf", oversized, "application/pdf")},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 413
    assert "5 Mo" in response.text
    assert response.headers["HX-Reswap"] == "beforebegin"
    with SessionLocal() as db:
        assert [item.label for item in crud.get_receipt_items(db, transaction_id)] == ["Milk"]


def test_a_small_receipt_pdf_is_still_read(signed_in, transaction_id):
    response = signed_in["editor"].post(
        f"/transactions/receipts/{transaction_id}/upload",
        files={"file": ("ticket.pdf", _blank_pdf(), "application/pdf")},
    )

    assert response.status_code == 200
    assert f"receipt-section-{transaction_id}" in response.text
