"""Only explicitly confirmed, current memories reach planning reads."""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import text

from app.account_auth import issue_access_token, session_key
from app.demo_sessions import session_engine
from app.main import app
from app.memory_store import planning_memories


def test_memory_consent_edit_expiry_revoke_and_isolation():
    ids = []
    tokens = []
    try:
        with session_engine().begin() as connection:
            for _ in range(2):
                ids.append(connection.execute(text("""
                    INSERT INTO users (email, password_hash, status)
                    VALUES (:email, 'test-only', 'active')
                """), {"email": f"memory-{uuid4().hex}@example.com"}).lastrowid)
        for account_id in ids:
            tokens.append(asyncio.run(issue_access_token(account_id))[0])
        a, b = ({"Authorization": f"Bearer {token}"} for token in tokens)
        future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        with TestClient(app) as client:
            created = client.post("/api/v1/account/memory/candidates", headers=a, json={
                "summary": "喜欢早晨运动", "evidenceRef": "user_explicit:test", "purpose": "planning", "expiresAt": future,
            })
            assert created.status_code == 201, created.text
            candidate_id = created.json()["id"]
            assert created.json()["status"] == "candidate"
            assert planning_memories(ids[0]) == []
            assert client.get("/api/v1/account/memory/candidates", headers=b).json() == []
            assert client.post(f"/api/v1/account/memory/candidates/{candidate_id}/decision", headers=b,
                               json={"decision": "confirm"}).status_code == 404
            changed = client.put(f"/api/v1/account/memory/candidates/{candidate_id}", headers=a,
                                 json={"summary": "喜欢傍晚运动", "purpose": "planning", "expiresAt": future})
            assert changed.status_code == 200, changed.text
            confirmed = client.post(f"/api/v1/account/memory/candidates/{candidate_id}/decision", headers=a,
                                    json={"decision": "confirm"})
            assert confirmed.json()["status"] == "confirmed"
            again = client.post(f"/api/v1/account/memory/candidates/{candidate_id}/decision", headers=a,
                                json={"decision": "confirm"})
            assert again.json()["memoryId"] == confirmed.json()["memoryId"]
            assert planning_memories(ids[0]) == ["喜欢傍晚运动"]
            assert planning_memories(ids[1]) == []
            with session_engine().begin() as connection:
                connection.execute(text("UPDATE memory_candidates SET expires_at=UTC_TIMESTAMP(3) - INTERVAL 1 SECOND WHERE id=:id"), {"id": candidate_id})
            assert planning_memories(ids[0]) == []
            with session_engine().begin() as connection:
                connection.execute(text("UPDATE memory_candidates SET expires_at=UTC_TIMESTAMP(3) + INTERVAL 2 DAY WHERE id=:id"), {"id": candidate_id})
            assert planning_memories(ids[0]) == ["喜欢傍晚运动"]
            assert client.post(f"/api/v1/account/memory/candidates/{candidate_id}/revoke", headers=a).json() == {"revoked": True}
            assert planning_memories(ids[0]) == []
            assert client.post(f"/api/v1/account/memory/candidates/{candidate_id}/revoke", headers=a).json() == {"revoked": False}
            denied = client.post("/api/v1/account/memory/candidates", headers=a, json={
                "summary": "未采用", "evidenceRef": "user_explicit:test", "purpose": "planning", "expiresAt": future,
            }).json()["id"]
            assert client.post(f"/api/v1/account/memory/candidates/{denied}/decision", headers=a,
                               json={"decision": "reject"}).json()["status"] == "rejected"
            assert planning_memories(ids[0]) == []
            reminder = client.post("/api/v1/account/memory/candidates", headers=a, json={
                "summary": "每天提醒喝水", "evidenceRef": "user_explicit:test", "purpose": "planning", "expiresAt": future,
            }).json()["id"]
            client.post(f"/api/v1/account/memory/candidates/{reminder}/decision", headers=a,
                        json={"decision": "confirm"})
            planned = client.post("/api/v1/account/life/plans", headers=a,
                                  json={"intent": "帮我安排今天并提醒买牛奶", "idempotencyKey": uuid4().hex})
            assert planned.status_code == 201, planned.text
            assert {item["title"] for item in planned.json()["items"]} == {"买牛奶", "喝水"}
            assert planned.json()["memoryUsed"] == ["每天提醒喝水"]
            client.post(f"/api/v1/account/memory/candidates/{reminder}/revoke", headers=a)
            after_revoke = client.post("/api/v1/account/life/plans", headers=a,
                                       json={"intent": "帮我安排今天并提醒买牛奶", "idempotencyKey": uuid4().hex})
            assert [item["title"] for item in after_revoke.json()["items"]] == ["买牛奶"]
            assert client.delete(f"/api/v1/account/memory/candidates/{reminder}", headers=b).status_code == 404
            deleted = client.delete(f"/api/v1/account/memory/candidates/{reminder}", headers=a)
            assert deleted.status_code == 200 and deleted.json() == {"deleted": True}
            assert all(item["id"] != reminder for item in client.get("/api/v1/account/memory/candidates", headers=a).json())
            assert planning_memories(ids[0]) == []
            assert client.delete(f"/api/v1/account/memory/candidates/{reminder}", headers=a).status_code == 404
    finally:
        store = Redis.from_url("redis://127.0.0.1:6379/0")
        for token in tokens:
            store.delete(session_key(token))
        with session_engine().begin() as connection:
            for account_id in ids:
                connection.execute(text("DELETE FROM agent_job_events WHERE user_id=:id"), {"id": account_id})
                connection.execute(text("DELETE FROM approval_requests WHERE user_id=:id"), {"id": account_id})
                connection.execute(text("DELETE FROM agent_jobs WHERE user_id=:id"), {"id": account_id})
                connection.execute(text("DELETE FROM memories WHERE user_id=:id"), {"id": account_id})
                connection.execute(text("DELETE FROM memory_candidates WHERE user_id=:id"), {"id": account_id})
                connection.execute(text("DELETE FROM users WHERE id=:id"), {"id": account_id})
