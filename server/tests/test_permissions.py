"""Class preference is reversible and never authorizes an unseen write."""

import asyncio
from uuid import uuid4

from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import text

from app.account_auth import issue_access_token, session_key
from app.demo_sessions import create_demo_session, session_engine
from app.main import app


def test_life_scope_preference_still_requires_each_plan_approval():
    ids, tokens = [], []
    demo_session = None
    try:
        with session_engine().begin() as connection:
            for _ in range(2):
                ids.append(connection.execute(text("""
                    INSERT INTO users (email, password_hash, status)
                    VALUES (:email, 'test-only', 'active')
                """), {"email": f"scope-{uuid4().hex}@example.com"}).lastrowid)
        for account_id in ids:
            tokens.append(asyncio.run(issue_access_token(account_id))[0])
        owner, other = ({"Authorization": f"Bearer {token}"} for token in tokens)
        demo_token, demo_session = create_demo_session()
        with TestClient(app) as client:
            first = client.post("/api/v1/account/life/plans", headers=owner, json={
                "intent": "买牛奶", "idempotencyKey": uuid4().hex,
                "items": [{"kind": "task", "title": "买牛奶"}],
            })
            assert first.status_code == 201, first.text
            first_id = first.json()["jobId"]
            choice = client.post(f"/api/v1/account/life/plans/{first_id}/decision", headers=owner,
                                 json={"decision": "allow_scope"})
            assert choice.status_code == 200, choice.text
            assert choice.json()["approval"]["decision"] == "allow_scope"
            assert client.post(f"/api/v1/account/life/plans/{first_id}/decision", headers=owner,
                               json={"decision": "allow_scope"}).status_code == 200
            grants = client.get("/api/v1/account/permissions", headers=owner)
            assert grants.status_code == 200, grants.text
            assert [item["scope"] for item in grants.json()] == ["life.write"]
            assert client.get("/api/v1/account/permissions", headers=other).json() == []

            next_plan = client.post("/api/v1/account/life/plans", headers=owner, json={
                "intent": "联系老师", "idempotencyKey": uuid4().hex,
                "items": [{"kind": "task", "title": "联系老师"}],
            })
            assert next_plan.status_code == 201 and next_plan.json()["status"] == "waiting_approval"
            assert next_plan.json()["approval"]["decision"] == "pending"
            assert [item["title"] for item in client.get("/api/v1/account/life/items", headers=owner).json()["tasks"]] == ["买牛奶"]
            assert client.post(f"/api/v1/account/life/plans/{next_plan.json()['jobId']}/decision",
                               headers=owner, json={"decision": "deny"}).json()["status"] == "cancelled"
            assert client.post("/api/v1/account/permissions/revoke", headers=other,
                               json={"scope": "life.write"}).json() == {"revoked": False}
            assert client.post("/api/v1/account/permissions/revoke", headers=owner,
                               json={"scope": "life.write"}).json() == {"revoked": True}
            assert client.get("/api/v1/account/permissions", headers=owner).json() == []
            assert client.post("/api/v1/account/permissions/revoke", headers=owner,
                               json={"scope": "life.write"}).json() == {"revoked": False}

            demo = {"Authorization": f"Bearer {demo_token}"}
            demo_plan = client.post("/api/v1/demo/life/plans", headers=demo, json={
                "intent": "买牛奶", "idempotencyKey": uuid4().hex,
                "items": [{"kind": "task", "title": "买牛奶"}],
            })
            assert demo_plan.status_code == 201, demo_plan.text
            assert client.post(f"/api/v1/demo/life/plans/{demo_plan.json()['jobId']}/decision",
                               headers=demo, json={"decision": "allow_scope"}).status_code == 422
    finally:
        store = Redis.from_url("redis://127.0.0.1:6379/0")
        for token in tokens:
            store.delete(session_key(token))
        with session_engine().begin() as connection:
            for account_id in ids:
                connection.execute(text("DELETE FROM permission_grants WHERE user_id=:id"), {"id": account_id})
                connection.execute(text("DELETE FROM agent_job_events WHERE user_id=:id"), {"id": account_id})
                connection.execute(text("DELETE FROM approval_requests WHERE user_id=:id"), {"id": account_id})
                connection.execute(text("DELETE FROM agent_jobs WHERE user_id=:id"), {"id": account_id})
                connection.execute(text("DELETE FROM tasks WHERE user_id=:id"), {"id": account_id})
                connection.execute(text("DELETE FROM users WHERE id=:id"), {"id": account_id})
            if demo_session:
                connection.execute(text("DELETE FROM agent_job_events WHERE demo_session_id=:id"), {"id": demo_session.id})
                connection.execute(text("DELETE FROM approval_requests WHERE demo_session_id=:id"), {"id": demo_session.id})
                connection.execute(text("DELETE FROM agent_jobs WHERE demo_session_id=:id"), {"id": demo_session.id})
                connection.execute(text("DELETE FROM demo_sessions WHERE id=:id"), {"id": demo_session.id})
