"""Web demo life items stay in the demo session, never in an account."""

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.demo_sessions import session_engine
from app.demo_tokens import token_digest
from app.main import app


def test_demo_approval_and_session_isolation():
    tokens = []
    session_ids = []
    try:
        with TestClient(app) as client:
            for _ in range(2):
                token = client.post("/api/v1/demo/session").json()["token"]
                tokens.append(token)
            with session_engine().connect() as connection:
                for token in tokens:
                    session_ids.append(connection.scalar(text("SELECT id FROM demo_sessions WHERE session_token_hash=:digest"),
                                                         {"digest": token_digest(token)}))
            a = {"Authorization": f"Bearer {tokens[0]}"}
            b = {"Authorization": f"Bearer {tokens[1]}"}
            created = client.post("/api/v1/demo/life/plans", headers=a,
                                  json={"intent": "提醒买牛奶", "idempotencyKey": uuid4().hex})
            assert created.status_code == 201, created.text
            job_id = created.json()["jobId"]
            assert client.get(f"/api/v1/demo/life/plans/{job_id}", headers=b).status_code == 404
            assert client.get("/api/v1/demo/life/items", headers=b).json() == {"tasks": [], "schedules": []}
            approved = client.post(f"/api/v1/demo/life/plans/{job_id}/decision", headers=a,
                                   json={"decision": "allow_once"})
            assert approved.status_code == 200, approved.text
            assert approved.json()["status"] == "succeeded"
            assert len(client.get("/api/v1/demo/life/items", headers=a).json()["tasks"]) == 1
            assert client.get("/api/v1/demo/life/items", headers=b).json()["tasks"] == []
            item_id = client.get("/api/v1/demo/life/items", headers=a).json()["tasks"][0]["id"]
            assert client.put(f"/api/v1/demo/life/items/task/{item_id}", headers=b,
                              json={"title": "越权", "status": "done"}).status_code == 404
            assert client.put(f"/api/v1/demo/life/items/task/{item_id}", headers=a,
                              json={"title": "牛奶已买", "status": "done"}).status_code == 200
            morning = client.get("/api/v1/demo/life/morning?date=2026-10-17", headers=a)
            assert morning.status_code == 200
            assert morning.json()["sleep"]["status"] == "not_authorized"
            assert morning.json()["tasks"][0]["title"] == "牛奶已买"

            rejected = client.post("/api/v1/demo/life/plans", headers=a,
                                   json={"intent": "拒绝事项", "idempotencyKey": uuid4().hex})
            rejected_id = rejected.json()["jobId"]
            assert client.post(f"/api/v1/demo/life/plans/{rejected_id}/decision", headers=a,
                               json={"decision": "deny"}).json()["status"] == "cancelled"
            assert len(client.get("/api/v1/demo/life/items", headers=a).json()["tasks"]) == 1
    finally:
        if session_ids:
            with session_engine().begin() as connection:
                for session_id in session_ids:
                    connection.execute(text("DELETE FROM agent_job_events WHERE demo_session_id=:id"), {"id": session_id})
                    connection.execute(text("DELETE FROM approval_requests WHERE demo_session_id=:id"), {"id": session_id})
                    connection.execute(text("DELETE FROM agent_jobs WHERE demo_session_id=:id"), {"id": session_id})
                    connection.execute(text("DELETE FROM demo_schedules WHERE demo_session_id=:id"), {"id": session_id})
                    connection.execute(text("DELETE FROM demo_tasks WHERE demo_session_id=:id"), {"id": session_id})
                    connection.execute(text("DELETE FROM demo_sessions WHERE id=:id"), {"id": session_id})
