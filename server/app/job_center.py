"""Owner-bound status and cancellation for persisted life jobs."""

import json

from sqlalchemy import text

from .demo_sessions import session_engine


class JobConflict(Exception):
    pass


def _owner(kind: str) -> str:
    if kind == "account":
        return "user_id"
    if kind == "demo":
        return "demo_session_id"
    raise ValueError("Invalid owner kind")


def list_jobs(kind: str, owner_id: int) -> list[dict]:
    owner = _owner(kind)
    with session_engine().connect() as connection:
        rows = connection.execute(text(f"""
            SELECT j.id, j.status, j.created_at, j.updated_at,
                   a.decision, a.expires_at, a.payload_preview,
                   (SELECT e.summary FROM agent_job_events e
                    WHERE e.job_id=j.id AND e.{owner}=:owner_id
                    ORDER BY e.seq_no DESC LIMIT 1) AS latest_event
            FROM agent_jobs j
            JOIN approval_requests a ON a.job_id=j.id AND a.{owner}=j.{owner}
            WHERE j.{owner}=:owner_id
            ORDER BY j.id DESC LIMIT 50
        """), {"owner_id": owner_id}).mappings().all()
    return [{"jobId": row["id"], "status": row["status"], "decision": row["decision"],
             "preview": row["payload_preview"], "latestEvent": row["latest_event"],
             "createdAt": row["created_at"].isoformat() + "Z",
             "updatedAt": row["updated_at"].isoformat() + "Z",
             "approvalExpiresAt": row["expires_at"].isoformat() + "Z"} for row in rows]


def job_events(kind: str, owner_id: int, job_id: int) -> list[dict] | None:
    owner = _owner(kind)
    with session_engine().connect() as connection:
        found = connection.scalar(text(f"SELECT id FROM agent_jobs WHERE id=:job_id AND {owner}=:owner_id"),
                                  {"job_id": job_id, "owner_id": owner_id})
        if not found:
            return None
        rows = connection.execute(text(f"""
            SELECT seq_no, event_type, summary, `timestamp` FROM agent_job_events
            WHERE job_id=:job_id AND {owner}=:owner_id ORDER BY seq_no
        """), {"job_id": job_id, "owner_id": owner_id}).mappings().all()
    return [{"seq": row["seq_no"], "type": row["event_type"], "summary": row["summary"],
             "timestamp": row["timestamp"].isoformat() + "Z"} for row in rows]


def cancel_job(kind: str, owner_id: int, job_id: int) -> bool | None:
    owner = _owner(kind)
    with session_engine().begin() as connection:
        row = connection.execute(text(f"""
            SELECT j.status, j.plan_json, a.decision FROM agent_jobs j
            JOIN approval_requests a ON a.job_id=j.id AND a.{owner}=j.{owner}
            WHERE j.id=:job_id AND j.{owner}=:owner_id FOR UPDATE
        """), {"job_id": job_id, "owner_id": owner_id}).mappings().first()
        if row is None:
            return None
        if row["status"] == "cancelled":
            return False
        plan = json.loads(row["plan_json"]) if isinstance(row["plan_json"], str) else row["plan_json"]
        is_study = plan.get("kind") == "pc_study"
        if row["status"] == "waiting_approval" and row["decision"] == "pending":
            connection.execute(text(f"UPDATE approval_requests SET decision='deny' WHERE job_id=:job_id AND {owner}=:owner_id"),
                               {"job_id": job_id, "owner_id": owner_id})
        elif not (kind == "account" and is_study and row["status"] in ("waiting_pc", "running", "failed")):
            raise JobConflict("此任务不能取消；已保存事项请在事项列表中取消。")
        connection.execute(text("UPDATE agent_jobs SET status='cancelled' WHERE id=:job_id"), {"job_id": job_id})
        seq = connection.scalar(text("SELECT COALESCE(MAX(seq_no), 0) + 1 FROM agent_job_events WHERE job_id=:job_id"),
                                {"job_id": job_id})
        connection.execute(text(f"""
            INSERT INTO agent_job_events ({owner}, job_id, seq_no, event_type, summary)
            VALUES (:owner_id, :job_id, :seq, 'cancelled_by_user', :summary)
        """), {"owner_id": owner_id, "job_id": job_id, "seq": seq,
               "summary": "用户取消本地学习任务。" if is_study else "用户取消草案，未写入事项。"})
        return True
