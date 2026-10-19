"""bcrypt reads 72 bytes at most: a longer new password is refused everywhere a
password is set."""

import pytest

from backend import crud
from backend.database import SessionLocal
from tests.security.conftest import sign_in

# 37 characters but 74 bytes in UTF-8: refused although it looks short.
TOO_LONG = "é" * 37
LONGEST = "a" * 72


@pytest.fixture
def account(security_data):
    with SessionLocal() as db:
        user_id = crud.create_user(db, "sec_length", "length-password", "viewer").id
    yield user_id
    with SessionLocal() as db:
        crud.delete_user(db, user_id)


def _user_names() -> set[str]:
    with SessionLocal() as db:
        return {user.username for user in crud.list_users(db)}


def test_changing_ones_own_password_refuses_more_than_72_bytes(new_client, account):
    client = new_client()
    sign_in(client, "sec_length", "length-password")

    response = client.post(
        "/settings/change-password",
        data={"current_password": "length-password", "new_password": TOO_LONG, "confirm_password": TOO_LONG},
    )

    assert response.status_code == 400
    assert "72 caractères au plus" in response.text
    sign_in(new_client(), "sec_length", "length-password")  # unchanged


def test_creating_an_account_refuses_more_than_72_bytes(signed_in):
    response = signed_in["admin"].post(
        "/users/create", data={"username": "sec_too_long", "password": TOO_LONG, "role": "viewer"}
    )

    assert response.status_code == 400
    assert "72 caractères au plus" in response.text
    assert "sec_too_long" not in _user_names()


def test_72_bytes_are_still_accepted(signed_in):
    response = signed_in["admin"].post(
        "/users/create", data={"username": "sec_longest", "password": LONGEST, "role": "viewer"}
    )
    try:
        assert response.status_code == 200
        assert "sec_longest" in _user_names()
    finally:
        with SessionLocal() as db:
            user = crud.get_user_by_username(db, "sec_longest")
            if user is not None:
                crud.delete_user(db, user.id)


def test_resetting_a_password_refuses_more_than_72_bytes(signed_in, account):
    response = signed_in["admin"].post(f"/users/{account}/password", data={"new_password": TOO_LONG})

    assert response.status_code == 400
    assert "72 caractères au plus" in response.text
