"""Explicit account memory consent and time bounded planning reads."""

from datetime import datetime, timezone

from sqlalchemy import text

from .demo_sessions import session_engine


class MemoryConflict(Exception):
    pass


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _present(row) -> dict:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    status = "expired" if row["status"] in ("candidate", "confirmed") and row["expires_at"] <= now else row["status"]
    return {"id": row["id"], "summary": row["summary"], "evidenceRef": row["evidence_ref"],
            "purpose": row["purpose"], "expiresAt": row["expires_at"].isoformat() + "Z",
            "status": status, "memoryId": row["memory_id"]}


def list_candidates(user_id: int) -> list[dict]:
    with session_engine().connect() as connection:
        rows = connection.execute(text("""
            SELECT c.*, m.id AS memory_id FROM memory_candidates c
            LEFT JOIN memories m ON m.user_id=c.user_id AND m.source_ref=CONCAT('candidate:', c.id)
            WHERE c.user_id=:user_id ORDER BY c.id DESC LIMIT 100
        """), {"user_id": user_id}).mappings().all()
    return [_present(row) for row in rows]


def create_candidate(user_id: int, summary: str, evidence_ref: str, purpose: str, expires_at: datetime) -> dict:
    if _utc(expires_at) <= datetime.now(timezone.utc).replace(tzinfo=None):
        raise MemoryConflict("记忆有效期必须晚于现在。")
    with session_engine().begin() as connection:
        candidate_id = connection.execute(text("""
            INSERT INTO memory_candidates (user_id, summary, evidence_ref, purpose, expires_at, status)
            VALUES (:user_id, :summary, :evidence_ref, :purpose, :expires_at, 'candidate')
        """), {"user_id": user_id, "summary": summary, "evidence_ref": evidence_ref,
               "purpose": purpose, "expires_at": _utc(expires_at)}).lastrowid
    return next(row for row in list_candidates(user_id) if row["id"] == candidate_id)


def edit_candidate(user_id: int, candidate_id: int, summary: str, purpose: str, expires_at: datetime) -> dict | None:
    if _utc(expires_at) <= datetime.now(timezone.utc).replace(tzinfo=None):
        raise MemoryConflict("记忆有效期必须晚于现在。")
    with session_engine().begin() as connection:
        row = connection.execute(text("""
            SELECT status, expires_at FROM memory_candidates WHERE id=:id AND user_id=:user_id FOR UPDATE
        """), {"id": candidate_id, "user_id": user_id}).mappings().first()
        if not row:
            return None
        if row["status"] not in ("candidate", "confirmed"):
            raise MemoryConflict("此记忆已失效，不能编辑。")
        if row["expires_at"] <= datetime.now(timezone.utc).replace(tzinfo=None):
            raise MemoryConflict("此记忆已过期，请重新提出候选记忆。")
        connection.execute(text("""
            UPDATE memory_candidates SET summary=:summary, purpose=:purpose, expires_at=:expires_at
            WHERE id=:id AND user_id=:user_id
        """), {"summary": summary, "purpose": purpose, "expires_at": _utc(expires_at),
               "id": candidate_id, "user_id": user_id})
        if row["status"] == "confirmed":
            connection.execute(text("""
                UPDATE memories SET content=:summary, category=:purpose
                WHERE user_id=:user_id AND source_ref=:source AND revoked_at IS NULL
            """), {"summary": summary, "purpose": purpose, "user_id": user_id,
                   "source": f"candidate:{candidate_id}"})
    return next(row for row in list_candidates(user_id) if row["id"] == candidate_id)


def decide_candidate(user_id: int, candidate_id: int, allow: bool) -> dict | None:
    with session_engine().begin() as connection:
        row = connection.execute(text("""
            SELECT id, summary, purpose, expires_at, status FROM memory_candidates
            WHERE id=:id AND user_id=:user_id FOR UPDATE
        """), {"id": candidate_id, "user_id": user_id}).mappings().first()
        if not row:
            return None
        if row["status"] == ("confirmed" if allow else "rejected"):
            pass
        elif row["status"] != "candidate":
            raise MemoryConflict("此候选记忆已经处理。")
        elif row["expires_at"] <= datetime.now(timezone.utc).replace(tzinfo=None):
            raise MemoryConflict("候选记忆已过期。")
        elif allow:
            connection.execute(text("""
                INSERT INTO memories (user_id, content, category, source_ref, confirmed_at)
                VALUES (:user_id, :content, :category, :source, UTC_TIMESTAMP(3))
            """), {"user_id": user_id, "content": row["summary"], "category": row["purpose"],
                   "source": f"candidate:{candidate_id}"})
            connection.execute(text("UPDATE memory_candidates SET status='confirmed' WHERE id=:id"), {"id": candidate_id})
        else:
            connection.execute(text("UPDATE memory_candidates SET status='rejected' WHERE id=:id"), {"id": candidate_id})
    return next(row for row in list_candidates(user_id) if row["id"] == candidate_id)


def revoke_memory(user_id: int, candidate_id: int) -> bool | None:
    with session_engine().begin() as connection:
        row = connection.execute(text("""
            SELECT status FROM memory_candidates WHERE id=:id AND user_id=:user_id FOR UPDATE
        """), {"id": candidate_id, "user_id": user_id}).mappings().first()
        if not row:
            return None
        if row["status"] == "rejected":
            return False
        connection.execute(text("UPDATE memory_candidates SET status='rejected' WHERE id=:id"), {"id": candidate_id})
        connection.execute(text("""
            UPDATE memories SET revoked_at=UTC_TIMESTAMP(3)
            WHERE user_id=:user_id AND source_ref=:source AND revoked_at IS NULL
        """), {"user_id": user_id, "source": f"candidate:{candidate_id}"})
        return True


def delete_memory(user_id: int, candidate_id: int) -> bool | None:
    """Remove the candidate and its confirmed memory; approved tasks remain separate."""
    with session_engine().begin() as connection:
        exists = connection.scalar(text("""
            SELECT id FROM memory_candidates WHERE id=:id AND user_id=:user_id FOR UPDATE
        """), {"id": candidate_id, "user_id": user_id})
        if exists is None:
            return None
        connection.execute(text("""
            DELETE FROM memories WHERE user_id=:user_id AND source_ref=:source
        """), {"user_id": user_id, "source": f"candidate:{candidate_id}"})
        connection.execute(text("""
            DELETE FROM memory_candidates WHERE id=:id AND user_id=:user_id
        """), {"id": candidate_id, "user_id": user_id})
        return True


def planning_memories(user_id: int, limit: int = 20) -> list[str]:
    """Only confirmed, current, unrevoked planning memories may influence a plan."""
    with session_engine().connect() as connection:
        rows = connection.execute(text("""
            SELECT m.content FROM memories m JOIN memory_candidates c
            ON m.source_ref=CONCAT('candidate:', c.id) AND m.user_id=c.user_id
            WHERE m.user_id=:user_id AND m.revoked_at IS NULL
              AND c.status='confirmed' AND c.purpose='planning'
              AND c.expires_at>UTC_TIMESTAMP(3)
            ORDER BY m.confirmed_at DESC LIMIT :limit
        """), {"user_id": user_id, "limit": limit}).scalars().all()
    return list(rows)
