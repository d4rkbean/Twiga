"""Open sessions: the table behind the cookie, the block in Mon profil, closing a session,
and the tokens issued before the table existed."""

import re
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend import auth, crud, sessions
from backend.database import SessionLocal
from backend.models import UserSession
from tests.test_lot5c_settings import text_of

MAC_CHROME = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
IPHONE_SAFARI = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.5 Mobile/15E148 Safari/604.1"
)
PASSWORD = "session-password"


@pytest.fixture(autouse=True)
def clean_sessions(demo, clients):
    """Every row a test adds is removed afterwards: the shared clients keep theirs."""
    with SessionLocal() as db:
        before = {row.id for row in db.query(UserSession).all()}
    yield
    with SessionLocal() as db:
        db.query(UserSession).filter(UserSession.id.notin_(before)).delete(synchronize_session=False)
        db.commit()


@pytest.fixture
def account(demo):
    """A throwaway editor account (its password is changed by some tests)."""
    with SessionLocal() as db:
        user = crud.create_user(db, "sessions_user", PASSWORD, "editor")
        user_id = user.id
    yield user_id
    with SessionLocal() as db:
        crud.delete_user(db, user_id)


@pytest.fixture
def device(app):
    """Builds clients, each its own browser (own cookie jar and User-Agent)."""
    built = []

    def build(user_agent: str = MAC_CHROME) -> TestClient:
        client = TestClient(app, follow_redirects=False, headers={"user-agent": user_agent})
        built.append(client)
        return client

    yield build
    for client in built:
        client.close()


def sign_in(client: TestClient, username: str = "sessions_user", password: str = PASSWORD):
    response = client.post("/login", data={"username": username, "password": password})
    assert response.status_code == 200, response.text
    assert auth.SESSION_COOKIE_NAME in client.cookies
    return response


def rows_of(user_id: int) -> list[UserSession]:
    with SessionLocal() as db:
        return db.query(UserSession).filter(UserSession.user_id == user_id).order_by(UserSession.id).all()


def is_signed_in(client: TestClient) -> bool:
    return client.get("/profile").status_code == 200


def session_ids_in(html: str) -> list[int]:
    return [int(value) for value in re.findall(r'name="session_id" value="(\d+)"', html)]


# --- Describing a device ------------------------------------------------------------


def test_the_device_and_the_browser_are_read_from_the_user_agent():
    assert sessions.describe_user_agent(MAC_CHROME) == ("Mac", "Chrome")
    assert sessions.describe_user_agent(IPHONE_SAFARI) == ("iPhone", "Safari")
    assert sessions.describe_user_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 Safari/537.36 Edg/126.0") == ("Windows", "Edge")
    assert sessions.describe_user_agent("Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0") == ("Linux", "Firefox")
    assert sessions.describe_user_agent("Mozilla/5.0 (Linux; Android 14; Pixel 8) Chrome/126.0 Mobile Safari/537.36") == ("Android", "Chrome")
    assert sessions.describe_user_agent("") == ("Appareil inconnu", "Navigateur inconnu")
    assert sessions.describe_user_agent(None) == ("Appareil inconnu", "Navigateur inconnu")


def test_the_last_activity_is_said_in_plain_words():
    now = datetime(2026, 10, 19, 12, 0, 0)
    assert sessions.relative_time(now - timedelta(seconds=20), now) == "à l'instant"
    assert sessions.relative_time(now - timedelta(minutes=5), now) == "il y a 5 min"
    assert sessions.relative_time(now - timedelta(hours=3), now) == "il y a 3 h"
    assert sessions.relative_time(now - timedelta(days=1), now) == "il y a 1 jour"
    assert sessions.relative_time(now - timedelta(days=4), now) == "il y a 4 jours"


# --- The table behind the cookie ----------------------------------------------------


def test_signing_in_records_the_device_and_keeps_only_a_hash(device, account):
    client = device(IPHONE_SAFARI)
    sign_in(client)
    rows = rows_of(account)
    assert len(rows) == 1
    row = rows[0]
    assert row.user_agent == IPHONE_SAFARI and row.revoked_at is None and row.legacy_hash is None
    sid = auth.session_id_of_token(client.cookies.get(auth.SESSION_COOKIE_NAME))
    assert sid and sid not in (row.token_hash or "") and len(row.token_hash) == 64
    assert is_signed_in(client)


def test_a_session_unknown_to_the_table_is_signed_out(device, account):
    client = device()
    sign_in(client)
    with SessionLocal() as db:
        db.query(UserSession).filter(UserSession.user_id == account).delete()
        db.commit()
    assert client.get("/profile").status_code == 303
    assert client.get("/profile").headers["location"] == "/login"


def test_a_closed_session_sends_an_htmx_request_back_to_the_login(device, account):
    client = device()
    sign_in(client)
    with SessionLocal() as db:
        db.query(UserSession).filter(UserSession.user_id == account).delete()
        db.commit()
    response = client.get("/profile", headers={"HX-Request": "true"})
    assert response.headers["HX-Redirect"] == "/login"


def test_the_last_activity_is_written_at_most_once_a_minute(device, account):
    client = device()
    sign_in(client)
    row_id = rows_of(account)[0].id

    def last_seen():
        with SessionLocal() as db:
            return db.get(UserSession, row_id).last_seen_at

    def set_last_seen(value):
        with SessionLocal() as db:
            db.get(UserSession, row_id).last_seen_at = value
            db.commit()

    recent = datetime.utcnow() - timedelta(seconds=20)
    set_last_seen(recent)
    client.get("/profile")
    assert last_seen() == recent  # under a minute: nothing written

    stale = datetime.utcnow() - timedelta(minutes=5)
    set_last_seen(stale)
    client.get("/profile")
    assert last_seen() > stale + timedelta(minutes=4)  # refreshed


def test_expired_sessions_are_refused_and_purged_at_the_next_sign_in(device, account):
    client = device()
    sign_in(client)
    row_id = rows_of(account)[0].id
    with SessionLocal() as db:
        db.get(UserSession, row_id).created_at = datetime.utcnow() - timedelta(days=31)
        db.commit()
    assert client.get("/profile").status_code == 303  # the row is older than its cookie may be

    other = device()
    sign_in(other)  # signing in cleans up
    assert row_id not in {row.id for row in rows_of(account)}


def test_logging_out_closes_this_session_only(device, account):
    laptop, phone = device(MAC_CHROME), device(IPHONE_SAFARI)
    sign_in(laptop)
    sign_in(phone)
    old_cookie = laptop.cookies.get(auth.SESSION_COOKIE_NAME)
    assert len(rows_of(account)) == 2

    response = laptop.post("/logout")
    assert response.headers["HX-Redirect"] == "/login"
    assert len(rows_of(account)) == 1
    assert is_signed_in(phone)

    replay = device(MAC_CHROME)
    replay.cookies.set(auth.SESSION_COOKIE_NAME, old_cookie)
    assert replay.get("/profile").status_code == 303  # the old cookie is dead, not just deleted


# --- Mon profil: the block ----------------------------------------------------------


@pytest.fixture(params=["classic", "other_way"])
def interface(request, monkeypatch, account):
    if request.param == "other_way":
        monkeypatch.setenv("ENABLE_OTHER_WAY", "true")
    with SessionLocal() as db:
        crud.get_user(db, account).ui_variant = request.param
        db.commit()
    return request.param


def test_the_block_lists_the_devices_of_the_account_the_current_one_first(device, account, interface):
    laptop, phone = device(MAC_CHROME), device(IPHONE_SAFARI)
    sign_in(phone)
    sign_in(laptop)
    html = phone.get("/profile").text
    body = text_of(html)

    assert "Sessions ouvertes" in body
    assert body.index("iPhone · Safari") < body.index("Mac · Chrome")  # this device first
    assert "Cet appareil" in body and body.count("Cet appareil") == 1
    assert "active maintenant" in body and "ouverte le" in body
    assert "Fermer les autres sessions" in body
    assert len(session_ids_in(html)) == 1  # a Fermer button for the other one only


def test_the_block_says_when_nothing_else_is_open(device, account, interface):
    client = device()
    sign_in(client)
    body = text_of(client.get("/profile").text)
    assert "Aucune autre session ouverte." in body and "Fermer les autres sessions" not in body


def test_the_page_never_shows_a_readable_session_id(device, account, interface):
    client, other = device(), device(IPHONE_SAFARI)
    sign_in(other)
    sign_in(client)
    html = client.get("/profile").text
    sid = auth.session_id_of_token(client.cookies.get(auth.SESSION_COOKIE_NAME))
    other_sid = auth.session_id_of_token(other.cookies.get(auth.SESSION_COOKIE_NAME))
    hashes = [row.token_hash for row in rows_of(account)]
    assert sid not in html and other_sid not in html and not any(value in html for value in hashes)
    # The close buttons post to fixed addresses: nothing about a session is in an address.
    assert "/profile/sessions/close" in html
    assert not re.search(r"/profile/sessions/[^\"'/ ]*\d", html)


def test_closing_another_session_signs_that_device_out(device, account, interface):
    laptop, phone = device(MAC_CHROME), device(IPHONE_SAFARI)
    sign_in(phone)
    sign_in(laptop)
    (other_id,) = session_ids_in(laptop.get("/profile").text)

    response = laptop.post("/profile/sessions/close", data={"session_id": other_id})
    assert response.status_code == 200 and 'id="profile-sessions"' in response.text
    assert "Session fermée." in text_of(response.text)
    assert "iPhone" not in text_of(response.text)
    assert phone.get("/profile").status_code == 303  # signed out
    assert is_signed_in(laptop)
    assert len(rows_of(account)) == 1


def test_closing_the_other_sessions_keeps_this_one(device, account, interface):
    laptop, phone, tablet = device(MAC_CHROME), device(IPHONE_SAFARI), device(IPHONE_SAFARI.replace("iPhone", "iPad"))
    for client in (phone, tablet, laptop):
        sign_in(client)

    response = laptop.post("/profile/sessions/close-others")
    assert response.status_code == 200 and "Les autres sessions sont fermées." in text_of(response.text)
    assert phone.get("/profile").status_code == 303 and tablet.get("/profile").status_code == 303
    assert is_signed_in(laptop) and len(rows_of(account)) == 1


def test_the_current_session_cannot_be_closed_from_the_list(device, account):
    client = device()
    sign_in(client)
    current = rows_of(account)[0].id
    assert client.post("/profile/sessions/close", data={"session_id": current}).status_code == 400
    assert is_signed_in(client)


def test_a_session_of_another_account_cannot_be_closed(device, account, clients, demo):
    with SessionLocal() as db:
        other = db.query(UserSession).filter(UserSession.user_id == demo["user_viewer"]).first()
        other_id = other.id
    client = device()
    sign_in(client)
    response = client.post("/profile/sessions/close", data={"session_id": other_id})
    assert response.status_code == 404  # answers like a session that does not exist
    with SessionLocal() as db:
        assert db.get(UserSession, other_id) is not None
    assert clients["viewer"].get("/profile").status_code == 200  # the viewer is still in
    assert is_signed_in(client)


def test_an_unknown_session_number_changes_nothing(device, account):
    client = device()
    sign_in(client)
    assert client.post("/profile/sessions/close", data={"session_id": 999999999}).status_code == 404
    assert len(rows_of(account)) == 1


def test_the_close_routes_ask_for_a_signed_in_account(app):
    with TestClient(app, follow_redirects=False) as anonymous:
        assert anonymous.post("/profile/sessions/close", data={"session_id": 1}).status_code == 303
        assert anonymous.post("/profile/sessions/close-others").status_code == 303


def test_every_role_manages_its_own_sessions(clients):
    for role in ("admin", "editor", "viewer"):
        assert clients[role].post("/profile/sessions/close-others").status_code == 200


def test_an_administrator_sees_only_their_own_sessions(clients, device, account):
    other = device()
    sign_in(other)  # another account, with its own session
    html = clients["admin"].get("/profile").text
    assert session_ids_in(html) == []  # the admin has one session: this one
    other_id = rows_of(account)[0].id
    assert clients["admin"].post("/profile/sessions/close", data={"session_id": other_id}).status_code == 404
    assert is_signed_in(other)


def test_without_authentication_there_is_no_block(clients, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", False)
    response = clients["admin"].get("/profile")
    assert response.status_code == 307 and response.headers["location"] == "/settings"
    assert "Sessions ouvertes" not in clients["admin"].get("/settings").text
    assert clients["admin"].post("/profile/sessions/close-others").status_code == 400


# --- Changing the password ----------------------------------------------------------


def test_changing_the_password_closes_the_other_sessions_and_keeps_this_one(device, account):
    laptop, phone = device(MAC_CHROME), device(IPHONE_SAFARI)
    sign_in(laptop)
    sign_in(phone)
    keep = {row.user_agent: row.id for row in rows_of(account)}[MAC_CHROME]

    response = laptop.post(
        "/settings/change-password",
        data={"current_password": PASSWORD, "new_password": "another-password", "confirm_password": "another-password"},
    )
    assert response.status_code == 200
    assert phone.get("/profile").status_code == 303  # the token's fingerprint no longer matches
    assert [row.id for row in rows_of(account)] == [keep]  # and its row is gone
    assert is_signed_in(laptop)  # the new cookie carries the same session


def test_an_administrator_resetting_a_password_closes_every_session_of_that_account(device, account, clients):
    phone = device(IPHONE_SAFARI)
    sign_in(phone)
    clients["admin"].post(f"/users/{account}/password", data={"new_password": "reset-by-admin"})
    assert rows_of(account) == []
    assert phone.get("/profile").status_code == 303


# --- Tokens issued before the table -------------------------------------------------


def legacy_cookie(account_id: int) -> str:
    with SessionLocal() as db:
        return auth.create_session_token(crud.get_user(db, account_id))


def test_a_token_from_before_the_table_is_accepted_then_converted(device, account):
    token = legacy_cookie(account)
    assert auth.session_id_of_token(token) is None  # no session id inside
    assert rows_of(account) == []

    client = device(IPHONE_SAFARI)
    client.cookies.set(auth.SESSION_COOKIE_NAME, token)
    response = client.get("/profile")
    assert response.status_code == 200  # nobody is signed out by the update

    rows = rows_of(account)
    assert len(rows) == 1 and rows[0].legacy_hash and rows[0].user_agent == IPHONE_SAFARI
    new_cookie = response.cookies.get(auth.SESSION_COOKIE_NAME)
    assert new_cookie and auth.session_id_of_token(new_cookie)  # the browser now holds a real session
    assert "iPhone · Safari" in text_of(response.text)

    assert is_signed_in(client)
    assert len(rows_of(account)) == 1  # no second row


def test_the_same_old_token_presented_twice_joins_the_same_session(device, account):
    token = legacy_cookie(account)
    first, second = device(MAC_CHROME), device(MAC_CHROME)
    for client in (first, second):
        client.cookies.set(auth.SESSION_COOKIE_NAME, token)
    assert first.get("/profile").status_code == 200
    assert second.get("/profile").status_code == 200  # the old token still rides the converted row
    assert len(rows_of(account)) == 1


def test_a_converted_session_closed_cannot_be_converted_again(device, account):
    token = legacy_cookie(account)
    client = device(MAC_CHROME)
    client.cookies.set(auth.SESSION_COOKIE_NAME, token)
    client.get("/profile")  # converted
    other = device(IPHONE_SAFARI)
    sign_in(other)
    (converted_id,) = session_ids_in(other.get("/profile").text)

    assert other.post("/profile/sessions/close", data={"session_id": converted_id}).status_code == 200
    assert client.get("/profile").status_code == 303  # the new cookie is dead

    replay = device(MAC_CHROME)
    replay.cookies.set(auth.SESSION_COOKIE_NAME, token)
    assert replay.get("/profile").status_code == 303  # and so is the old one: it was used
    assert "iPhone" in text_of(other.get("/profile").text) and len(session_ids_in(other.get("/profile").text)) == 0


def test_a_legacy_token_still_needs_the_current_password(device, account):
    token = legacy_cookie(account)
    with SessionLocal() as db:
        crud.set_user_password(db, account, "changed-after-the-token")
    client = device()
    client.cookies.set(auth.SESSION_COOKIE_NAME, token)
    assert client.get("/profile").status_code == 303
    assert rows_of(account) == []


def test_a_forged_session_id_is_refused(device, account):
    with SessionLocal() as db:
        forged = auth.create_session_token(crud.get_user(db, account), "not-a-real-session-id")
    client = device()
    client.cookies.set(auth.SESSION_COOKIE_NAME, forged)
    assert client.get("/profile").status_code == 303


def test_a_session_id_does_not_work_for_another_account(device, account, demo):
    client = device()
    sign_in(client)
    sid = auth.session_id_of_token(client.cookies.get(auth.SESSION_COOKIE_NAME))
    with SessionLocal() as db:
        # Signed for another account, carrying this account's session id.
        borrowed = auth.create_session_token(crud.get_user(db, demo["user_admin"]), sid)
    thief = device()
    thief.cookies.set(auth.SESSION_COOKIE_NAME, borrowed)
    assert thief.get("/profile").status_code == 303
