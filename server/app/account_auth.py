"""Email/password accounts and revocable, short-lived access sessions."""

import hashlib
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

import redis.asyncio as redis
from argon2 import PasswordHasher, Type, exceptions
from dotenv import load_dotenv
from sqlalchemy import text

from .demo_sessions import session_engine, utc_iso


ACCESS_LIFETIME_SECONDS = 60 * 60
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{40,128}$")
PASSWORD_HASHER = PasswordHasher(time_cost=2, memory_cost=19_456, parallelism=1, type=Type.ID)
DUMMY_HASH = PASSWORD_HASHER.hash("unused-login-timing-password")


def account_store() -> redis.Redis:
    load_dotenv()
    return redis.Redis.from_url(
        os.getenv("JARVIS_REDIS_URL", "redis://127.0.0.1:6379/0"),
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=3,
    )


def account_token_from_authorization(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not TOKEN_PATTERN.fullmatch(token):
        return None
    return token


def session_key(token: str) -> str:
    digest = hashlib.sha256(token.encode("ascii")).hexdigest()
    return f"jarvis:account:session:{digest}"


async def check_rate_limit(action: str, client_host: str) -> bool:
    limit = 5 if action == "register" else 10
    host_digest = hashlib.sha256(client_host.encode("utf-8")).hexdigest()
    key = f"jarvis:account:rate:{action}:{host_digest}"
    async with account_store() as store:
        async with store.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, 60)
            count, _ = await pipe.execute()
    return count <= limit


def create_account(email: str, password: str) -> dict:
    password_hash = PASSWORD_HASHER.hash(password)
    with session_engine().begin() as connection:
        result = connection.execute(
            text("INSERT INTO users (email, password_hash, status) VALUES (:email, :password_hash, 'active')"),
            {"email": email, "password_hash": password_hash},
        )
        return {"id": result.lastrowid, "email": email}


def find_account_by_email(email: str) -> dict | None:
    with session_engine().connect() as connection:
        row = connection.execute(
            text("SELECT id, email, password_hash, status FROM users WHERE email = :email"),
            {"email": email},
        ).mappings().first()
    return dict(row) if row else None


def find_account_by_id(user_id: int) -> dict | None:
    with session_engine().connect() as connection:
        row = connection.execute(
            text("SELECT id, email, status FROM users WHERE id = :id"),
            {"id": user_id},
        ).mappings().first()
    return dict(row) if row else None


def password_matches(stored_hash: str, password: str) -> bool:
    try:
        return PASSWORD_HASHER.verify(stored_hash, password)
    except (exceptions.VerificationError, exceptions.InvalidHashError):
        return False


async def issue_access_token(user_id: int) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    async with account_store() as store:
        await store.set(session_key(token), str(user_id), ex=ACCESS_LIFETIME_SECONDS)
    expiry = datetime.now(timezone.utc) + timedelta(seconds=ACCESS_LIFETIME_SECONDS)
    return token, utc_iso(expiry.replace(tzinfo=None))


async def account_id_for_token(token: str) -> int | None:
    async with account_store() as store:
        value = await store.get(session_key(token))
    return int(value) if value and value.isdecimal() else None


async def revoke_access_token(token: str) -> None:
    async with account_store() as store:
        await store.delete(session_key(token))
