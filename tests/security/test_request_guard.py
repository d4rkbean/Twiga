"""Forms sent by another site are refused, with and without authentication, and
ALLOWED_HOSTS refuses unknown host names."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import crud, request_guard
from backend.database import SessionLocal

SETTING = "/settings/cap-income-source"
OTHER_SITE = "https://evil.example"


def _income_source() -> str:
    with SessionLocal() as db:
        return crud.get_cap_settings(db).income_source


def _post_setting(client, value: str, **headers):
    return client.post(SETTING, data={"income_source": value}, headers=headers)


@pytest.fixture
def reset_income_source():
    before = _income_source()
    yield
    with SessionLocal() as db:
        crud.get_cap_settings(db).income_source = before
        db.commit()


def _other_value() -> str:
    current = _income_source()
    return next(code for code in crud.INCOME_SOURCE_CODES if code != current)


def test_a_post_from_another_site_is_refused_and_changes_nothing(signed_in, reset_income_source):
    before = _income_source()

    response = _post_setting(signed_in["admin"], _other_value(), origin=OTHER_SITE)

    assert response.status_code == 403
    assert "ne vient pas de Twiga" in response.text
    assert _income_source() == before


def test_a_post_from_twiga_itself_is_accepted(signed_in, reset_income_source):
    value = _other_value()

    response = _post_setting(signed_in["admin"], value, origin="http://testserver")

    assert response.status_code == 200
    assert _income_source() == value


def test_an_htmx_post_from_the_same_page_is_accepted(signed_in, reset_income_source):
    response = _post_setting(
        signed_in["admin"],
        _other_value(),
        origin="http://testserver",
        referer="http://testserver/settings",
        **{"HX-Request": "true"},
    )

    assert response.status_code == 200


def test_a_post_without_origin_nor_referer_is_accepted(signed_in, reset_income_source):
    response = _post_setting(signed_in["admin"], _other_value())

    assert response.status_code == 200


def test_the_referer_is_checked_when_there_is_no_origin(signed_in, reset_income_source):
    refused = _post_setting(signed_in["admin"], _other_value(), referer=f"{OTHER_SITE}/page")
    accepted = _post_setting(signed_in["admin"], _other_value(), referer="http://testserver/settings")

    assert refused.status_code == 403
    assert accepted.status_code == 200


def test_the_address_given_by_a_reverse_proxy_is_accepted(signed_in, reset_income_source):
    response = _post_setting(
        signed_in["admin"],
        _other_value(),
        origin="https://twiga.example.com",
        **{"X-Forwarded-Host": "twiga.example.com"},
    )

    assert response.status_code == 200


def test_an_origin_listed_in_trusted_origins_is_accepted(signed_in, reset_income_source, monkeypatch):
    monkeypatch.setattr(request_guard, "TRUSTED_ORIGINS", ["https://twiga.example.com"])

    accepted = _post_setting(signed_in["admin"], _other_value(), origin="https://twiga.example.com")
    refused = _post_setting(signed_in["admin"], _other_value(), origin=OTHER_SITE)

    assert accepted.status_code == 200
    assert refused.status_code == 403


def test_signing_in_from_another_site_is_refused(new_client):
    response = new_client().post(
        "/login", data={"username": "sec_admin", "password": "test-password"}, headers={"origin": OTHER_SITE}
    )

    assert response.status_code == 403
    assert "set-cookie" not in response.headers


def test_without_authentication_a_post_from_another_site_is_refused_too():
    # AUTH_ENABLED is read at import time: the middleware is tested on its own,
    # in front of a route that anyone may call, as every route is without
    # authentication.
    app = FastAPI()
    app.add_middleware(request_guard.RequestGuardMiddleware)

    @app.post("/write")
    def write():
        return {"written": True}

    client = TestClient(app)

    assert client.post("/write", headers={"origin": OTHER_SITE}).status_code == 403
    assert client.post("/write", headers={"origin": "http://testserver"}).status_code == 200
    assert client.post("/write").status_code == 200
    assert client.get("/write", headers={"origin": OTHER_SITE}).status_code == 405  # safe method: not checked


def test_allowed_hosts_refuses_other_host_names(signed_in, monkeypatch):
    monkeypatch.setattr(request_guard, "ALLOWED_HOSTS", ["twiga.local", "testserver"])
    client = signed_in["admin"]

    assert client.get("/dashboard", headers={"host": "attacker.example"}).status_code == 400
    assert client.get("/dashboard", headers={"host": "twiga.local:8181"}).status_code == 200
    assert client.get("/dashboard").status_code == 200
    assert client.get("/health", headers={"host": "attacker.example"}).status_code == 200


def test_every_host_name_is_accepted_when_allowed_hosts_is_empty(signed_in):
    assert request_guard.ALLOWED_HOSTS == []
    assert signed_in["admin"].get("/dashboard", headers={"host": "any.example"}).status_code == 200
