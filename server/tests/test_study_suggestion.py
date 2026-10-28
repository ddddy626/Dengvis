"""Opt-in cloud study suggestions are account-scoped and remain unapproved."""

import asyncio
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import text

from app.account_auth import issue_access_token, session_key
from app.demo_sessions import session_engine
from app.main import app


def test_study_suggestion_owner_consent_and_no_write(monkeypatch):
    prefix = f"test:study:suggest:{uuid4().hex}"
    monkeypatch.setenv("DEMO_QUOTA_PREFIX", prefix)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")
    ids, tokens = [], []
    seen = []

    def model(request: httpx.Request) -> httpx.Response:
        seen.append(request.read().decode())
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "content": '{"items":[{"kind":"task","title":"整理向量检索笔记 [1]"}],"questions":[]}'
        }}]})

    app.state.deepseek_transport = httpx.MockTransport(model)
    try:
        with session_engine().begin() as connection:
            for _ in range(2):
                ids.append(connection.execute(text("""
                    INSERT INTO users (email, password_hash, status)
                    VALUES (:email, 'test-only', 'active')
                """), {"email": f"study-suggest-{uuid4().hex}@example.com"}).lastrowid)
        for account_id in ids:
            tokens.append(asyncio.run(issue_access_token(account_id))[0])
        owner, other = ({"Authorization": f"Bearer {token}"} for token in tokens)
        with TestClient(app) as client:
            pair = client.post("/api/v1/account/pc/pair", headers=owner)
            assert pair.status_code == 200, pair.text
            worker_token = client.post("/api/v1/pc/pair", json={"code": pair.json()["code"]}).json()["token"]
            worker = {"Authorization": f"Bearer {worker_token}"}
            created = client.post("/api/v1/account/pc/study", headers=owner,
                                  json={"query": "复习向量检索", "idempotencyKey": uuid4().hex})
            assert created.status_code == 201, created.text
            job_id = created.json()["jobId"]
            url = f"/api/v1/account/pc/study/{job_id}/suggest"
            assert client.post(url, headers=other).status_code == 404
            assert client.post(url, headers=owner).status_code == 409
            assert client.post("/api/v1/pc/study/claim", headers=worker).json()["job"]["jobId"] == job_id
            complete = client.post(f"/api/v1/pc/study/{job_id}/complete", headers=worker, json={
                "success": True, "modelName": "local-test", "elapsedMs": 1,
                "excerpts": [{"source": "notes.pdf", "page": 7, "text": "向量检索示例", "score": 0.9}],
            })
            assert complete.status_code == 200, complete.text
            with session_engine().connect() as connection:
                approvals_before = connection.scalar(text("SELECT COUNT(*) FROM approval_requests WHERE user_id=:id"), {"id": ids[0]})
            suggested = client.post(url, headers=owner)
            assert suggested.status_code == 200, suggested.text
            assert suggested.json()["items"][0]["title"] == "notes.pdf 第7页：整理向量检索笔记"
            assert client.get("/api/v1/account/life/items", headers=owner).json()["tasks"] == []
            with session_engine().connect() as connection:
                assert connection.scalar(text("SELECT COUNT(*) FROM approval_requests WHERE user_id=:id"), {"id": ids[0]}) == approvals_before
        assert len(seen) == 1
        assert "notes.pdf" in seen[0] and "向量检索示例" in seen[0]
    finally:
        del app.state.deepseek_transport
        store = Redis.from_url("redis://127.0.0.1:6379/0")
        for token in tokens:
            store.delete(session_key(token))
        for key in store.scan_iter(f"{prefix}:*"):
            store.delete(key)
        with session_engine().begin() as connection:
            for account_id in ids:
                connection.execute(text("DELETE FROM agent_job_events WHERE user_id=:id"), {"id": account_id})
                connection.execute(text("DELETE FROM approval_requests WHERE user_id=:id"), {"id": account_id})
                connection.execute(text("DELETE FROM agent_jobs WHERE user_id=:id"), {"id": account_id})
                connection.execute(text("DELETE FROM pc_worker_tokens WHERE user_id=:id"), {"id": account_id})
                connection.execute(text("DELETE FROM pc_pair_requests WHERE user_id=:id"), {"id": account_id})
                connection.execute(text("DELETE FROM devices WHERE user_id=:id"), {"id": account_id})
                connection.execute(text("DELETE FROM users WHERE id=:id"), {"id": account_id})
