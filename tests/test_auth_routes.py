import jwt
import pytest
from fastapi.testclient import TestClient

from apps.api import main
from apps.api.auth import hash_password
from apps.api.users_db import EmailAlreadyRegistered


@pytest.fixture
def client():
    return TestClient(main.app)


def test_signup_sets_httponly_session_cookie(client, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        main,
        "create_user",
        lambda email, password_hash: captured.update(email=email, password_hash=password_hash) or "new-user-id",
    )

    res = client.post("/auth/signup", json={"email": "Test@Example.com", "password": "correcthorse"})

    assert res.status_code == 200
    assert captured["email"] == "test@example.com"  # normalized to lowercase
    assert captured["password_hash"] != "correcthorse"  # never stored in plaintext

    set_cookie = res.headers.get("set-cookie", "")
    assert "studymate_token=" in set_cookie
    assert "HttpOnly" in set_cookie  # not readable from JS - the whole point

    token = res.cookies["studymate_token"]
    payload = jwt.decode(token, "test-jwt-secret", algorithms=["HS256"], audience="authenticated")
    assert payload["sub"] == "new-user-id"


def test_signup_rejects_short_password(client, monkeypatch):
    monkeypatch.setattr(main, "create_user", lambda email, password_hash: "should-not-be-called")

    res = client.post("/auth/signup", json={"email": "test@example.com", "password": "short"})

    assert res.status_code == 400


def test_signup_rejects_duplicate_email(client, monkeypatch):
    def raise_duplicate(email, password_hash):
        raise EmailAlreadyRegistered(email)

    monkeypatch.setattr(main, "create_user", raise_duplicate)

    res = client.post("/auth/signup", json={"email": "test@example.com", "password": "correcthorse"})

    assert res.status_code == 409


def test_login_with_correct_password_sets_session_cookie(client, monkeypatch):
    stored_hash = hash_password("correcthorse")
    monkeypatch.setattr(
        main, "get_user_by_email", lambda email: {"id": "existing-user-id", "email": email, "password_hash": stored_hash}
    )

    res = client.post("/auth/login", json={"email": "test@example.com", "password": "correcthorse"})

    assert res.status_code == 200
    payload = jwt.decode(res.cookies["studymate_token"], "test-jwt-secret", algorithms=["HS256"], audience="authenticated")
    assert payload["sub"] == "existing-user-id"


def test_login_with_wrong_password_is_rejected(client, monkeypatch):
    stored_hash = hash_password("correcthorse")
    monkeypatch.setattr(
        main, "get_user_by_email", lambda email: {"id": "existing-user-id", "email": email, "password_hash": stored_hash}
    )

    res = client.post("/auth/login", json={"email": "test@example.com", "password": "wrong-password"})

    assert res.status_code == 401


def test_login_with_unknown_email_is_rejected(client, monkeypatch):
    monkeypatch.setattr(main, "get_user_by_email", lambda email: None)

    res = client.post("/auth/login", json={"email": "nobody@example.com", "password": "correcthorse"})

    assert res.status_code == 401


def test_login_does_not_require_existing_session(monkeypatch):
    monkeypatch.setattr(main, "get_user_by_email", lambda email: None)
    unauthenticated_client = TestClient(main.app)

    res = unauthenticated_client.post("/auth/login", json={"email": "x@example.com", "password": "whatever1"})

    # Reaches real login logic (bad credentials), not blocked by the cookie-auth dependency.
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid email or password"


def test_me_route_reflects_session_cookie(monkeypatch):
    token = jwt.encode({"sub": "user-123", "aud": "authenticated"}, "test-jwt-secret", algorithm="HS256")
    client = TestClient(main.app, cookies={"studymate_token": token})

    res = client.get("/auth/me")

    assert res.status_code == 200
    assert res.json() == {"user_id": "user-123"}


def test_me_route_requires_session():
    client = TestClient(main.app)

    res = client.get("/auth/me")

    assert res.status_code == 401


def test_reset_password_updates_hash_for_known_email(client, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        main,
        "update_password",
        lambda email, password_hash: captured.update(email=email, password_hash=password_hash) or True,
    )

    res = client.post(
        "/auth/reset-password",
        json={"email": "Test@Example.com", "new_password": "newpassword1", "confirm_password": "newpassword1"},
    )

    assert res.status_code == 200
    assert captured["email"] == "test@example.com"  # normalized to lowercase
    assert captured["password_hash"] != "newpassword1"  # never stored in plaintext


def test_reset_password_rejects_mismatched_confirmation(client, monkeypatch):
    monkeypatch.setattr(main, "update_password", lambda email, password_hash: True)

    res = client.post(
        "/auth/reset-password",
        json={"email": "test@example.com", "new_password": "newpassword1", "confirm_password": "different1"},
    )

    assert res.status_code == 400


def test_reset_password_rejects_short_password(client, monkeypatch):
    monkeypatch.setattr(main, "update_password", lambda email, password_hash: True)

    res = client.post(
        "/auth/reset-password",
        json={"email": "test@example.com", "new_password": "short", "confirm_password": "short"},
    )

    assert res.status_code == 400


def test_reset_password_with_unknown_email_returns_404(client, monkeypatch):
    monkeypatch.setattr(main, "update_password", lambda email, password_hash: False)

    res = client.post(
        "/auth/reset-password",
        json={"email": "nobody@example.com", "new_password": "newpassword1", "confirm_password": "newpassword1"},
    )

    assert res.status_code == 404


def test_reset_password_does_not_require_existing_session(monkeypatch):
    monkeypatch.setattr(main, "update_password", lambda email, password_hash: True)
    unauthenticated_client = TestClient(main.app)

    res = unauthenticated_client.post(
        "/auth/reset-password",
        json={"email": "x@example.com", "new_password": "newpassword1", "confirm_password": "newpassword1"},
    )

    assert res.status_code == 200


def test_logout_clears_session_cookie():
    token = jwt.encode({"sub": "user-123", "aud": "authenticated"}, "test-jwt-secret", algorithm="HS256")
    client = TestClient(main.app, cookies={"studymate_token": token})

    res = client.post("/auth/logout")

    assert res.status_code == 200
    set_cookie = res.headers.get("set-cookie", "")
    assert "studymate_token=" in set_cookie
    # Cleared cookies are expired immediately (Max-Age=0), not just emptied.
    assert "Max-Age=0" in set_cookie
