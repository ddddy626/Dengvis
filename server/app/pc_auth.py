"""One-time account-to-PC pairing without sharing account credentials."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from .demo_sessions import session_engine


class PairFailure(Exception):
    pass


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("ascii")).hexdigest()


def create_pair_code(user_id: int) -> dict:
    code = secrets.token_urlsafe(32)
    with session_engine().begin() as connection:
        connection.execute(text("""
            UPDATE pc_pair_requests SET consumed_at=UTC_TIMESTAMP(3)
            WHERE user_id=:user_id AND consumed_at IS NULL
        """), {"user_id": user_id})
        row_id = connection.execute(text("""
            INSERT INTO pc_pair_requests (user_id, code_hash, expires_at)
            VALUES (:user_id, :code_hash, UTC_TIMESTAMP(3) + INTERVAL 10 MINUTE)
        """), {"user_id": user_id, "code_hash": _hash(code)}).lastrowid
        expires = connection.scalar(text("SELECT expires_at FROM pc_pair_requests WHERE id=:id"), {"id": row_id})
    return {"code": code, "expiresAt": expires.isoformat() + "Z"}


def consume_pair_code(code: str) -> dict:
    if not 30 <= len(code) <= 128 or not code.isascii():
        raise PairFailure("配对码无效或已过期。")
    token = secrets.token_urlsafe(32)
    device_secret = secrets.token_urlsafe(32)
    with session_engine().begin() as connection:
        row = connection.execute(text("""
            SELECT id, user_id, expires_at, consumed_at FROM pc_pair_requests
            WHERE code_hash=:code_hash FOR UPDATE
        """), {"code_hash": _hash(code)}).mappings().first()
        if not row or row["consumed_at"] is not None or row["expires_at"] <= datetime.now(timezone.utc).replace(tzinfo=None):
            raise PairFailure("配对码无效或已过期。")
        device_id = connection.execute(text("""
            INSERT INTO devices (user_id, device_type, device_id_hash, last_seen)
            VALUES (:user_id, 'pc_worker', :device_hash, UTC_TIMESTAMP(3))
        """), {"user_id": row["user_id"], "device_hash": _hash(device_secret)}).lastrowid
        connection.execute(text("""
            INSERT INTO pc_worker_tokens (user_id, device_id, token_hash, expires_at)
            VALUES (:user_id, :device_id, :token_hash, UTC_TIMESTAMP(3) + INTERVAL 90 DAY)
        """), {"user_id": row["user_id"], "device_id": device_id, "token_hash": _hash(token)})
        connection.execute(text("UPDATE pc_pair_requests SET consumed_at=UTC_TIMESTAMP(3) WHERE id=:id"), {"id": row["id"]})
    return {"token": token, "deviceId": device_id, "expiresAt": (datetime.now(timezone.utc) + timedelta(days=90)).isoformat()}


def worker_identity(token: str, heartbeat: bool = False) -> tuple[int, int] | None:
    if not 30 <= len(token) <= 128 or not token.isascii():
        return None
    with session_engine().begin() as connection:
        row = connection.execute(text("""
            SELECT user_id, device_id FROM pc_worker_tokens
            WHERE token_hash=:token_hash AND revoked_at IS NULL AND expires_at>UTC_TIMESTAMP(3)
        """), {"token_hash": _hash(token)}).mappings().first()
        if not row:
            return None
        if heartbeat:
            connection.execute(text("""
                UPDATE devices SET last_seen=UTC_TIMESTAMP(3)
                WHERE id=:device_id AND user_id=:user_id
            """), {"device_id": row["device_id"], "user_id": row["user_id"]})
        return row["user_id"], row["device_id"]


def list_devices(user_id: int) -> list[dict]:
    with session_engine().connect() as connection:
        rows = connection.execute(text("""
            SELECT d.id, d.last_seen, t.expires_at, t.revoked_at
            FROM devices d JOIN pc_worker_tokens t ON t.device_id=d.id AND t.user_id=d.user_id
            WHERE d.user_id=:user_id ORDER BY d.id DESC
        """), {"user_id": user_id}).mappings().all()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return [{"deviceId": row["id"], "online": bool(row["last_seen"] and row["last_seen"] > now - timedelta(seconds=90)
             and row["revoked_at"] is None and row["expires_at"] > now),
             "lastSeen": row["last_seen"].isoformat() + "Z" if row["last_seen"] else None,
             "revoked": row["revoked_at"] is not None} for row in rows]


def revoke_device(user_id: int, device_id: int) -> bool | None:
    with session_engine().begin() as connection:
        row = connection.execute(text("""
            SELECT revoked_at FROM pc_worker_tokens WHERE user_id=:user_id AND device_id=:device_id FOR UPDATE
        """), {"user_id": user_id, "device_id": device_id}).mappings().first()
        if row is None:
            return None
        if row["revoked_at"] is not None:
            return False
        connection.execute(text("""
            UPDATE pc_worker_tokens SET revoked_at=UTC_TIMESTAMP(3)
            WHERE user_id=:user_id AND device_id=:device_id
        """), {"user_id": user_id, "device_id": device_id})
        return True
