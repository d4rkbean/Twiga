import tempfile
import uuid
from pathlib import Path


def _upload_path(import_id: str, suffix: str) -> Path:
    return Path(tempfile.gettempdir()) / f"finance-import-{import_id}{suffix}"


def save_upload(content: bytes, suffix: str) -> str:
    import_id = uuid.uuid4().hex
    _upload_path(import_id, suffix).write_bytes(content)
    return import_id


def read_upload(import_id: str, suffix: str) -> str:
    path = _upload_path(import_id, suffix)
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


def delete_upload(import_id: str, suffix: str) -> None:
    _upload_path(import_id, suffix).unlink(missing_ok=True)
    _name_path(import_id, suffix).unlink(missing_ok=True)


def _name_path(import_id: str, suffix: str) -> Path:
    return Path(tempfile.gettempdir()) / f"finance-import-{import_id}{suffix}.name"


def save_name(import_id: str, suffix: str, filename: str) -> None:
    """Remembers the uploaded file's own name, for the import history."""
    _name_path(import_id, suffix).write_text(filename, encoding="utf-8")


def read_name(import_id: str, suffix: str) -> str:
    try:
        return _name_path(import_id, suffix).read_text(encoding="utf-8")
    except OSError:
        return f"import{suffix}"
