"""An unknown or inactive username costs the same bcrypt check as a real one."""

import bcrypt
import pytest

from backend import auth, crud
from backend.database import SessionLocal


@pytest.fixture
def checks(monkeypatch):
    calls = []
    real_checkpw = bcrypt.checkpw

    def counting_checkpw(password, hashed):
        calls.append(hashed)
        return real_checkpw(password, hashed)

    monkeypatch.setattr(bcrypt, "checkpw", counting_checkpw)
    return calls


def test_an_unknown_username_still_runs_one_bcrypt_check(security_data, checks):
    with SessionLocal() as db:
        assert auth.verify_password(db, "nobody-here", "whatever") is None

    assert len(checks) == 1
    assert checks[0].startswith(b"$2b$12$")  # the cost of the real hashes


def test_an_inactive_account_still_runs_one_bcrypt_check(security_data, checks):
    with SessionLocal() as db:
        user_id = crud.create_user(db, "sec_inactive", "inactive-password", "viewer").id
        crud.set_user_active(db, user_id, False)
    try:
        with SessionLocal() as db:
            assert auth.verify_password(db, "sec_inactive", "inactive-password") is None
        assert len(checks) == 1
    finally:
        with SessionLocal() as db:
            crud.delete_user(db, user_id)


def test_a_real_account_runs_one_bcrypt_check(security_data, checks):
    with SessionLocal() as db:
        assert auth.verify_password(db, "sec_viewer", "test-password") is not None

    assert len(checks) == 1
