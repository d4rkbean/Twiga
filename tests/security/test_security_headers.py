"""Security headers on every answer: pages, fragments, static files, refusals."""

import pytest

from backend import security_headers


@pytest.mark.parametrize("path", ["/dashboard", "/static/js/htmx-config.js", "/health"])
def test_the_security_headers_are_on_every_answer(signed_in, path):
    headers = signed_in["admin"].get(path).headers

    csp = headers["content-security-policy"]
    for directive in ("default-src 'self'", "frame-ancestors 'none'", "object-src 'none'", "form-action 'self'"):
        assert directive in csp
    assert "camera=()" in headers["permissions-policy"]
    assert headers["x-xss-protection"] == "0"
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "strict-origin-when-cross-origin"


def test_a_refused_request_carries_them_too(signed_in):
    response = signed_in["admin"].post("/settings/cap-income-source", headers={"origin": "https://evil.example"})

    assert response.status_code == 403
    assert "content-security-policy" in response.headers


def test_the_policy_allows_only_twiga_itself():
    assert "http" not in security_headers._CSP
    assert "*" not in security_headers._CSP
