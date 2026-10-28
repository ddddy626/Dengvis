"""Account-owned PC study jobs with leases and bounded result payloads."""

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import text

from .demo_sessions import session_engine


class StudyConflict(Exception):
    pass


def _json(value):
    return json.loads(value) if isinstance(value, str) else value


def _event(connection, user_id: int, job_id: int, event_type: str, summary: str) -> None:
    seq = connection.scalar(text("SELECT COALESCE(MAX(seq_no), 0) + 1 FROM agent_job_events WHERE job_id=:id"), {"id": job_id})
    connection.execute(text("""
        INSERT INTO agent_job_events (user_id, job_id, seq_no, event_type, summary)
        VALUES (:user_id, :job_id, :seq, :event_type, :summary)
    """), {"user_id": user_id, "job_id": job_id, "seq": seq, "event_type": event_type, "summary": summary[:500]})


def _present(connection, user_id: int, job_id: int) -> dict | None:
    row = connection.execute(text("""
        SELECT id, status, plan_json, created_at, updated_at FROM agent_jobs
        WHERE id=:job_id AND user_id=:user_id
    """), {"job_id": job_id, "user_id": user_id}).mappings().first()
    if not row:
        return None
    plan = _json(row["plan_json"])
    if plan.get("kind") != "pc_study":
        return None
    return {"jobId": row["id"], "status": row["status"], "query": plan["query"],
            "result": plan.get("result"), "createdAt": row["created_at"].isoformat() + "Z",
            "updatedAt": row["updated_at"].isoformat() + "Z"}


def get_study_job(user_id: int, job_id: int) -> dict | None:
    with session_engine().connect() as connection:
        return _present(connection, user_id, job_id)


def list_study_jobs(user_id: int) -> list[dict]:
    with session_engine().connect() as connection:
        ids = connection.execute(text("""
            SELECT id FROM agent_jobs WHERE user_id=:user_id
              AND JSON_UNQUOTE(JSON_EXTRACT(plan_json, '$.kind'))='pc_study'
            ORDER BY id DESC LIMIT 50
        """), {"user_id": user_id}).scalars().all()
        return [_present(connection, user_id, job_id) for job_id in ids]


def create_study_job(user_id: int, query: str, idempotency_key: str) -> dict:
    fingerprint = hashlib.sha256(query.strip().encode("utf-8")).hexdigest()
    with session_engine().begin() as connection:
        existing = connection.scalar(text("""
            SELECT id FROM agent_jobs WHERE user_id=:user_id AND idempotency_key=:key
        """), {"user_id": user_id, "key": idempotency_key})
        if existing:
            current = _present(connection, user_id, existing)
            if not current or _json(connection.scalar(text("SELECT plan_json FROM agent_jobs WHERE id=:id"), {"id": existing}))["fingerprint"] != fingerprint:
                raise StudyConflict("此幂等键已用于其他任务。")
            return current
        plan = {"kind": "pc_study", "query": query.strip(), "fingerprint": fingerprint, "maxResults": 3}
        job_id = connection.execute(text("""
            INSERT INTO agent_jobs (user_id, status, plan_json, budget_json, idempotency_key)
            VALUES (:user_id, 'waiting_pc', :plan, :budget, :key)
        """), {"user_id": user_id, "plan": json.dumps(plan, ensure_ascii=False),
               "budget": json.dumps({"maxSeconds": 600}), "key": idempotency_key}).lastrowid
        connection.execute(text("""
            INSERT INTO approval_requests (user_id, job_id, scope, payload_preview, decision, expires_at)
            VALUES (:user_id, :job_id, 'pc.study', :preview, 'allow_once', UTC_TIMESTAMP(3) + INTERVAL 1 DAY)
        """), {"user_id": user_id, "job_id": job_id, "preview": query[:1000]})
        _event(connection, user_id, job_id, "waiting_pc", "等待已配对 PC 领取本地学习任务。")
        return _present(connection, user_id, job_id)


def claim_study_job(user_id: int, device_id: int) -> dict | None:
    with session_engine().begin() as connection:
        connection.execute(text("""
            UPDATE agent_jobs SET status='waiting_pc', budget_json=JSON_REMOVE(budget_json, '$.claimedBy')
            WHERE user_id=:user_id AND status='running' AND updated_at<UTC_TIMESTAMP(3) - INTERVAL 10 MINUTE
              AND JSON_UNQUOTE(JSON_EXTRACT(plan_json, '$.kind'))='pc_study'
        """), {"user_id": user_id})
        row = connection.execute(text("""
            SELECT id, plan_json FROM agent_jobs
            WHERE user_id=:user_id AND status='waiting_pc'
              AND JSON_UNQUOTE(JSON_EXTRACT(plan_json, '$.kind'))='pc_study'
            ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED
        """), {"user_id": user_id}).mappings().first()
        if not row:
            return None
        connection.execute(text("""
            UPDATE agent_jobs SET status='running', budget_json=JSON_SET(budget_json, '$.claimedBy', :device_id)
            WHERE id=:job_id
        """), {"job_id": row["id"], "device_id": device_id})
        _event(connection, user_id, row["id"], "pc_claimed", "已配对 PC 领取任务，开始本地检索。")
        plan = _json(row["plan_json"])
        return {"jobId": row["id"], "query": plan["query"], "maxResults": plan["maxResults"]}


def complete_study_job(user_id: int, device_id: int, job_id: int, outcome: dict) -> dict | None:
    with session_engine().begin() as connection:
        row = connection.execute(text("""
            SELECT status, plan_json, budget_json FROM agent_jobs
            WHERE id=:job_id AND user_id=:user_id FOR UPDATE
        """), {"job_id": job_id, "user_id": user_id}).mappings().first()
        if not row or _json(row["plan_json"]).get("kind") != "pc_study":
            return None
        if row["status"] != "running" or _json(row["budget_json"]).get("claimedBy") != device_id:
            raise StudyConflict("任务已取消、已完成，或由另一台设备领取。")
        plan = _json(row["plan_json"])
        plan["result"] = outcome
        status = "succeeded" if outcome["success"] else "failed"
        connection.execute(text("UPDATE agent_jobs SET status=:status, plan_json=:plan WHERE id=:job_id"),
                           {"status": status, "plan": json.dumps(plan, ensure_ascii=False), "job_id": job_id})
        _event(connection, user_id, job_id, "pc_completed" if outcome["success"] else "pc_failed",
               "本地检索已完成。" if outcome["success"] else "本地检索失败，可查看原因并重试。")
        return _present(connection, user_id, job_id)


def retry_study_job(user_id: int, job_id: int) -> dict | None:
    with session_engine().begin() as connection:
        row = connection.execute(text("""
            SELECT status, plan_json FROM agent_jobs WHERE id=:job_id AND user_id=:user_id FOR UPDATE
        """), {"job_id": job_id, "user_id": user_id}).mappings().first()
        if not row or _json(row["plan_json"]).get("kind") != "pc_study":
            return None
        if row["status"] != "failed":
            raise StudyConflict("只有失败的学习任务可以重试。")
        plan = _json(row["plan_json"])
        plan.pop("result", None)
        connection.execute(text("""
            UPDATE agent_jobs SET status='waiting_pc', plan_json=:plan,
              budget_json=JSON_REMOVE(budget_json, '$.claimedBy') WHERE id=:job_id
        """), {"plan": json.dumps(plan, ensure_ascii=False), "job_id": job_id})
        _event(connection, user_id, job_id, "pc_retry", "用户请求重试，等待 PC 再次领取。")
        return _present(connection, user_id, job_id)
