"""Atomic guest model-call reservations and failure refunds."""

import os
import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import redis.asyncio as redis
from sqlalchemy import text

from .demo_sessions import session_engine


class DemoQuotaExceeded(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _positive_limit(name: str, default: int) -> int:
    return max(1, int(os.getenv(name, str(default))))


def _day_key() -> str:
    local_date = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    return f"{os.getenv('DEMO_QUOTA_PREFIX', 'jarvis:demo')}:daily_reserved_tokens:{local_date}"


def _active_key() -> str:
    return f"{os.getenv('DEMO_QUOTA_PREFIX', 'jarvis:demo')}:active_calls"


def _cost_key(day: str) -> str:
    return f"{os.getenv('DEMO_QUOTA_PREFIX', 'jarvis:demo')}:daily_reserved_fen:{day}"


async def allow_demo_session(client_host: str) -> bool:
    host_hash = hashlib.sha256(client_host.encode("utf-8")).hexdigest()
    key = f"{os.getenv('DEMO_QUOTA_PREFIX', 'jarvis:demo')}:new_sessions:{host_hash}"
    store = redis.Redis.from_url(os.getenv("JARVIS_REDIS_URL", "redis://127.0.0.1:6379/0"))
    async with store:
        count = await store.eval("""
            local count = redis.call('INCR', KEYS[1])
            if count == 1 then redis.call('EXPIRE', KEYS[1], 3600) end
            return count
        """, 1, key)
    return count <= _positive_limit("DEMO_MAX_NEW_SESSIONS_PER_IP_HOUR", 100)


def _reserve_session(session_id: int, limit: int) -> bool:
    with session_engine().begin() as connection:
        changed = connection.execute(text("""
            UPDATE demo_sessions SET quota_used=quota_used+1
            WHERE id=:id AND expires_at>UTC_TIMESTAMP(3) AND quota_used<:limit
        """), {"id": session_id, "limit": limit})
        return changed.rowcount == 1


def _refund_session(session_id: int) -> None:
    with session_engine().begin() as connection:
        connection.execute(text("""
            UPDATE demo_sessions SET quota_used=GREATEST(quota_used-1, 0) WHERE id=:id
        """), {"id": session_id})


_RESERVE_SCRIPT = """
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', ARGV[1])
local used = tonumber(redis.call('GET', KEYS[1]) or '0')
if used + tonumber(ARGV[2]) > tonumber(ARGV[3]) then return -1 end
if redis.call('ZCARD', KEYS[2]) >= tonumber(ARGV[4]) then return -2 end
local cost = tonumber(redis.call('GET', KEYS[3]) or '0')
if cost + tonumber(ARGV[6]) > tonumber(ARGV[7]) then return -3 end
redis.call('INCRBY', KEYS[1], ARGV[2])
redis.call('EXPIRE', KEYS[1], 172800)
redis.call('INCRBY', KEYS[3], ARGV[6])
redis.call('EXPIRE', KEYS[3], 172800)
redis.call('ZADD', KEYS[2], tonumber(ARGV[1]) + 90, ARGV[5])
redis.call('EXPIRE', KEYS[2], 180)
return 1
"""


_RELEASE_SCRIPT = """
local removed = redis.call('ZREM', KEYS[2], ARGV[1])
if removed == 1 and ARGV[3] == '1' then
  local remaining = redis.call('DECRBY', KEYS[1], ARGV[2])
  if remaining < 0 then redis.call('SET', KEYS[1], 0, 'EX', 172800) end
  local cost = redis.call('DECRBY', KEYS[3], ARGV[4])
  if cost < 0 then redis.call('SET', KEYS[3], 0, 'EX', 172800) end
end
return removed
"""


async def reserve_demo_call(session_id: int, message: str, *, overhead_bytes: int = 1024, max_output_tokens: int = 800) -> str:
    session_limit = _positive_limit("DEMO_MAX_CALLS_PER_SESSION", 10)
    if not await asyncio.to_thread(_reserve_session, session_id, session_limit):
        raise DemoQuotaExceeded("DEMO_SESSION_QUOTA", "本次游客会话的体验次数已用完。")
    try:
        return await reserve_model_call(message, overhead_bytes=overhead_bytes, max_output_tokens=max_output_tokens)
    except BaseException:
        await asyncio.to_thread(_refund_session, session_id)
        raise


async def reserve_model_call(message: str, *, overhead_bytes: int = 1024, max_output_tokens: int = 800) -> str:
    daily_limit = _positive_limit("DEMO_MAX_DAILY_RESERVED_TOKENS", 500_000)
    concurrency_limit = _positive_limit("DEMO_MAX_CONCURRENT_CALLS", 1)
    cost_limit_fen = _positive_limit("DEMO_MAX_DAILY_COST_FEN", 1000)
    ceiling_fen_per_million = _positive_limit("DEMO_COST_CEILING_FEN_PER_MILLION_TOKENS", 10_000)
    reserved_tokens = len(message.encode("utf-8")) + max_output_tokens + overhead_bytes  # Conservatively upper-bound input tokens by UTF-8 bytes.
    reserved_fen = max(1, (reserved_tokens * ceiling_fen_per_million + 999_999) // 1_000_000)
    daily_key = _day_key()
    day = daily_key.rsplit(':', 1)[1]
    reservation_id = f"{day}:{reserved_tokens}:{reserved_fen}:{uuid4().hex}"
    store = redis.Redis.from_url(os.getenv("JARVIS_REDIS_URL", "redis://127.0.0.1:6379/0"), decode_responses=True)
    async with store:
        outcome = await store.eval(_RESERVE_SCRIPT, 3, daily_key, _active_key(), _cost_key(day),
                                   int(datetime.now(timezone.utc).timestamp()), reserved_tokens,
                                   daily_limit, concurrency_limit, reservation_id,
                                   reserved_fen, cost_limit_fen)
    if outcome != 1:
        if outcome == -1:
            raise DemoQuotaExceeded("DEMO_DAILY_BUDGET", "今日游客体验额度已用完。")
        if outcome == -3:
            raise DemoQuotaExceeded("DEMO_DAILY_COST_BUDGET", "今日模型预算已用完。")
        raise DemoQuotaExceeded("DEMO_BUSY", "当前体验人数较多，请稍后重试。")
    return reservation_id


async def finish_demo_call(session_id: int, reservation_id: str, succeeded: bool, *, model_charged: bool | None = None) -> None:
    try:
        await finish_model_call(reservation_id, succeeded if model_charged is None else model_charged)
    finally:
        if not succeeded:
            await asyncio.to_thread(_refund_session, session_id)


async def finish_model_call(reservation_id: str, succeeded: bool) -> None:
    day, tokens, fen, _ = reservation_id.split(':', 3)
    daily_key = f"{os.getenv('DEMO_QUOTA_PREFIX', 'jarvis:demo')}:daily_reserved_tokens:{day}"
    reserved_tokens = int(tokens)
    store = redis.Redis.from_url(os.getenv("JARVIS_REDIS_URL", "redis://127.0.0.1:6379/0"), decode_responses=True)
    async with store:
        await store.eval(_RELEASE_SCRIPT, 3, daily_key, _active_key(), _cost_key(day),
                         reservation_id, reserved_tokens,
                         "0" if succeeded else "1", int(fen))
