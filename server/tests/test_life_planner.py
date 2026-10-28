"""Smart suggestions remain untrusted draft data and never write life items."""

import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import text

from app.deepseek import DeepSeekFailure
from app.demo_sessions import create_demo_session, session_engine
from app.life_planner import suggest_life, suggest_study_life
from app.main import app


def test_planner_accepts_reviewable_json_and_rejects_incomplete_schedule(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")
    seen = []

    def valid(request: httpx.Request) -> httpx.Response:
        seen.append(request.read())
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "content": '{"items":[{"kind":"task","title":"买牛奶"},{"kind":"task","title":"联系老师"}],"questions":["何时联系老师？"]}'
        }}]})

    result = asyncio.run(suggest_life("提醒买牛奶并联系老师", httpx.MockTransport(valid)))
    assert [item.title for item in result.items] == ["买牛奶", "联系老师"]
    assert result.questions == ["何时联系老师？"]
    assert b'json_object' in seen[0] and b'disabled' in seen[0]

    invalid = httpx.MockTransport(lambda _: httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
        "content": '{"items":[{"kind":"schedule","title":"开会"}],"questions":[]}'
    }}]}))
    with pytest.raises(DeepSeekFailure) as raised:
        asyncio.run(suggest_life("开会", invalid))
    assert raised.value.code == "PLANNER_BAD_RESPONSE"


def test_study_suggestion_requires_valid_citation_and_preserves_source(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")
    excerpts = [{"source": "notes.pdf", "page": 4, "text": "复习向量索引定义"}]

    def model_reply(title):
        return httpx.MockTransport(lambda _: httpx.Response(200, json={"choices": [
            {"finish_reason": "stop", "message": {"content":
                '{"items":[{"kind":"task","title":' + json.dumps(title, ensure_ascii=False)
                + '}],"questions":[]}'}}
        ]}))

    result = asyncio.run(suggest_study_life("复习资料", excerpts, model_reply("整理向量索引笔记 [1]")))
    assert result.items[0].title == "notes.pdf 第4页：整理向量索引笔记"
    for title in ("整理向量索引笔记", "整理向量索引笔记 [2]"):
        with pytest.raises(DeepSeekFailure) as raised:
            asyncio.run(suggest_study_life("复习资料", excerpts, model_reply(title)))
        assert raised.value.code == "PLANNER_BAD_RESPONSE"


def test_guest_suggestion_uses_budget_but_does_not_write_plan(monkeypatch):
    prefix = f"test:planner:{uuid4().hex}"
    monkeypatch.setenv("DEMO_QUOTA_PREFIX", prefix)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")
    token, session = create_demo_session()
    app.state.deepseek_transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"choices": [
        {"finish_reason": "stop", "message": {"content": '{"items":[{"kind":"task","title":"买牛奶"}],"questions":[]}'}}
    ]}))
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/demo/life/suggest", headers={"Authorization": f"Bearer {token}"},
                                   json={"intent": "提醒买牛奶"})
        assert response.status_code == 200, response.text
        assert response.json()["items"][0]["title"] == "买牛奶"
        app.state.deepseek_transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"choices": [
            {"finish_reason": "stop", "message": {"content": '{"items":[{"kind":"schedule","title":"开会"}]}'}}
        ]}))
        with TestClient(app) as client:
            invalid = client.post("/api/v1/demo/life/suggest", headers={"Authorization": f"Bearer {token}"},
                                  json={"intent": "开会"})
        assert invalid.status_code == 503
        assert invalid.json()["code"] == "PLANNER_BAD_RESPONSE"
        with session_engine().connect() as connection:
            assert connection.scalar(text("SELECT COUNT(*) FROM agent_jobs WHERE demo_session_id=:id"), {"id": session.id}) == 0
            assert connection.scalar(text("SELECT quota_used FROM demo_sessions WHERE id=:id"), {"id": session.id}) == 1
        store = Redis.from_url("redis://127.0.0.1:6379/0")
        assert any(int(store.get(key)) > 0 for key in store.scan_iter(f"{prefix}:daily_reserved_fen:*"))
    finally:
        del app.state.deepseek_transport
        store = Redis.from_url("redis://127.0.0.1:6379/0")
        for key in store.scan_iter(f"{prefix}:*"):
            store.delete(key)
        with session_engine().begin() as connection:
            connection.execute(text("DELETE FROM demo_sessions WHERE id=:id"), {"id": session.id})
