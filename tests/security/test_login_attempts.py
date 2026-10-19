"""Failed sign-ins: per address and username, per username from every address,
bounded memory, X-Forwarded-For believed only from TRUSTED_PROXIES."""

import pytest

from backend.routers import auth as auth_router


def _fail(client, username="sec_viewer", forwarded_for=None):
    headers = {"X-Forwarded-For": forwarded_for} if forwarded_for else {}
    return client.post("/login", data={"username": username, "password": "wrong"}, headers=headers)


@pytest.fixture(autouse=True)
def clear_username_counter():
    yield
    auth_router._failed_by_username.clear()


def test_five_failures_from_one_address_lock_that_address_out(new_client):
    client = new_client()
    for _ in range(5):
        assert _fail(client).status_code == 401

    assert _fail(client).status_code == 429


def test_twenty_failures_from_many_addresses_lock_the_username_out(new_client, monkeypatch):
    monkeypatch.setattr(auth_router, "TRUSTED_PROXIES", {"testclient"})
    client = new_client()
    for index in range(20):
        assert _fail(client, forwarded_for=f"203.0.113.{index}").status_code == 401

    assert _fail(client, forwarded_for="198.51.100.7").status_code == 429
    assert _fail(client, username="sec_editor", forwarded_for="198.51.100.7").status_code == 401


def test_x_forwarded_for_is_ignored_without_a_trusted_proxy(new_client):
    client = new_client()
    for index in range(5):
        assert _fail(client, forwarded_for=f"203.0.113.{index}").status_code == 401

    assert _fail(client, forwarded_for="198.51.100.7").status_code == 429


def test_the_client_address_is_read_behind_a_trusted_proxy(monkeypatch):
    class FakeRequest:
        def __init__(self, direct, forwarded):
            self.client = type("Client", (), {"host": direct})()
            self.headers = {"x-forwarded-for": forwarded} if forwarded else {}

    monkeypatch.setattr(auth_router, "TRUSTED_PROXIES", {"10.0.0.2"})

    assert auth_router._client_ip(FakeRequest("10.0.0.2", "1.1.1.1, 203.0.113.9")) == "203.0.113.9"
    assert auth_router._client_ip(FakeRequest("10.0.0.2", "203.0.113.9, 10.0.0.2")) == "203.0.113.9"
    assert auth_router._client_ip(FakeRequest("192.0.2.1", "203.0.113.9")) == "192.0.2.1"


def test_looking_an_address_up_does_not_keep_anything():
    assert auth_router._is_locked_out(("192.0.2.1", "nobody")) is False
    assert auth_router._failed_attempts == {}
    assert auth_router._failed_by_username == {}


def test_the_memory_is_bounded_and_expired_entries_are_dropped(monkeypatch):
    monkeypatch.setattr(auth_router, "_MAX_TRACKED", 3)
    store = {}
    auth_router._add(store, "old", 0.0)
    auth_router._add(store, "a", 1000.0)
    auth_router._add(store, "b", 1001.0)

    auth_router._add(store, "c", 1000.0 + auth_router._LOCKOUT_SECONDS - 1)  # "old" has expired
    assert set(store) == {"a", "b", "c"}

    auth_router._add(store, "d", 1002.0)  # nothing expired: the oldest goes
    assert set(store) == {"b", "c", "d"}
