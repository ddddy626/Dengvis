import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from redis import Redis

from app.main import app
from app.demo_sessions import session_engine
from app.demo_tokens import token_digest


@pytest.fixture
def guest_headers():
    with TestClient(app) as client:
        response = client.post("/api/v1/demo/session")
    assert response.status_code == 201
    token = response.json()["token"]
    with session_engine().connect() as connection:
        session_id = connection.scalar(
            text("SELECT id FROM demo_sessions WHERE session_token_hash = :digest"),
            {"digest": token_digest(token)},
        )
    try:
        yield {"Authorization": f"Bearer {token}"}
    finally:
        Redis.from_url("redis://127.0.0.1:6379/0").delete(f"jarvis:demo:history:{session_id}")
        with session_engine().begin() as connection:
            connection.execute(text("DELETE FROM demo_sessions WHERE id = :id"), {"id": session_id})


def test_health():
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}


def test_invalid_message_has_shared_error_shape():
    with TestClient(app) as client:
        response = client.post("/api/v1/chat", json={"message": ""})
    assert response.status_code == 422
    assert set(response.json()) == {"code", "message", "requestId", "retryable"}


def test_missing_key_never_returns_fake_reply(monkeypatch, guest_headers):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    with TestClient(app) as client:
        response = client.post("/api/v1/chat", json={"message": "你好"}, headers=guest_headers)
    assert response.status_code == 503
    assert response.json()["code"] == "MODEL_NOT_CONFIGURED"
    assert "reply" not in response.json()


def test_success_uses_upstream_reply(monkeypatch, guest_headers):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")
    def upstream(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-only"
        return httpx.Response(200, json={"choices": [{"message": {"content": "真实上游文本"}}]})
    app.state.deepseek_transport = httpx.MockTransport(upstream)
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/chat", json={"message": "你好"}, headers=guest_headers)
        assert response.status_code == 200
        assert response.json()["reply"] == "真实上游文本"
    finally:
        del app.state.deepseek_transport


def test_empty_401_is_structured_and_hides_key(monkeypatch, guest_headers):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")
    app.state.deepseek_transport = httpx.MockTransport(lambda _: httpx.Response(401))
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/chat", json={"message": "你好"}, headers=guest_headers)
        assert response.status_code == 502
        assert response.json()["code"] == "MODEL_CREDENTIALS"
        assert "test-only" not in response.text
    finally:
        del app.state.deepseek_transport
