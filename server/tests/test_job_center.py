"""Persisted job status and owner-bound cancellation."""

import asyncio
from uuid import uuid4

from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import text

from app.account_auth import issue_access_token, session_key
from app.demo_sessions import session_engine
from app.main import app


def test_job_status_events_cancel_and_cross_account_isolation():
    ids = []
    tokens = []
    try:
        with session_engine().begin() as connection:
            for _ in range(2):
                ids.append(connection.execute(text("""
                    INSERT INTO users (email, password_hash, status)
                    VALUES (:email, 'test-only', 'active')
                """), {"email": f"job-{uuid4().hex}@example.com"}).lastrowid)
        for account_id in ids:
            tokens.append(asyncio.run(issue_access_token(account_id))[0])
        a, b = ({"Authorization": f"Bearer {token}"} for token in tokens)
        with TestClient(app) as client:
            created = client.post("/api/v1/account/life/plans", headers=a,
                                  json={"intent": "提醒买牛奶", "idempotencyKey": uuid4().hex})
            assert created.status_code == 201, created.text
            job_id = created.json()["jobId"]
            assert client.get("/api/v1/account/life/jobs", headers=b).json() == []
            assert client.get(f"/api/v1/account/life/jobs/{job_id}/events", headers=b).status_code == 404
            assert client.post(f"/api/v1/account/life/jobs/{job_id}/cancel", headers=b).status_code == 404
            before = client.get("/api/v1/account/life/jobs", headers=a).json()
            assert before[0]["status"] == "waiting_approval"
            assert before[0]["latestEvent"]
            cancelled = client.post(f"/api/v1/account/life/jobs/{job_id}/cancel", headers=a)
            assert cancelled.status_code == 200, cancelled.text
            assert cancelled.json() == {"cancelled": True}
            assert client.post(f"/api/v1/account/life/jobs/{job_id}/cancel", headers=a).json() == {"cancelled": False}
            assert client.get(f"/api/v1/account/life/jobs/{job_id}/events", headers=a).json()[-1]["type"] == "cancelled_by_user"
            assert client.get(f"/api/v1/account/life/plans/{job_id}", headers=a).json()["status"] == "cancelled"
            assert client.get("/api/v1/account/life/items", headers=a).json() == {"tasks": [], "schedules": []}
    finally:
        store = Redis.from_url("redis://127.0.0.1:6379/0")
        for token in tokens:
            store.delete(session_key(token))
        with session_engine().begin() as connection:
            for account_id in ids:
                connection.execute(text("DELETE FROM agent_job_events WHERE user_id=:id"), {"id": account_id})
                connection.execute(text("DELETE FROM approval_requests WHERE user_id=:id"), {"id": account_id})
                connection.execute(text("DELETE FROM agent_jobs WHERE user_id=:id"), {"id": account_id})
                connection.execute(text("DELETE FROM users WHERE id=:id"), {"id": account_id})
