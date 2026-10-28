"""Account isolation and revocation against the dedicated local MySQL and Redis."""

import hashlib
from uuid import uuid4

from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import text

from app.account_auth import session_key
from app.demo_sessions import session_engine
from app.main import app


def clear_testclient_rate_limits():
    host_digest = hashlib.sha256(b"testclient").hexdigest()
    keys = [f"jarvis:account:rate:{action}:{host_digest}" for action in ("register", "login")]
    Redis.from_url("redis://127.0.0.1:6379/0").delete(*keys)


def test_account_registration_login_isolation_and_logout():
    email = f"jarvis-test-{uuid4().hex}@example.com"
    password = "local-test-passphrase-2026"
    token = None
    clear_testclient_rate_limits()
    try:
        with TestClient(app) as client:
            credentials = {"email": email, "password": password}
            registered = client.post("/api/v1/auth/register", json=credentials)
            assert registered.status_code == 201
            account_id = registered.json()["id"]

            with session_engine().connect() as connection:
                stored_hash = connection.scalar(text("SELECT password_hash FROM users WHERE id = :id"), {"id": account_id})
            assert stored_hash.startswith("$argon2id$")
            assert password not in stored_hash

            duplicate = client.post("/api/v1/auth/register", json=credentials)
            assert duplicate.status_code == 409
            wrong = client.post("/api/v1/auth/login", json={**credentials, "password": "wrong-password-2026"})
            assert wrong.status_code == 401

            logged_in = client.post("/api/v1/auth/login", json=credentials)
            assert logged_in.status_code == 200
            token = logged_in.json()["token"]
            assert logged_in.json()["mode"] == "account"
            headers = {"Authorization": f"Bearer {token}"}
            assert client.get("/api/v1/auth/me", headers=headers).json()["id"] == account_id
            assert client.get("/api/v1/chat/history", headers=headers).status_code == 401
            assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
            assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    finally:
        clear_testclient_rate_limits()
        if token:
            Redis.from_url("redis://127.0.0.1:6379/0").delete(session_key(token))
        with session_engine().begin() as connection:
            connection.execute(text("DELETE FROM users WHERE email = :email"), {"email": email})


def test_account_rejects_missing_or_forged_token():
    with TestClient(app) as client:
        assert client.get("/api/v1/auth/me").status_code == 401
        forged = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + "a" * 43})
    assert forged.status_code == 401
    assert forged.json()["code"] == "ACCOUNT_SESSION_EXPIRED"
