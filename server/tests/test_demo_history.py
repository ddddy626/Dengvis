import httpx
from fastapi.testclient import TestClient
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import text

from app.demo_tokens import token_digest
from app.demo_sessions import session_engine
from app.main import app


def test_guest_history_is_isolated_and_expires_with_session(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")
    app.state.deepseek_transport = httpx.MockTransport(
        lambda _: httpx.Response(200, json={"choices": [{"message": {"content": "只属于游客 A"}}]})
    )
    created: list[tuple[str, int]] = []
    store = Redis.from_url("redis://127.0.0.1:6379/0")
    try:
        with TestClient(app) as client:
            for _ in range(2):
                response = client.post("/api/v1/demo/session")
                assert response.status_code == 201
                token = response.json()["token"]
                with session_engine().connect() as connection:
                    session_id = connection.scalar(
                        text("SELECT id FROM demo_sessions WHERE session_token_hash = :digest"),
                        {"digest": token_digest(token)},
                    )
                created.append((token, session_id))
            first, second = ({"Authorization": f"Bearer {token}"} for token, _ in created)
            sent = client.post("/api/v1/chat", json={"message": "A 的私有消息"}, headers=first)
            assert sent.status_code == 200
            history_a = client.get("/api/v1/chat/history", headers=first)
            history_b = client.get("/api/v1/chat/history", headers=second)
            assert history_a.status_code == history_b.status_code == 200
            assert [(item["role"], item["content"]) for item in history_a.json()["messages"]] == [
                ("user", "A 的私有消息"), ("assistant", "只属于游客 A")
            ]
            assert history_b.json()["messages"] == []
            ttl = store.ttl(f"jarvis:demo:history:{created[0][1]}")
            assert 0 < ttl <= 24 * 60 * 60

            with session_engine().begin() as connection:
                connection.execute(
                    text("UPDATE demo_sessions SET expires_at = UTC_TIMESTAMP(3) - INTERVAL 1 SECOND WHERE id = :id"),
                    {"id": created[0][1]},
                )
            assert client.get("/api/v1/chat/history", headers=first).status_code == 401
            assert client.get("/api/v1/chat/history", headers=second).status_code == 200
    finally:
        del app.state.deepseek_transport
        for _, session_id in created:
            store.delete(f"jarvis:demo:history:{session_id}")
            with session_engine().begin() as connection:
                connection.execute(text("DELETE FROM demo_sessions WHERE id = :id"), {"id": session_id})


def test_chat_requires_valid_guest_before_model_call(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")
    called = False

    def upstream(_request):
        nonlocal called
        called = True
        return httpx.Response(200, json={"choices": [{"message": {"content": "unexpected"}}]})

    app.state.deepseek_transport = httpx.MockTransport(upstream)
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/chat", json={"message": "你好"})
        assert response.status_code == 401
        assert response.json()["code"] == "DEMO_SESSION_INVALID"
        assert not called
    finally:
        del app.state.deepseek_transport


def test_redis_outage_does_not_call_model(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")
    called = False

    def upstream(_request):
        nonlocal called
        called = True
        return httpx.Response(200, json={"choices": [{"message": {"content": "unexpected"}}]})

    async def unavailable():
        raise RedisError("test-only outage")

    monkeypatch.setattr("app.main.history_available", unavailable)
    app.state.deepseek_transport = httpx.MockTransport(upstream)
    token = None
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/demo/session")
            assert response.status_code == 201
            token = response.json()["token"]
            failed = client.post(
                "/api/v1/chat", json={"message": "你好"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert failed.status_code == 503
        assert failed.json()["code"] == "HISTORY_STORE_UNAVAILABLE"
        assert not called
    finally:
        del app.state.deepseek_transport
        if token:
            with session_engine().begin() as connection:
                connection.execute(
                    text("DELETE FROM demo_sessions WHERE session_token_hash = :digest"),
                    {"digest": token_digest(token)},
                )
