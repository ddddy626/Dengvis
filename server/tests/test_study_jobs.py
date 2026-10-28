"""PC jobs remain account-owned through claim, failure, retry and completion."""

import asyncio
from uuid import uuid4

from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import text

from app.account_auth import issue_access_token, session_key
from app.demo_sessions import session_engine
from app.main import app


def test_study_claim_retry_complete_cancel_and_isolation():
    ids = []
    tokens = []
    try:
        with session_engine().begin() as connection:
            for _ in range(2):
                ids.append(connection.execute(text("""
                    INSERT INTO users (email, password_hash, status)
                    VALUES (:email, 'test-only', 'active')
                """), {"email": f"study-{uuid4().hex}@example.com"}).lastrowid)
        for account_id in ids:
            tokens.append(asyncio.run(issue_access_token(account_id))[0])
        a, b = ({"Authorization": f"Bearer {token}"} for token in tokens)
        with TestClient(app) as client:
            code = client.post("/api/v1/account/pc/pair", headers=a).json()["code"]
            worker = {"Authorization": f"Bearer {client.post('/api/v1/pc/pair', json={'code': code}).json()['token']}"}
            first = client.post("/api/v1/account/pc/study", headers=a,
                                json={"query": "复习向量检索", "idempotencyKey": uuid4().hex})
            assert first.status_code == 201, first.text
            job_id = first.json()["jobId"]
            assert first.json()["status"] == "waiting_pc"
            assert client.get(f"/api/v1/account/pc/study/{job_id}", headers=b).status_code == 404
            claimed = client.post("/api/v1/pc/study/claim", headers=worker)
            assert claimed.status_code == 200, claimed.text
            assert claimed.json()["job"]["jobId"] == job_id
            assert client.post("/api/v1/pc/study/claim", headers=worker).json()["job"] is None
            failed = client.post(f"/api/v1/pc/study/{job_id}/complete", headers=worker,
                                 json={"success": False, "modelName": "local-test", "elapsedMs": 1,
                                       "error": "测试失败", "excerpts": []})
            assert failed.status_code == 200, failed.text
            assert failed.json()["status"] == "failed"
            assert client.post(f"/api/v1/account/pc/study/{job_id}/retry", headers=b).status_code == 404
            assert client.post(f"/api/v1/account/pc/study/{job_id}/retry", headers=a).json()["status"] == "waiting_pc"
            assert client.post("/api/v1/pc/study/claim", headers=worker).json()["job"]["jobId"] == job_id
            success = client.post(f"/api/v1/pc/study/{job_id}/complete", headers=worker,
                                  json={"success": True, "modelName": "hashing-char-3gram-v1", "elapsedMs": 12,
                                        "excerpts": [{"source": "notes.pdf", "page": 1, "text": "向量检索示例", "score": 0.8}]})
            assert success.status_code == 200, success.text
            assert success.json()["status"] == "succeeded"
            assert success.json()["result"]["excerpts"][0]["text"] == "向量检索示例"
            study_draft = client.post(f"/api/v1/account/pc/study/{job_id}/draft", headers=a)
            assert study_draft.status_code == 200, study_draft.text
            assert study_draft.json()["status"] == "waiting_approval"
            assert "notes.pdf 第 1 页" in study_draft.json()["items"][0]["title"]
            assert client.post(f"/api/v1/account/pc/study/{job_id}/draft", headers=a).json()["jobId"] == study_draft.json()["jobId"]
            assert client.get("/api/v1/account/life/items", headers=a).json()["tasks"] == []
            approved_draft = client.post(f"/api/v1/account/life/plans/{study_draft.json()['jobId']}/decision",
                                         headers=a, json={"decision": "allow_once"})
            assert approved_draft.status_code == 200, approved_draft.text
            assert len(client.get("/api/v1/account/life/items", headers=a).json()["tasks"]) == 1
            assert client.post(f"/api/v1/account/life/jobs/{job_id}/cancel", headers=a).status_code == 409
            second = client.post("/api/v1/account/pc/study", headers=a,
                                 json={"query": "待取消任务", "idempotencyKey": uuid4().hex}).json()["jobId"]
            assert client.post(f"/api/v1/account/life/jobs/{second}/cancel", headers=a).json() == {"cancelled": True}
            assert client.post("/api/v1/pc/study/claim", headers=worker).json()["job"] is None
    finally:
        store = Redis.from_url("redis://127.0.0.1:6379/0")
        for token in tokens:
            store.delete(session_key(token))
        with session_engine().begin() as connection:
            for account_id in ids:
                connection.execute(text("DELETE FROM agent_job_events WHERE user_id=:id"), {"id": account_id})
                connection.execute(text("DELETE FROM approval_requests WHERE user_id=:id"), {"id": account_id})
                connection.execute(text("DELETE FROM agent_jobs WHERE user_id=:id"), {"id": account_id})
                connection.execute(text("DELETE FROM tasks WHERE user_id=:id"), {"id": account_id})
                connection.execute(text("DELETE FROM pc_worker_tokens WHERE user_id=:id"), {"id": account_id})
                connection.execute(text("DELETE FROM pc_pair_requests WHERE user_id=:id"), {"id": account_id})
                connection.execute(text("DELETE FROM devices WHERE user_id=:id"), {"id": account_id})
                connection.execute(text("DELETE FROM users WHERE id=:id"), {"id": account_id})
