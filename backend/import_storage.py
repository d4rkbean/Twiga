import os
import tempfile
import time
import uuid
from pathlib import Path

# A statement left half-way through the import wizard is not kept forever:
# files older than this are removed at start-up and before every new import.
_MAX_AGE_SECONDS = 24 * 60 * 60


def _upload_path(import_id: str, suffix: str) -> Path:
    return Path(tempfile.gettempdir()) / f"finance-import-{import_id}{suffix}"


def purge_stale_uploads() -> None:
    now = time.time()
    for path in Path(tempfile.gettempdir()).glob("finance-import-*"):
        try:
            if now - path.stat().st_mtime > _MAX_AGE_SECONDS:
                path.unlink(missing_ok=True)
        except OSError:
            pass


def save_upload(content: bytes, suffix: str) -> str:
    purge_stale_uploads()
    import_id = uuid.uuid4().hex
    # Readable by the application's own user only: a bank statement.
    descriptor = os.open(_upload_path(import_id, suffix), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as file:
        file.write(content)
    return import_id


def read_upload(import_id: str, suffix: str) -> str:
    path = _upload_path(import_id, suffix)
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


def delete_upload(import_id: str, suffix: str) -> None:
    _upload_path(import_id, suffix).unlink(missing_ok=True)
