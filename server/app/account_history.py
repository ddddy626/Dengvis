"""Short-term text history for authenticated accounts, isolated from guests."""

import json
from datetime import datetime, timezone

from .demo_history import history_store


ACCOUNT_HISTORY_SECONDS = 24 * 60 * 60
MAX_HISTORY_ITEMS = 200


def account_history_key(user_id: int) -> str:
    return f"jarvis:account:history:{user_id}"


async def account_history_available() -> None:
    async with history_store() as store:
        await store.ping()


async def append_account_exchange(user_id: int, message: str, reply: str) -> None:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    entries = [
        json.dumps({"role": "user", "content": message, "createdAt": now}, ensure_ascii=False),
        json.dumps({"role": "assistant", "content": reply, "createdAt": now}, ensure_ascii=False),
    ]
    key = account_history_key(user_id)
    async with history_store() as store:
        async with store.pipeline(transaction=True) as pipe:
            pipe.rpush(key, *entries)
            pipe.ltrim(key, -MAX_HISTORY_ITEMS, -1)
            pipe.expire(key, ACCOUNT_HISTORY_SECONDS)
            await pipe.execute()


async def read_account_history(user_id: int) -> list[dict[str, str]]:
    async with history_store() as store:
        values = await store.lrange(account_history_key(user_id), 0, -1)
    return [json.loads(value) for value in values]
