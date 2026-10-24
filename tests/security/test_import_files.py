"""Import files: kept readable by the app only, removed after 24 hours, and
statements and backups refused beyond their size limit."""

import os
import stat
import tempfile
import time
from pathlib import Path

from backend import import_storage
from backend.routers import export as export_router


def _import_files() -> set[Path]:
    return set(Path(tempfile.gettempdir()).glob("finance-import-*"))


def test_a_saved_statement_is_readable_by_the_app_only():
    import_id = import_storage.save_upload(b"date;label;amount\n", ".csv")
    try:
        path = import_storage._upload_path(import_id, ".csv")
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert import_storage.read_upload(import_id, ".csv").startswith("date;label")
    finally:
        import_storage.delete_upload(import_id, ".csv")


def test_files_older_than_24_hours_are_removed_at_the_next_import():
    stale = Path(tempfile.gettempdir()) / "finance-import-0123456789abcdef0123456789abcdef.csv"
    recent = Path(tempfile.gettempdir()) / "finance-import-fedcba9876543210fedcba9876543210.csv"
    for path in (stale, recent):
        path.write_bytes(b"x")
    old = time.time() - 25 * 60 * 60
    os.utime(stale, (old, old))
    try:
        import_id = import_storage.save_upload(b"x", ".csv")
        import_storage.delete_upload(import_id, ".csv")

        assert not stale.exists()
        assert recent.exists()
    finally:
        stale.unlink(missing_ok=True)
        recent.unlink(missing_ok=True)


def test_a_statement_over_5_mb_is_refused_before_anything_is_saved(signed_in, security_data):
    before = _import_files()

    response = signed_in["admin"].post(
        "/imports/preview",
        files={"file": ("statement.csv", b"x" * (5 * 1024 * 1024 + 1), "text/csv")},
        data={"account_id": str(security_data["account_id"])},
    )

    assert response.status_code == 200
    assert "Fichier trop volumineux (5 Mo maximum)." in response.text
    assert _import_files() == before


def test_a_backup_over_the_limit_is_refused(signed_in, monkeypatch):
    monkeypatch.setattr(export_router, "RESTORE_MAX_MB", 1)
    monkeypatch.setitem(export_router._restore_progress, "status", "idle")

    response = signed_in["admin"].post(
        "/export/restore", files={"file": ("backup.json", b" " * (1024 * 1024 + 1), "application/json")}
    )

    assert response.status_code == 200
    assert "Fichier trop volumineux (1 Mo maximum)." in response.text
    assert export_router._restore_progress["status"] == "error"


def test_the_restore_limit_reads_its_setting():
    assert export_router._megabytes(None, 50) == 50
    assert export_router._megabytes("120", 50) == 120
    assert export_router._megabytes("lots", 50) == 50
