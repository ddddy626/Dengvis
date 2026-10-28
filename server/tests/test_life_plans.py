"""The approval decision, not model text, controls durable life-task writes."""

import asyncio
from uuid import uuid4

from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import text

from app.account_auth import issue_access_token, session_key
from app.demo_sessions import session_engine
from app.main import app


def test_account_plan_edit_approval_idempotency_and_denial():
    token_a = token_b = None
    email_a = f"life-a-{uuid4().hex}@example.com"
    email_b = f"life-b-{uuid4().hex}@example.com"
    account_ids = []
    try:
        with session_engine().begin() as connection:
            for email in (email_a, email_b):
                account_ids.append(connection.execute(text("""
                    INSERT INTO users (email, password_hash, status) VALUES (:email, 'test-only', 'active')
                """), {"email": email}).lastrowid)
        token_a, _ = asyncio.run(issue_access_token(account_ids[0]))
        token_b, _ = asyncio.run(issue_access_token(account_ids[1]))
        a = {"Authorization": f"Bearer {token_a}"}
        b = {"Authorization": f"Bearer {token_b}"}
        with TestClient(app) as client:
            body = {"intent": "帮我安排今天并提醒买牛奶", "idempotencyKey": uuid4().hex}
            created = client.post("/api/v1/account/life/plans", headers=a, json=body)
            assert created.status_code == 201, created.text
            job_id = created.json()["jobId"]
            assert created.json()["items"][0]["title"] == "买牛奶"
            assert created.json()["status"] == "waiting_approval"
            duplicate = client.post("/api/v1/account/life/plans", headers=a, json=body)
            assert duplicate.json()["jobId"] == job_id
            conflict = client.post("/api/v1/account/life/plans", headers=a, json={**body, "intent": "其他事项"})
            assert conflict.status_code == 409
            assert client.get(f"/api/v1/account/life/plans/{job_id}", headers=b).status_code == 404
            assert client.get("/api/v1/account/life/items", headers=b).json() == {"tasks": [], "schedules": []}

            edited = client.put(f"/api/v1/account/life/plans/{job_id}", headers=a, json={"items": [
                {"kind": "task", "title": "买牛奶"},
                {"kind": "schedule", "title": "复习", "startsAt": "2026-10-17T09:00:00+08:00", "endsAt": "2026-10-17T10:00:00+08:00"},
            ]})
            assert edited.status_code == 200, edited.text
            assert len(edited.json()["items"]) == 2
            approved = client.post(f"/api/v1/account/life/plans/{job_id}/decision", headers=a, json={"decision": "allow_once"})
            assert approved.status_code == 200, approved.text
            assert approved.json()["status"] == "succeeded"
            assert len(approved.json()["saved"]) == 2
            repeated = client.post(f"/api/v1/account/life/plans/{job_id}/decision", headers=a, json={"decision": "allow_once"})
            assert repeated.json()["saved"] == approved.json()["saved"]
            items = client.get("/api/v1/account/life/items", headers=a).json()
            assert len(items["tasks"]) == len(items["schedules"]) == 1
            assert items["schedules"][0]["title"] == "复习"
            task_id = items["tasks"][0]["id"]
            assert client.put(f"/api/v1/account/life/items/task/{task_id}", headers=b,
                              json={"title": "越权修改", "status": "done"}).status_code == 404
            changed = client.put(f"/api/v1/account/life/items/task/{task_id}", headers=a,
                                 json={"title": "买牛奶和面包", "status": "done"})
            assert changed.status_code == 200
            report = client.get("/api/v1/account/life/morning?date=2026-10-17", headers=a)
            assert report.status_code == 200, report.text
            assert report.json()["sleep"]["status"] == "not_authorized"
            assert report.json()["tasks"][0]["title"] == "买牛奶和面包"
            assert report.json()["schedules"][0]["title"] == "复习"
            assert client.get("/api/v1/account/life/morning?date=2026-10-17", headers=a).status_code == 200
            with session_engine().connect() as connection:
                count = connection.scalar(text("SELECT COUNT(*) FROM morning_reports WHERE user_id=:id AND report_date='2026-10-17'"), {"id": account_ids[0]})
            assert count == 1

            denied = client.post("/api/v1/account/life/plans", headers=a, json={"intent": "删除测试", "idempotencyKey": uuid4().hex})
            denied_id = denied.json()["jobId"]
            decision = client.post(f"/api/v1/account/life/plans/{denied_id}/decision", headers=a, json={"decision": "deny"})
            assert decision.json()["status"] == "cancelled"
            after = client.get("/api/v1/account/life/items", headers=a).json()
            assert len(after["tasks"]) == len(after["schedules"]) == 1
    finally:
        store = Redis.from_url("redis://127.0.0.1:6379/0")
        for token in (token_a, token_b):
            if token:
                store.delete(session_key(token))
        if account_ids:
            with session_engine().begin() as connection:
                for account_id in account_ids:
                    connection.execute(text("DELETE FROM agent_job_events WHERE user_id=:id"), {"id": account_id})
                    connection.execute(text("DELETE FROM approval_requests WHERE user_id=:id"), {"id": account_id})
                    connection.execute(text("DELETE FROM agent_jobs WHERE user_id=:id"), {"id": account_id})
                    connection.execute(text("DELETE FROM schedules WHERE user_id=:id"), {"id": account_id})
                    connection.execute(text("DELETE FROM tasks WHERE user_id=:id"), {"id": account_id})
                    connection.execute(text("DELETE FROM morning_reports WHERE user_id=:id"), {"id": account_id})
                    connection.execute(text("DELETE FROM users WHERE id=:id"), {"id": account_id})
