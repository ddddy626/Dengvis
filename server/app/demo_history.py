"""Short-lived chat records isolated by the validated guest session ID."""

import json
import os
from datetime import datetime, timezone

import redis.asyncio as redis
from dotenv import load_dotenv

from .demo_sessions import DemoSession


def history_store() -> redis.Redis:
    load_dotenv()
    return redis.Redis.from_url(
        os.getenv("JARVIS_REDIS_URL", "redis://127.0.0.1:6379/0"),
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=3,
    )


def history_key(session: DemoSession) -> str:
    return f"jarvis:demo:history:{session.id}"


async def history_available() -> None:
    async with history_store() as store:
        await store.ping()


async def append_exchange(session: DemoSession, message: str, reply: str) -> None:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    entries = [
        json.dumps({"role": "user", "content": message, "createdAt": now}, ensure_ascii=False),
        json.dumps({"role": "assistant", "content": reply, "createdAt": now}, ensure_ascii=False),
    ]
    async with history_store() as store:
        async with store.pipeline(transaction=True) as pipe:
            pipe.rpush(history_key(session), *entries)
            pipe.expireat(history_key(session), int(session.expires_at.replace(tzinfo=timezone.utc).timestamp()))
            await pipe.execute()


async def read_history(session: DemoSession) -> list[dict[str, str]]:
    async with history_store() as store:
        values = await store.lrange(history_key(session), 0, -1)
    return [json.loads(value) for value in values]
