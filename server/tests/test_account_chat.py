"""Account and guest histories stay isolated across login sessions."""

import hashlib
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import text

from app.account_auth import session_key
from app.account_history import account_history_key
from app.demo_tokens import token_digest
from app.demo_sessions import session_engine
from app.main import app


def test_account_chat_isolated_from_other_accounts_and_guests(monkeypatch):
    suffix = uuid4().hex
    quota_prefix = f"test:account:quota:{suffix}"
    monkeypatch.setenv("DEMO_QUOTA_PREFIX", quota_prefix)
    monkeypatch.setenv("DEMO_MAX_DAILY_COST_FEN", "20")
    emails = [f"jarvis-chat-{suffix}-{number}@example.com" for number in (1, 2)]
    credentials = [{"email": email, "password": "local-chat-passphrase-2026"} for email in emails]
    account_ids = []
    account_tokens = []
    guest_token = None
    host_digest = hashlib.sha256(b"testclient").hexdigest()
    rate_keys = [f"jarvis:account:rate:{action}:{host_digest}" for action in ("register", "login")]
    store = Redis.from_url("redis://127.0.0.1:6379/0")
    store.delete(*rate_keys)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")
    app.state.deepseek_transport = httpx.MockTransport(
        lambda _: httpx.Response(200, json={"choices": [{"message": {"content": "账号一的回复"}}]})
    )
    try:
        with TestClient(app) as client:
            for credential in credentials:
                registered = client.post("/api/v1/auth/register", json=credential)
                assert registered.status_code == 201
                account_ids.append(registered.json()["id"])
                logged_in = client.post("/api/v1/auth/login", json=credential)
                assert logged_in.status_code == 200
                account_tokens.append(logged_in.json()["token"])
            guest = client.post("/api/v1/demo/session")
            assert guest.status_code == 201
            guest_token = guest.json()["token"]

            first = {"Authorization": f"Bearer {account_tokens[0]}"}
            second = {"Authorization": f"Bearer {account_tokens[1]}"}
            guest_headers = {"Authorization": f"Bearer {guest_token}"}
            sent = client.post("/api/v1/account/chat", json={"message": "账号一的消息"}, headers=first)
            assert sent.status_code == 200
            assert sent.json()["reply"] == "账号一的回复"
            own = client.get("/api/v1/account/chat/history", headers=first)
            assert [item["content"] for item in own.json()["messages"]] == ["账号一的消息", "账号一的回复"]
            budget_denied = client.post("/api/v1/chat", json={"message": "你好"}, headers=guest_headers)
            assert budget_denied.status_code == 429
            assert budget_denied.json()["code"] == "DEMO_DAILY_COST_BUDGET"
            assert client.get("/api/v1/account/chat/history", headers=second).json()["messages"] == []
            assert client.get("/api/v1/chat/history", headers=guest_headers).json()["messages"] == []
            assert client.get("/api/v1/account/chat/history", headers=guest_headers).status_code == 401
            assert client.get("/api/v1/chat/history", headers=first).status_code == 401

            assert client.post("/api/v1/auth/logout", headers=first).status_code == 204
            assert client.get("/api/v1/account/chat/history", headers=first).status_code == 401
            relogin = client.post("/api/v1/auth/login", json=credentials[0])
            assert relogin.status_code == 200
            account_tokens.append(relogin.json()["token"])
            recovered = client.get(
                "/api/v1/account/chat/history",
                headers={"Authorization": f"Bearer {account_tokens[-1]}"},
            )
            assert [item["content"] for item in recovered.json()["messages"]] == ["账号一的消息", "账号一的回复"]
    finally:
        del app.state.deepseek_transport
        keys = rate_keys + [session_key(token) for token in account_tokens]
        keys += [account_history_key(account_id) for account_id in account_ids]
        if guest_token:
            with session_engine().connect() as connection:
                guest_id = connection.scalar(
                    text("SELECT id FROM demo_sessions WHERE session_token_hash = :digest"),
                    {"digest": token_digest(guest_token)},
                )
            if guest_id:
                keys.append(f"jarvis:demo:history:{guest_id}")
        store.delete(*keys)
        for key in store.scan_iter(f"{quota_prefix}:*"):
            store.delete(key)
        with session_engine().begin() as connection:
            for email in emails:
                connection.execute(text("DELETE FROM users WHERE email = :email"), {"email": email})
            if guest_token:
                connection.execute(
                    text("DELETE FROM demo_sessions WHERE session_token_hash = :digest"),
                    {"digest": token_digest(guest_token)},
                )
