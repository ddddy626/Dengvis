"""Guest quota enforces total and concurrent bounds and refunds model failures."""

import asyncio
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import text

from app.demo_quota import DemoQuotaExceeded, finish_demo_call, reserve_demo_call, reserve_model_call, finish_model_call
from app.demo_sessions import create_demo_session, session_engine
from app.main import app


def _count(session_id: int) -> int:
    with session_engine().connect() as connection:
        return connection.scalar(text("SELECT quota_used FROM demo_sessions WHERE id=:id"), {"id": session_id})


def _cleanup(ids: list[int], prefix: str):
    store = Redis.from_url("redis://127.0.0.1:6379/0")
    for key in store.scan_iter(f"{prefix}:*"):
        store.delete(key)
    with session_engine().begin() as connection:
        for session_id in ids:
            connection.execute(text("DELETE FROM demo_sessions WHERE id=:id"), {"id": session_id})


def test_success_counts_once_daily_and_session_limits(monkeypatch):
    prefix = f"test:demo:{uuid4().hex}"
    monkeypatch.setenv("DEMO_QUOTA_PREFIX", prefix)
    monkeypatch.setenv("DEMO_MAX_CALLS_PER_SESSION", "1")
    monkeypatch.setenv("DEMO_MAX_DAILY_RESERVED_TOKENS", "1830")
    monkeypatch.setenv("DEMO_MAX_CONCURRENT_CALLS", "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")
    app.state.deepseek_transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"choices": [{"message": {"content": "测试回复"}}]}))
    ids = []
    try:
        token, session = create_demo_session()
        ids.append(session.id)
        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token}"}
            assert client.post("/api/v1/chat", headers=headers, json={"message": "你好"}).status_code == 200
            assert _count(session.id) == 1
            denied = client.post("/api/v1/chat", headers=headers, json={"message": "再来一次"})
            assert denied.status_code == 429
            assert denied.json()["code"] == "DEMO_SESSION_QUOTA"
            second_token, second = create_demo_session()
            ids.append(second.id)
            global_denied = client.post("/api/v1/chat", headers={"Authorization": f"Bearer {second_token}"}, json={"message": "你好"})
            assert global_denied.status_code == 429
            assert global_denied.json()["code"] == "DEMO_DAILY_BUDGET"
            assert _count(second.id) == 0
    finally:
        del app.state.deepseek_transport
        for session_id in ids:
            Redis.from_url("redis://127.0.0.1:6379/0").delete(f"jarvis:demo:history:{session_id}")
        _cleanup(ids, prefix)


def test_model_failure_refunds_and_concurrency_releases(monkeypatch):
    prefix = f"test:demo:{uuid4().hex}"
    monkeypatch.setenv("DEMO_QUOTA_PREFIX", prefix)
    monkeypatch.setenv("DEMO_MAX_CALLS_PER_SESSION", "2")
    monkeypatch.setenv("DEMO_MAX_DAILY_RESERVED_TOKENS", "11600")
    monkeypatch.setenv("DEMO_MAX_CONCURRENT_CALLS", "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    ids = []
    try:
        token, first = create_demo_session()
        ids.append(first.id)
        _, second = create_demo_session()
        ids.append(second.id)
        with TestClient(app) as client:
            response = client.post("/api/v1/chat", headers={"Authorization": f"Bearer {token}"}, json={"message": "你好"})
        assert response.status_code == 503
        assert response.json()["code"] == "MODEL_NOT_CONFIGURED"
        assert _count(first.id) == 0

        async def check_concurrent():
            reservation = await reserve_demo_call(first.id, "你好")
            with pytest.raises(DemoQuotaExceeded) as raised:
                await reserve_demo_call(second.id, "你好")
            assert raised.value.code == "DEMO_BUSY"
            assert _count(second.id) == 0
            await finish_demo_call(first.id, reservation, False)

        asyncio.run(check_concurrent())
        assert _count(first.id) == 0
    finally:
        for session_id in ids:
            Redis.from_url("redis://127.0.0.1:6379/0").delete(f"jarvis:demo:history:{session_id}")
        _cleanup(ids, prefix)


def test_new_guest_session_rate_limit(monkeypatch):
    prefix = f"test:demo:{uuid4().hex}"
    monkeypatch.setenv("DEMO_QUOTA_PREFIX", prefix)
    monkeypatch.setenv("DEMO_MAX_NEW_SESSIONS_PER_IP_HOUR", "1")
    ids = []
    try:
        with TestClient(app) as client:
            first = client.post("/api/v1/demo/session")
            assert first.status_code == 201, first.text
            second = client.post("/api/v1/demo/session")
            assert second.status_code == 429
            assert second.json()["code"] == "DEMO_SESSION_RATE_LIMITED"
        from app.demo_tokens import token_digest
        with session_engine().connect() as connection:
            ids.append(connection.scalar(text("SELECT id FROM demo_sessions WHERE session_token_hash=:digest"),
                                         {"digest": token_digest(first.json()["token"])}))
    finally:
        _cleanup(ids, prefix)


def test_shared_daily_cost_reservation_and_refund(monkeypatch):
    prefix = f"test:demo:{uuid4().hex}"
    monkeypatch.setenv("DEMO_QUOTA_PREFIX", prefix)
    monkeypatch.setenv("DEMO_MAX_DAILY_RESERVED_TOKENS", "100000")
    monkeypatch.setenv("DEMO_MAX_DAILY_COST_FEN", "20")
    monkeypatch.setenv("DEMO_COST_CEILING_FEN_PER_MILLION_TOKENS", "10000")
    monkeypatch.setenv("DEMO_MAX_CONCURRENT_CALLS", "1")

    async def check():
        first = await reserve_model_call("你好")
        await finish_model_call(first, True)
        with pytest.raises(DemoQuotaExceeded) as raised:
            await reserve_model_call("你好")
        assert raised.value.code == "DEMO_DAILY_COST_BUDGET"

        monkeypatch.setenv("DEMO_MAX_DAILY_COST_FEN", "40")
        second = await reserve_model_call("你好")
        await finish_model_call(second, False)
        third = await reserve_model_call("你好")
        await finish_model_call(third, True)

    try:
        asyncio.run(check())
    finally:
        _cleanup([], prefix)
