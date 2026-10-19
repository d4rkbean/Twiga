"""Fixtures of the security tests: a throwaway PostgreSQL database built by the
real Alembic migrations, three accounts (one per role) and a signed-in HTTP
client for each.

PostgreSQL is mandatory (crud.py relies on date_trunc, extract, ilike): run the
suite against a database whose name ends in "_test", it is dropped and rebuilt.
"""

import os
from decimal import Decimal
from pathlib import Path

# Must be set before backend.* is imported: authentication is read from the
# environment at import time.
os.environ["AUTH_ENABLED"] = "true"

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]

ROLES = ("admin", "editor", "viewer")
PASSWORD = "test-password"


@pytest.fixture(scope="session")
def security_data():
    """Builds the schema with Alembic and adds the accounts the tests use."""
    from backend import crud
    from backend.database import SessionLocal, engine

    # Dropping the schema below is only acceptable on a throwaway database.
    assert engine.url.database.endswith("_test"), (
        f"refusing to reset database {engine.url.database!r}: use a *_test database"
    )
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    command.upgrade(config, "head")

    ids = {}
    with SessionLocal() as db:
        for role in ROLES:
            ids[f"user_{role}"] = crud.create_user(db, f"sec_{role}", PASSWORD, role).id
        account = crud.create_account(db, "Security checking", "courant", Decimal("100.00"))
        ids["account_id"] = account.id
        category = crud.create_category(db, "Security food", None)
        ids["category_id"] = category.id
    return ids


@pytest.fixture(scope="session")
def security_app(security_data):
    from backend.main import app

    return app


@pytest.fixture(autouse=True)
def reset_login_attempts():
    """Failed sign-ins are kept in memory: every test starts with none."""
    yield
    from backend.routers import auth as auth_router

    auth_router._failed_attempts.clear()


def sign_in(client, username: str, password: str = PASSWORD):
    response = client.post("/login", data={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response


@pytest.fixture(scope="session")
def signed_in(security_app):
    """One signed-in client per role, plus an anonymous one, keyed by role name."""
    from fastapi.testclient import TestClient

    # The context manager runs the startup hooks, which load the session
    # secret: sessions must be opened after it.
    with TestClient(security_app, follow_redirects=False) as anonymous:
        built = {"anonymous": anonymous}
        for role in ROLES:
            client = TestClient(security_app, follow_redirects=False)
            sign_in(client, f"sec_{role}")
            built[role] = client
        yield built


@pytest.fixture
def new_client(security_app, signed_in):
    """Builds extra clients (own cookie jar), closed after the test."""
    from fastapi.testclient import TestClient

    built = []

    def build(**kwargs):
        client = TestClient(security_app, follow_redirects=False, **kwargs)
        built.append(client)
        return client

    yield build
    for client in built:
        client.close()
