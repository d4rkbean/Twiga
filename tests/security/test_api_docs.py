"""The generated API documentation is not served."""

import pytest


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"])
def test_the_api_documentation_is_not_served(signed_in, path):
    assert signed_in["admin"].get(path).status_code == 404
