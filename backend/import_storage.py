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
