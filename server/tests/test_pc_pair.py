"""Account-owned one-time PC pairing and revocation."""

import asyncio
from uuid import uuid4

from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import text

from app.account_auth import issue_access_token, session_key
from app.demo_sessions import session_engine
from app.main import app


def test_pair_one_time_heartbeat_revoke_and_owner_boundary():
    ids = []
    tokens = []
    try:
        with session_engine().begin() as connection:
            for _ in range(2):
                ids.append(connection.execute(text("""
                    INSERT INTO users (email, password_hash, status)
                    VALUES (:email, 'test-only', 'active')
                """), {"email": f"pc-pair-{uuid4().hex}@example.com"}).lastrowid)
        for account_id in ids:
            tokens.append(asyncio.run(issue_access_token(account_id))[0])
        a, b = ({"Authorization": f"Bearer {token}"} for token in tokens)
        with TestClient(app) as client:
            issued = client.post("/api/v1/account/pc/pair", headers=a)
            assert issued.status_code == 200, issued.text
            code = issued.json()["code"]
            assert len(code) >= 30
            invalid = client.post("/api/v1/pc/pair", json={"code": "x" * 43})
            assert invalid.status_code == 401
            consumed = client.post("/api/v1/pc/pair", json={"code": code})
            assert consumed.status_code == 200, consumed.text
            assert client.post("/api/v1/pc/pair", json={"code": code}).status_code == 401
            worker = {"Authorization": f"Bearer {consumed.json()['token']}"}
            assert client.post("/api/v1/pc/heartbeat", headers=worker).json()["online"]
            assert len(client.get("/api/v1/account/pc/devices", headers=a).json()) == 1
            assert client.get("/api/v1/account/pc/devices", headers=b).json() == []
            device_id = consumed.json()["deviceId"]
            assert client.post(f"/api/v1/account/pc/devices/{device_id}/revoke", headers=b).status_code == 404
            assert client.post(f"/api/v1/account/pc/devices/{device_id}/revoke", headers=a).json() == {"revoked": True}
            assert client.post("/api/v1/pc/heartbeat", headers=worker).status_code == 401
    finally:
        store = Redis.from_url("redis://127.0.0.1:6379/0")
        for token in tokens:
            store.delete(session_key(token))
        with session_engine().begin() as connection:
            for account_id in ids:
                connection.execute(text("DELETE FROM pc_worker_tokens WHERE user_id=:id"), {"id": account_id})
                connection.execute(text("DELETE FROM pc_pair_requests WHERE user_id=:id"), {"id": account_id})
                connection.execute(text("DELETE FROM devices WHERE user_id=:id"), {"id": account_id})
                connection.execute(text("DELETE FROM users WHERE id=:id"), {"id": account_id})
