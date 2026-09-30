from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from backend import crud, receipts_storage
from backend.database import get_db
from backend.models import ReceiptItem, Transaction
from backend.receipt_families import RECEIPT_FAMILIES, group_items_by_family
from backend.templating import templates

# Préfixe /transactions/receipts (pas /receipts) : reste sous le préfixe déjà
# whitelisté "écriture éditeur" dans backend.auth._EDITOR_WRITE_PREFIXES,
# sans avoir à y toucher — un éditeur peut ajouter/modifier une ligne de
# ticket comme il peut modifier n'importe quelle autre opération ; les
# routes contenant "delete" restent réservées à l'admin par la même règle
# générique que partout ailleurs dans l'app.
router = APIRouter(prefix="/transactions/receipts", tags=["receipts"])


def _parse_amount(raw: str | None) -> Decimal:
    if not raw:
        return Decimal("0.00")
    try:
        return Decimal(raw.strip().replace(",", "."))
    except InvalidOperation:
        return Decimal("0.00")


def _get_transaction_or_404(db: Session, transaction_id: int) -> Transaction:
    transaction = db.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction introuvable")
    return transaction


def _render_section(
    request: Request, db: Session, transaction: Transaction, raw_extracted_text: str | None = None
):
    receipt_items = crud.get_receipt_items(db, transaction.id)
    context = {
        "request": request,
        "transaction": transaction,
        "receipt_items": receipt_items,
        "receipt_groups": group_items_by_family(receipt_items),
        "receipt_families": RECEIPT_FAMILIES,
        # Affiché UNE FOIS, juste après un upload (jamais persisté, jamais
        # ressorti sur un rechargement normal de la fiche) : le fichier
        # source n'est pas conservé, donc c'est la seule occasion de voir ce
        # que pypdf en a réellement tiré si l'extraction automatique des
        # lignes rate des articles — sert à corriger à la main ou à me
        # transmettre un extrait pour ajuster l'heuristique.
        "raw_extracted_text": raw_extracted_text,
    }
    return templates.TemplateResponse("transactions/_receipt.html", context)


@router.get("/{transaction_id}/section", response_class=HTMLResponse)
def receipt_section(request: Request, transaction_id: int, db: Session = Depends(get_db)):
    transaction = _get_transaction_or_404(db, transaction_id)
    return _render_section(request, db, transaction)


@router.post("/{transaction_id}/upload", response_class=HTMLResponse)
async def upload_receipt(
    request: Request,
    transaction_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    transaction = _get_transaction_or_404(db, transaction_id)

    # Le fichier n'est jamais conservé : lu en mémoire le temps d'en
    # extraire le texte, puis jeté avec la fin de la requête — seules les
    # lignes qui en sont tirées sont enregistrées (voir receipts_storage).
    # Uniquement pour un PDF : une photo n'a pas de calque de texte à
    # extraire sans OCR (délibérément hors scope, voir la discussion
    # produit) — son seul usage possible ici serait la saisie manuelle des
    # lignes, déjà couverte par "+ Ajouter une ligne".
    raw_text = None
    if (file.filename or "").lower().endswith(".pdf"):
        content = await file.read()
        try:
            raw_text = receipts_storage.extract_pdf_text(content)
        except Exception:
            raw_text = ""
        suggested = receipts_storage.parse_receipt_lines(raw_text)
        if suggested:
            # Remplace le détail précédent au lieu de s'y ajouter : ré-importer
            # la même facture (typiquement après un premier essai raté) ne doit
            # pas doubler toutes les lignes.
            crud.delete_receipt_items_for_transaction(db, transaction.id)
            crud.bulk_add_receipt_items(db, transaction.id, suggested)

    return _render_section(request, db, transaction, raw_extracted_text=raw_text)


@router.post("/{transaction_id}/items/add", response_class=HTMLResponse)
def add_receipt_item_route(
    request: Request,
    transaction_id: int,
    label: str = Form(""),
    amount: str = Form(""),
    family: str = Form(""),
    db: Session = Depends(get_db),
):
    transaction = _get_transaction_or_404(db, transaction_id)
    crud.add_receipt_item(
        db,
        transaction_id,
        label=label.strip() or "Article",
        amount=_parse_amount(amount),
        family=family or None,
    )
    return _render_section(request, db, transaction)


@router.post("/items/{item_id}/update", response_class=HTMLResponse)
def update_receipt_item_route(
    request: Request,
    item_id: int,
    label: str = Form(""),
    amount: str = Form(""),
    family: str = Form(""),
    db: Session = Depends(get_db),
):
    item = db.get(ReceiptItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Ligne introuvable")
    crud.update_receipt_item(
        db,
        item,
        label=label.strip() or "Article",
        amount=_parse_amount(amount),
        family=family or None,
    )
    return _render_section(request, db, item.transaction)


@router.post("/items/{item_id}/delete", response_class=HTMLResponse)
def delete_receipt_item_route(request: Request, item_id: int, db: Session = Depends(get_db)):
    item = db.get(ReceiptItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Ligne introuvable")
    transaction = item.transaction
    crud.delete_receipt_item(db, item)
    return _render_section(request, db, transaction)
