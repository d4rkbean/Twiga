"""Display preferences: interface variant, theme and density.

Stored on the account, mirrored in a cookie (twiga_ui, twiga_theme,
twiga_density), resolved account -> cookie -> default exactly like the
language, and rendered by the server on <html>.
"""

import re
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend import auth, preferences

PREFERENCE_COLUMNS = ("ui_variant", "theme", "density")


def html_tag(response) -> str:
    return re.search(r"<html[^>]*>", response.text).group(0)


@pytest.fixture
def make_client(app, demo):
    """A fresh client (own cookie jar) logged in as the demo user of a role.
    The account's display preferences are put back to the defaults afterwards,
    so the other tests never see them."""
    from backend import crud
    from backend.database import SessionLocal

    created = []

    def build(role: str) -> TestClient:
        with SessionLocal() as db:
            token = auth.open_session(db, crud.get_user(db, demo[f"user_{role}"]), "pytest")
        client = TestClient(app, follow_redirects=False)
        client.cookies.set(auth.SESSION_COOKIE_NAME, token)
        created.append(role)
        return client

    yield build

    with SessionLocal() as db:
        for role in set(created):
            user = crud.get_user(db, demo[f"user_{role}"])
            user.ui_variant, user.theme, user.density = "classic", "system", "normal"
        db.commit()


def account_preferences(demo, role: str) -> tuple[str, str, str]:
    from backend.database import SessionLocal
    from backend.models import User

    with SessionLocal() as db:
        user = db.get(User, demo[f"user_{role}"])
        return user.ui_variant, user.theme, user.density


# --- Migration ------------------------------------------------------------


def test_migration_adds_the_columns_with_their_defaults(demo):
    from backend.database import engine

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT column_name, column_default, is_nullable FROM information_schema.columns "
                "WHERE table_name = 'users' AND column_name IN ('ui_variant', 'theme', 'density')"
            )
        ).all()
    columns = {name: (default, nullable) for name, default, nullable in rows}

    assert set(columns) == {"ui_variant", "theme", "density"}
    assert "classic" in columns["ui_variant"][0]
    assert "system" in columns["theme"][0]
    assert "normal" in columns["density"][0]
    assert all(nullable == "NO" for _, nullable in columns.values())


def test_migration_goes_down_and_up_again(demo, clients):
    from alembic import command
    from alembic.config import Config

    from backend.database import SessionLocal, engine
    from backend.models import UserSession
    from tests.conftest import ROOT

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend" / "alembic"))

    def user_columns() -> set[str]:
        with engine.connect() as connection:
            return {
                row[0]
                for row in connection.execute(
                    text("SELECT column_name FROM information_schema.columns WHERE table_name = 'users'")
                )
            }

    # Going down drops the table of sessions: the rows of the shared clients are put
    # back afterwards, or every later test would find its client signed out.
    with SessionLocal() as db:
        kept = [
            {column.name: getattr(row, column.name) for column in UserSession.__table__.columns}
            for row in db.query(UserSession).all()
        ]
    engine.dispose()
    try:
        command.downgrade(config, "c4e8a2b9f173")
        assert not set(PREFERENCE_COLUMNS) & user_columns()
        assert {"language", "number_format"} <= user_columns()
    finally:
        engine.dispose()
        command.upgrade(config, "head")
        with SessionLocal() as db:
            db.add_all(UserSession(**values) for values in kept)
            db.commit()
            db.execute(text("SELECT setval(pg_get_serial_sequence('user_sessions', 'id'), (SELECT COALESCE(MAX(id), 1) FROM user_sessions))"))
            db.commit()
    assert set(PREFERENCE_COLUMNS) <= user_columns()


# --- Resolution -------------------------------------------------------------


def test_the_account_wins_over_the_cookie():
    user = SimpleNamespace(ui_variant="classic", theme="dark", density="compact")
    cookies = {"twiga_theme": "light", "twiga_density": "comfortable"}

    assert preferences.resolve(user, cookies) == ("classic", "dark", "compact")


def test_the_cookie_wins_over_the_default_without_an_account():
    cookies = {"twiga_theme": "dark", "twiga_density": "comfortable", "twiga_ui": "classic"}

    assert preferences.resolve(None, cookies) == ("classic", "dark", "comfortable")


def test_the_defaults_apply_without_account_or_cookie():
    assert preferences.resolve(None, {}) == ("classic", "system", "normal")


def test_an_unknown_value_falls_through_to_the_next_source():
    user = SimpleNamespace(ui_variant="x", theme="purple", density="")

    assert preferences.resolve(user, {"twiga_theme": "light", "twiga_density": "huge"}) == (
        "classic",
        "light",
        "normal",
    )


def test_the_other_way_falls_back_to_classic_until_it_is_enabled(monkeypatch):
    user = SimpleNamespace(ui_variant="other_way", theme="system", density="normal")

    monkeypatch.delenv("ENABLE_OTHER_WAY", raising=False)
    assert preferences.resolve(user, {})[0] == "classic"
    monkeypatch.setenv("ENABLE_OTHER_WAY", "true")
    assert preferences.resolve(user, {})[0] == "other_way"


# --- Rendering ---------------------------------------------------------------


def test_html_carries_the_default_theme_and_density(make_client):
    response = make_client("viewer").get("/dashboard")

    tag = html_tag(response)
    assert 'data-theme="system"' in tag
    assert 'data-density="normal"' in tag
    assert 'data-ui="classic"' in tag
    assert "class=" not in tag  # neither .dark nor anything else


@pytest.mark.parametrize("theme, dark", [("dark", True), ("light", False), ("system", False)])
def test_html_class_follows_the_account_theme(make_client, theme, dark):
    client = make_client("editor")
    assert client.post("/profile/preferences", data={"theme": theme}).status_code == 200

    tag = html_tag(client.get("/dashboard"))

    assert f'data-theme="{theme}"' in tag
    assert ('class="dark"' in tag) is dark


@pytest.mark.parametrize("density", ["compact", "normal", "comfortable"])
def test_html_data_density_follows_the_account(make_client, density):
    client = make_client("editor")
    client.post("/profile/preferences", data={"density": density})

    assert f'data-density="{density}"' in html_tag(client.get("/transactions/list"))


def test_the_account_beats_a_stale_cookie_on_the_page(make_client):
    client = make_client("editor")
    client.post("/profile/preferences", data={"theme": "dark"})
    client.cookies.set("twiga_theme", "light")

    assert 'class="dark"' in html_tag(client.get("/dashboard"))


def test_every_main_screen_renders_the_density_variables(make_client):
    client = make_client("admin")
    client.post("/profile/preferences", data={"density": "compact", "theme": "dark"})

    for path in ("/transactions/list", "/transactions/inbox", "/dashboard", "/settings", "/profile"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert 'data-density="compact"' in html_tag(response), path
        assert 'class="dark"' in html_tag(response), path


# --- The preferences route ---------------------------------------------------


def test_saving_writes_the_account_and_the_cookies(make_client, demo):
    client = make_client("viewer")

    response = client.post(
        "/profile/preferences",
        data={"ui_variant": "classic", "theme": "dark", "density": "comfortable"},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert "HX-Refresh" not in response.headers  # no reload for a display change
    assert 'role="status"' in response.text
    assert account_preferences(demo, "viewer") == ("classic", "dark", "comfortable")
    cookies = response.headers.get_list("set-cookie")
    assert any(c.startswith("twiga_theme=dark") for c in cookies)
    assert any(c.startswith("twiga_density=comfortable") for c in cookies)
    assert any(c.startswith("twiga_ui=classic") for c in cookies)


def test_a_partial_post_only_touches_what_it_sends(make_client, demo):
    client = make_client("editor")
    client.post("/profile/preferences", data={"theme": "dark", "density": "compact"})

    client.post("/profile/preferences", data={"density": "comfortable"})

    assert account_preferences(demo, "editor") == ("classic", "dark", "comfortable")


def test_language_still_reloads_the_page(make_client):
    client = make_client("viewer")

    response = client.post("/profile/preferences", data={"language": "en", "number_format": "en-GB"})

    assert response.status_code == 200
    assert response.headers["HX-Refresh"] == "true"
    client.post("/profile/preferences", data={"language": "fr", "number_format": "fr"})


@pytest.mark.parametrize(
    "data",
    [
        {"theme": "purple"},
        {"density": "huge"},
        {"ui_variant": "third_way"},
        {"ui_variant": "other_way"},  # not enabled by default
        {"language": "xx"},
        {"number_format": "xx"},
        {"theme": "dark", "density": "huge"},
        {},
    ],
)
def test_values_outside_the_lists_are_refused(make_client, demo, data):
    client = make_client("editor")

    response = client.post("/profile/preferences", data=data)

    assert response.status_code == 400
    assert account_preferences(demo, "editor") == ("classic", "system", "normal")  # nothing written
    assert not response.headers.get_list("set-cookie")


def test_the_other_way_is_accepted_once_enabled(make_client, demo, monkeypatch):
    monkeypatch.setenv("ENABLE_OTHER_WAY", "true")
    client = make_client("editor")

    response = client.post("/profile/preferences", data={"ui_variant": "other_way"})

    assert response.status_code == 200
    assert account_preferences(demo, "editor")[0] == "other_way"
    assert 'data-ui="other_way"' in html_tag(client.get("/dashboard"))


def test_a_user_cannot_change_another_users_preferences(make_client, demo):
    admin = make_client("admin")
    viewer = make_client("viewer")

    # The route takes no user id: whatever a client sends, it only ever writes
    # to the account behind its own session.
    admin.post("/profile/preferences", data={"theme": "dark", "density": "compact", "user_id": demo["user_viewer"]})

    assert account_preferences(demo, "admin") == ("classic", "dark", "compact")
    assert account_preferences(demo, "viewer") == ("classic", "system", "normal")
    assert 'data-theme="system"' in html_tag(viewer.get("/dashboard"))


def test_the_route_needs_a_session_when_authentication_is_on(app):
    with TestClient(app, follow_redirects=False) as anonymous:
        response = anonymous.post("/profile/preferences", data={"theme": "dark"})

    assert response.status_code in (303, 401)


def test_the_login_page_follows_the_cookie(app):
    with TestClient(app, follow_redirects=False) as anonymous:
        anonymous.cookies.set("twiga_theme", "dark")
        anonymous.cookies.set("twiga_density", "compact")

        tag = html_tag(anonymous.get("/login"))

    assert 'class="dark"' in tag
    assert 'data-density="compact"' in tag


def test_without_authentication_the_cookie_alone_decides(app, demo, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", False)
    with TestClient(app, follow_redirects=False) as client:
        response = client.post("/profile/preferences", data={"theme": "dark", "density": "comfortable"})
        assert response.status_code == 200
        assert any(c.startswith("twiga_theme=dark") for c in response.headers.get_list("set-cookie"))

        tag = html_tag(client.get("/dashboard"))

    assert 'class="dark"' in tag
    assert 'data-density="comfortable"' in tag
    # No account was involved: the demo accounts are untouched.
    for role in ("admin", "editor", "viewer"):
        assert account_preferences(demo, role) == ("classic", "system", "normal")


# --- Screens -----------------------------------------------------------------


def test_the_profile_has_a_display_card(make_client):
    client = make_client("viewer")
    client.post("/profile/preferences", data={"theme": "light", "density": "comfortable"})

    page = client.get("/profile").text

    assert "Affichage" in page
    for name in ("ui_variant", "theme", "density"):
        assert f'name="{name}"' in page
    assert 'value="comfortable"' in page
    assert "pref-preview" in page
    assert "privacyOnOpen" in page


def test_the_other_way_is_offered_disabled_with_a_soon_label(make_client, monkeypatch):
    monkeypatch.delenv("ENABLE_OTHER_WAY", raising=False)
    page = make_client("viewer").get("/profile").text

    other_way = re.search(r'<input[^>]*value="other_way"[^>]*>', page, re.S).group(0)
    assert "disabled" in other_way
    assert "Bientôt" in page


def test_settings_preferences_reuse_the_same_partial(make_client):
    page = make_client("admin").get("/settings").text

    assert 'name="language"' in page  # language and format are still there
    assert 'name="number_format"' in page
    for name in ("ui_variant", "theme", "density"):
        assert f'name="{name}"' in page
    assert page.count("pref-preview-card") >= 2


def test_the_design_system_page_shows_the_three_densities(make_client):
    page = make_client("admin").get("/design-system").text

    for density in ("compact", "normal", "comfortable"):
        assert f'data-density="{density}"' in page


def test_touch_targets_never_shrink_below_50px_in_the_stylesheet():
    from pathlib import Path

    css = (Path(__file__).resolve().parent.parent / "frontend/static/css/design-system.css").read_text()
    for match in re.finditer(r"--row-(touch|list):\s*(\d+)px", css):
        assert int(match.group(2)) >= 50, match.group(0)
    assert "min-height: 50px" in css  # .btn, .input-base, .choice-card
