"""Guest session persistence for the local demo."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from scripts.check_database import database_url

from .demo_tokens import issue_token, token_digest


SESSION_LIFETIME = timedelta(hours=24)


@dataclass(frozen=True)
class DemoSession:
    id: int
    expires_at: datetime


@lru_cache(maxsize=1)
def session_engine() -> Engine:
    return create_engine(
        database_url(),
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5, "read_timeout": 5, "write_timeout": 5},
    )


def create_demo_session() -> tuple[str, DemoSession]:
    token, digest = issue_token()
    now = datetime.now(timezone.utc)
    expires_at = (now + SESSION_LIFETIME).replace(
        tzinfo=None, microsecond=(now.microsecond // 1000) * 1000
    )
    with session_engine().begin() as connection:
        result = connection.execute(
            text("""
                INSERT INTO demo_sessions (session_token_hash, expires_at, seed_version)
                VALUES (:digest, :expires_at, 'local-demo-v1')
            """),
            {"digest": digest, "expires_at": expires_at},
        )
        session_id = result.lastrowid
    return token, DemoSession(id=session_id, expires_at=expires_at)


def find_demo_session(token: str) -> DemoSession | None:
    with session_engine().connect() as connection:
        row = connection.execute(
            text("""
                SELECT id, expires_at FROM demo_sessions
                WHERE session_token_hash = :digest AND expires_at > UTC_TIMESTAMP(3)
            """),
            {"digest": token_digest(token)},
        ).mappings().first()
    if row is None:
        return None
    return DemoSession(id=row["id"], expires_at=row["expires_at"])


def utc_iso(value: datetime) -> str:
    return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
