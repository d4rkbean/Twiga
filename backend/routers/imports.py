import re
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from backend import crud, import_storage
from backend.database import get_db
from backend.models import Account
from backend.templating import templates
from imports import csv_parser, ofx_parser, qif_parser
from imports.common import ImportParseError, ParsedTransaction, split_duplicates
from backend.i18n import gettext as _t

router = APIRouter(prefix="/imports", tags=["imports"])

_SUPPORTED_FORMATS = {".csv": "csv", ".ofx": "ofx", ".qfx": "ofx", ".qif": "qif"}
_ALLOWED_FORMAT_VALUES = set(_SUPPORTED_FORMATS.values())
# import_id est toujours généré côté serveur par uuid.uuid4().hex
# (import_storage.save_upload) : 32 caractères hexadécimaux minuscules.
_IMPORT_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


def _detect_format(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    fmt = _SUPPORTED_FORMATS.get(suffix)
    if fmt is None:
        raise HTTPException(
            status_code=400, detail=_t("Format de fichier non reconnu (.qif, .csv ou .ofx attendu).")
        )
    return fmt


def _validate_import_ref(import_id: str, format: str) -> None:
    # import_id et format finissent tous les deux, non échappés, dans un nom
    # de fichier construit par import_storage._upload_path() ; sans cette
    # validation, un format="../../../../etc/passwd" fait sortir le chemin
    # résultant du répertoire temporaire (confirmé empiriquement), ouvrant un
    # oracle d'existence de fichiers, voire une suppression arbitraire via
    # delete_upload() en aval. /imports/preview passe déjà par
    # _detect_format() (whitelist stricte) ; confirm()/execute() reçoivent
    # "format" directement depuis un champ de formulaire client, jamais
    # revalidé jusqu'ici.
    if format not in _ALLOWED_FORMAT_VALUES:
        raise HTTPException(status_code=400, detail="Format d'import invalide.")
    if not _IMPORT_ID_PATTERN.fullmatch(import_id):
        raise HTTPException(status_code=400, detail="Identifiant d'import invalide.")


def _get_account(db: Session, account_id: int) -> Account:
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail=_t("Compte introuvable"))
    return account


def _error(request: Request, message: str) -> HTMLResponse:
    return templates.TemplateResponse("imports/_error.html", {"request": request, "error": message})


def _index_split(
    transactions: list[ParsedTransaction],
    existing_keys: set,
) -> tuple[list[ParsedTransaction], list[ParsedTransaction], dict[int, int]]:
    # Indexe chaque transaction par sa position dans le fichier source, pour
    # permettre à l'étape 3 de proposer une case à cocher par ligne (inclure/
    # exclure) sans avoir à faire persister la liste analysée entre confirm()
    # et execute() : le fichier est reparsé de façon déterministe aux deux
    # étapes, donc la position d'une transaction dans `transactions` reste
    # stable d'un appel à l'autre, tant que le fichier et le mapping de
    # colonnes (CSV) n'ont pas changé. id() sert de clé le temps de cet
    # appel (les objets restent référencés par unique/duplicates, jamais
    # récupérés par le GC entre-temps).
    unique, duplicates = split_duplicates(transactions, existing_keys)
    index_of = {id(tx): i for i, tx in enumerate(transactions)}
    return unique, duplicates, index_of


def _parse_indices(values: list[str]) -> set[int]:
    result: set[int] = set()
    for value in values:
        try:
            result.add(int(value))
        except (TypeError, ValueError):
            continue
    return result


def _parse_transactions(
    content: str,
    fmt: str,
    account_name: str,
    date_column: int | None,
    label_column: int | None,
    amount_column: int | None,
    date_format: str | None,
):
    if fmt == "csv":
        mapping = csv_parser.CsvColumnMapping(
            date_column=date_column, label_column=label_column, amount_column=amount_column
        )
        return csv_parser.parse_csv_transactions(content, account_name, mapping, date_format)
    return ofx_parser.parse_ofx_transactions(content, account_name)


@router.get("/new", response_class=HTMLResponse)
def new_import(request: Request, db: Session = Depends(get_db)):
    accounts = crud.list_accounts(db)
    return templates.TemplateResponse("imports/new.html", {"request": request, "accounts": accounts})


@router.post("/preview", response_class=HTMLResponse)
async def preview(
    request: Request,
    file: UploadFile = File(...),
    account_id: int | None = Form(None),
    db: Session = Depends(get_db),
):
    fmt = _detect_format(file.filename or "")
    raw_bytes = await file.read()
    import_id = import_storage.save_upload(raw_bytes, f".{fmt}")
    content = import_storage.read_upload(import_id, f".{fmt}")

    try:
        if fmt == "qif":
            result = qif_parser.parse_qif(content)
            context = {
                "request": request,
                "import_id": import_id,
                "accounts": result.accounts,
                "category_count": len(result.categories),
                "transaction_count": len(result.transactions),
                "payee_count": len(result.payees),
            }
            return templates.TemplateResponse("imports/_step2_qif.html", context)

        if account_id is None:
            import_storage.delete_upload(import_id, f".{fmt}")
            return _error(
                request,
                _t("Choisissez un compte existant, ou importez d'abord un fichier QIF pour en créer un."),
            )

        account = _get_account(db, account_id)

        if fmt == "csv":
            csv_preview = csv_parser.preview_csv(content)
            context = {
                "request": request,
                "import_id": import_id,
                "account": account,
                "preview": csv_preview,
                "date_format_choices": csv_parser.DATE_FORMAT_CHOICES,
            }
            return templates.TemplateResponse("imports/_step2_csv.html", context)

        transactions = ofx_parser.parse_ofx_transactions(content, account.name)
        context = {
            "request": request,
            "import_id": import_id,
            "account": account,
            "transactions": transactions[:20],
            "total_count": len(transactions),
        }
        return templates.TemplateResponse("imports/_step2_ofx.html", context)
    except ImportParseError as exc:
        import_storage.delete_upload(import_id, f".{fmt}")
        return _error(request, str(exc))


@router.post("/{import_id}/confirm", response_class=HTMLResponse)
def confirm(
    request: Request,
    import_id: str,
    format: str = Form(...),
    account_id: int | None = Form(None),
    date_column: int | None = Form(None),
    label_column: int | None = Form(None),
    amount_column: int | None = Form(None),
    date_format: str | None = Form(None),
    db: Session = Depends(get_db),
):
    _validate_import_ref(import_id, format)
    content = import_storage.read_upload(import_id, f".{format}")

    if format == "qif":
        try:
            result = qif_parser.parse_qif(content)
        except ImportParseError as exc:
            return _error(request, str(exc))

        existing_keys = crud.get_existing_transaction_keys(db)
        unique, duplicates = split_duplicates(result.transactions, existing_keys)
        existing_account_names = crud.get_existing_account_names(db)
        new_account_count = sum(1 for a in result.accounts if a.name not in existing_account_names)

        context = {
            "request": request,
            "import_id": import_id,
            "new_account_count": new_account_count,
            "existing_account_count": len(result.accounts) - new_account_count,
            "category_count": len(result.categories),
            "total_count": len(result.transactions),
            "unique_count": len(unique),
            "duplicate_count": len(duplicates),
        }
        return templates.TemplateResponse("imports/_step3_qif.html", context)

    account = _get_account(db, account_id) if account_id is not None else None
    if account is None:
        return _error(request, _t("Compte manquant pour cet import."))

    try:
        transactions = _parse_transactions(
            content, format, account.name, date_column, label_column, amount_column, date_format
        )
    except ImportParseError as exc:
        return _error(request, str(exc))

    existing_keys = crud.get_existing_transaction_keys(db)
    unique, duplicates, index_of = _index_split(transactions, existing_keys)

    context = {
        "request": request,
        "import_id": import_id,
        "format": format,
        "account": account,
        "date_column": date_column,
        "label_column": label_column,
        "amount_column": amount_column,
        "date_format": date_format,
        "total_count": len(transactions),
        "unique_count": len(unique),
        "duplicate_count": len(duplicates),
        "unique": [(index_of[id(tx)], tx) for tx in unique],
        "duplicates": [(index_of[id(tx)], tx) for tx in duplicates],
    }
    return templates.TemplateResponse("imports/_step3_confirm.html", context)


@router.post("/{import_id}/execute", response_class=HTMLResponse)
async def execute(
    request: Request,
    import_id: str,
    format: str = Form(...),
    account_id: int | None = Form(None),
    date_column: int | None = Form(None),
    label_column: int | None = Form(None),
    amount_column: int | None = Form(None),
    date_format: str | None = Form(None),
    db: Session = Depends(get_db),
):
    _validate_import_ref(import_id, format)
    content = import_storage.read_upload(import_id, f".{format}")

    if format == "qif":
        try:
            result = qif_parser.parse_qif(content)
        except ImportParseError as exc:
            return _error(request, str(exc))

        result_summary = crud.import_qif_result(db, result)
        import_storage.delete_upload(import_id, f".{format}")

        context = {"request": request, **result_summary}
        return templates.TemplateResponse("imports/_result.html", context)

    account = _get_account(db, account_id) if account_id is not None else None
    if account is None:
        return _error(request, _t("Compte manquant pour cet import."))

    try:
        transactions = _parse_transactions(
            content, format, account.name, date_column, label_column, amount_column, date_format
        )
    except ImportParseError as exc:
        return _error(request, str(exc))

    existing_keys = crud.get_existing_transaction_keys(db)
    unique, duplicates, index_of = _index_split(transactions, existing_keys)

    # Champs répétés (une case à cocher par ligne à l'étape 3) : lus
    # directement depuis le formulaire brut plutôt que déclarés en
    # `list[int] = Form(...)`, pour ne pas dépendre d'une version précise de
    # FastAPI/Starlette pour ce cas — la Request est déjà parsée une fois
    # (les paramètres Form(...) ci-dessus l'ont fait), request.form() ne fait
    # que relire le résultat mis en cache.
    form = await request.form()
    included = _parse_indices(form.getlist("include"))
    forced = _parse_indices(form.getlist("force_include"))

    selected = [tx for tx in unique if index_of[id(tx)] in included]
    forced_txs = [tx for tx in duplicates if index_of[id(tx)] in forced]
    selected.extend(forced_txs)

    result_summary = crud.bulk_insert_transactions(db, account, selected)

    import_storage.delete_upload(import_id, f".{format}")

    context = {
        "request": request,
        "duplicate_count": len(duplicates) - len(forced_txs),
        "excluded_count": len(unique) - len(selected) + len(forced_txs),
        **result_summary,
    }
    return templates.TemplateResponse("imports/_result.html", context)
