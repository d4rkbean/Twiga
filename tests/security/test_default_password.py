"""An account signed in with the default password "changeme" is sent to the
password change until it picks another one."""

import logging

import pytest

from backend import crud, password_change
from backend.database import SessionLocal
from tests.security.conftest import sign_in

USERNAME = "sec_default"


@pytest.fixture
def default_account(security_data):
    with SessionLocal() as db:
        user_id = crud.create_user(db, USERNAME, "changeme", "admin").id
    yield user_id
    with SessionLocal() as db:
        crud.delete_user(db, user_id)


@pytest.fixture
def client(new_client, default_account):
    client = new_client()
    sign_in(client, USERNAME, "changeme")
    return client


def test_every_page_leads_to_the_password_change(client):
    for path in ("/dashboard", "/transactions/inbox", "/profile", "/settings"):
        response = client.get(path)

        assert response.status_code == 303, path
        assert response.headers["location"] == "/profile/password"


def test_the_change_screen_is_mon_profil_with_a_notice(client):
    response = client.get("/profile/password")

    assert response.status_code == 200
    assert "encore celui par défaut" in response.text
    assert 'hx-post="/settings/change-password"' in response.text


def test_other_actions_are_refused_until_the_password_is_changed(client, security_data):
    response = client.post(
        "/settings/cap-income-source", data={"income_source": "manual"}, headers={"HX-Request": "true"}
    )
    fragment = client.get("/transactions/list/content", headers={"HX-Request": "true"})

    assert response.status_code == 403
    assert "Change d'abord ton mot de passe" in response.text
    # A fragment the change page loads by itself is left out, without an error.
    assert fragment.status_code == 204


def test_the_static_files_and_signing_out_stay_open(client):
    assert client.get("/static/js/htmx-config.js").status_code == 200
    assert client.post("/logout").status_code == 200


def test_a_successful_change_sends_back_to_the_application():
    # Checked on the middleware alone: the answer of the change route itself is
    # not what this test is about.
    import bcrypt
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse
    from fastapi.testclient import TestClient

    class Account:
        hashed_password = bcrypt.hashpw(b"changeme", bcrypt.gensalt(4)).decode()

    app = FastAPI()
    app.add_middleware(password_change.PasswordChangeMiddleware)

    @app.middleware("http")
    async def signed_in(request: Request, call_next):
        request.state.user = Account()
        return await call_next(request)

    @app.post("/settings/change-password")
    def change(request: Request):
        return HTMLResponse("ok", status_code=200 if request.query_params.get("ok") else 400)

    client = TestClient(app)

    assert client.post("/settings/change-password?ok=1").headers["HX-Redirect"] == "/dashboard"
    assert "HX-Redirect" not in client.post("/settings/change-password").headers


def test_once_changed_the_account_gets_back_to_the_application(new_client, default_account):
    with SessionLocal() as db:
        crud.set_user_password(db, default_account, "a-new-password")
    client = new_client()
    sign_in(client, USERNAME, "a-new-password")

    assert client.get("/dashboard").status_code == 200


def test_another_password_is_not_affected(signed_in):
    assert signed_in["editor"].get("/dashboard").status_code == 200


def test_the_start_warns_when_auth_password_or_an_account_is_the_default(default_account, monkeypatch, caplog):
    monkeypatch.setenv("AUTH_PASSWORD", "changeme")

    with caplog.at_level(logging.WARNING, logger="twiga.security"):
        password_change.warn_about_default_passwords()

    assert "AUTH_PASSWORD is the default value" in caplog.text
    assert USERNAME in caplog.text


def test_no_warning_once_auth_password_is_changed(security_data, monkeypatch, caplog):
    monkeypatch.setenv("AUTH_PASSWORD", "something-else")

    with caplog.at_level(logging.WARNING, logger="twiga.security"):
        password_change.warn_about_default_passwords()

    assert "AUTH_PASSWORD" not in caplog.text
