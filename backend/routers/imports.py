import re
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import crud, import_storage
from backend.database import get_db
from backend.models import Account, Rule
from backend.templating import templates
from imports import csv_parser, ofx_parser, qif_parser
from imports.common import ImportParseError, ParsedTransaction, split_duplicates
from backend.i18n import gettext as _t

router = APIRouter(prefix="/imports", tags=["imports"])

# Same limit as announced on the drop zone ("5 Mo maximum").
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
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


def _history_context(db: Session) -> dict:
    logs = crud.list_import_logs(db)
    return {"import_logs": logs, "import_logs_total": sum(log.imported for log in logs)}


def _classify(unique: list, rules: list) -> dict[int, tuple[str, str | None]]:
    """What the "État" column says about each new row: a rule that will file
    it ("rule"), a detected transfer ("transfer", with the other account) or
    nothing yet ("sort")."""
    states: dict[int, tuple[str, str | None]] = {}
    for tx in unique:
        if tx.transfer_account:
            states[id(tx)] = ("transfer", tx.transfer_account)
            continue
        lowered = tx.label.lower()
        matched = any(rule.keyword.lower() in lowered for rule in rules)
        states[id(tx)] = ("rule", None) if matched else ("sort", None)
    return states


def _step2_response(
    request: Request, db: Session, import_id: str, fmt: str, account_id: int | None
) -> HTMLResponse:
    """The "second step" screen of a stored upload (columns, preview, QIF
    summary). Shared by the first pass and by the "Précédent" button."""
    content = import_storage.read_upload(import_id, f".{fmt}")
    if fmt == "qif":
        result = qif_parser.parse_qif(content)
        existing_names = crud.get_existing_account_names(db)
        context = {
            "request": request,
            "import_id": import_id,
            "accounts": [(a, a.name in existing_names) for a in result.accounts],
            "category_count": len(result.categories),
            "transaction_count": len(result.transactions),
            "payee_count": len(result.payees),
        }
        return templates.TemplateResponse("imports/_step2_qif.html", context)

    account = _get_account(db, account_id) if account_id is not None else None
    if account is None:
        return _error(request, _t("Compte manquant pour cet import."))

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
        "transactions": transactions[:8],
        "total_count": len(transactions),
    }
    return templates.TemplateResponse("imports/_step2_ofx.html", context)


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
    context = {"request": request, "accounts": accounts, **_history_context(db)}
    return templates.TemplateResponse("imports/new.html", context)


@router.get("/step1", response_class=HTMLResponse)
def step1(request: Request, db: Session = Depends(get_db)):
    """First step on its own: the target of "Précédent" on the second step."""
    context = {"request": request, "accounts": crud.list_accounts(db)}
    return templates.TemplateResponse("imports/_step1_file.html", context)


@router.get("/back", response_class=HTMLResponse)
def back_to_step2(
    request: Request,
    import_id: str,
    format: str,
    account_id: int | None = None,
    db: Session = Depends(get_db),
):
    """"Précédent" on the third step: the stored file is read again. When the
    upload is gone (temporary file cleaned up), the wizard starts over."""
    if format not in _ALLOWED_FORMAT_VALUES or not _IMPORT_ID_PATTERN.fullmatch(import_id):
        return step1(request, db)
    try:
        return _step2_response(request, db, import_id, format, account_id)
    except (FileNotFoundError, ImportParseError):
        return step1(request, db)


@router.post("/preview", response_class=HTMLResponse)
async def preview(
    request: Request,
    file: UploadFile = File(...),
    account_id: int | None = Form(None),
    db: Session = Depends(get_db),
):
    fmt = _detect_format(file.filename or "")
    raw_bytes = await file.read()
    if len(raw_bytes) > MAX_UPLOAD_BYTES:
        return _error(request, _t("Fichier trop volumineux (5 Mo maximum)."))
    if fmt != "qif" and account_id is None:
        return _error(
            request,
            _t("Choisis un compte existant, ou importe d'abord un fichier QIF pour en créer un."),
        )

    import_id = import_storage.save_upload(raw_bytes, f".{fmt}")
    import_storage.save_name(import_id, f".{fmt}", Path(file.filename or "").name)
    try:
        return _step2_response(request, db, import_id, fmt, account_id)
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
    states = _classify(unique, db.execute(select(Rule)).scalars().all())

    context = {
        "request": request,
        "import_id": import_id,
        "format": format,
        "states": {index_of[id(tx)]: states[id(tx)] for tx in unique},
        "transfer_count": sum(1 for state in states.values() if state[0] == "transfer"),
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
        crud.record_import_log(
            db,
            import_storage.read_name(import_id, f".{format}"),
            _t("Tous les comptes"),
            len(result.transactions),
            result_summary["duplicate_count"],
            result_summary["imported_count"],
        )
        import_storage.delete_upload(import_id, f".{format}")

        context = {"request": request, **_history_context(db), **result_summary}
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
    crud.record_import_log(
        db,
        import_storage.read_name(import_id, f".{format}"),
        account.name,
        len(transactions),
        len(duplicates) - len(forced_txs),
        result_summary["imported_count"],
    )

    import_storage.delete_upload(import_id, f".{format}")

    context = {
        "request": request,
        **_history_context(db),
        "duplicate_count": len(duplicates) - len(forced_txs),
        "excluded_count": len(unique) - len(selected) + len(forced_txs),
        **result_summary,
    }
    return templates.TemplateResponse("imports/_result.html", context)
