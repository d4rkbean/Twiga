"""The session cookie gains Secure over HTTPS (COOKIE_SECURE=auto), keeps HttpOnly
and SameSite=Lax, and HTTPS responses carry HSTS."""

import pytest

from backend import auth, security_headers
from tests.security.conftest import PASSWORD


def _session_cookie(response) -> str:
    cookies = [value for value in response.headers.get_list("set-cookie") if value.startswith(auth.SESSION_COOKIE_NAME)]
    assert len(cookies) == 1, response.headers
    return cookies[0].lower()


def _sign_in(client, **headers):
    response = client.post("/login", data={"username": "sec_viewer", "password": PASSWORD}, headers=headers)
    assert response.status_code == 200, response.text
    return response


def test_over_https_the_session_cookie_is_secure_and_hsts_is_sent(new_client):
    response = _sign_in(new_client(base_url="https://testserver"))

    cookie = _session_cookie(response)
    assert "; secure" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    assert response.headers["strict-transport-security"] == "max-age=31536000"


def test_behind_an_https_proxy_the_session_cookie_is_secure(new_client):
    response = _sign_in(new_client(), **{"X-Forwarded-Proto": "https"})

    assert "; secure" in _session_cookie(response)
    assert "strict-transport-security" in response.headers


def test_over_plain_http_nothing_changes(new_client):
    response = _sign_in(new_client())

    cookie = _session_cookie(response)
    assert "secure" not in cookie and "httponly" in cookie and "samesite=lax" in cookie
    assert "strict-transport-security" not in response.headers


@pytest.mark.parametrize(("setting", "base_url", "secure"), [
    ("false", "https://testserver", False),
    ("true", "http://testserver", True),
])
def test_cookie_secure_can_be_forced(new_client, monkeypatch, setting, base_url, secure):
    monkeypatch.setattr(security_headers, "COOKIE_SECURE", setting)

    response = _sign_in(new_client(base_url=base_url))

    assert ("; secure" in _session_cookie(response)) is secure
