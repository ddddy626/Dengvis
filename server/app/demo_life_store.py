"""Transactional demo plans, approvals, and real task writes."""

import hashlib
import json
import re
from datetime import datetime, timezone

from sqlalchemy import text

from .demo_sessions import session_engine
from .life_contracts import LifeItemDraft, LifePlanCreate


class LifeConflict(Exception):
    pass


def _json(value):
    return json.loads(value) if isinstance(value, str) else value


def _utc(value: datetime | None) -> datetime | None:
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value else None


def _suggest_items(intent: str) -> list[LifeItemDraft]:
    match = re.search(r"提醒(?:我)?([^，,。；;]+)", intent)
    title = match.group(1).strip() if match else intent.strip()
    return [LifeItemDraft(kind="task", title=title[:255])]


def _event(connection, demo_session_id: int, job_id: int, event_type: str, summary: str) -> None:
    seq = connection.scalar(text("SELECT COALESCE(MAX(seq_no), 0) + 1 FROM agent_job_events WHERE job_id=:job_id"), {"job_id": job_id})
    connection.execute(text("""
        INSERT INTO agent_job_events (demo_session_id, job_id, seq_no, event_type, summary)
        VALUES (:demo_session_id, :job_id, :seq, :event_type, :summary)
    """), {"demo_session_id": demo_session_id, "job_id": job_id, "seq": seq, "event_type": event_type, "summary": summary[:500]})


def _present(connection, demo_session_id: int, job_id: int) -> dict | None:
    row = connection.execute(text("""
        SELECT j.id, j.status, j.plan_json, j.created_at, a.id AS approval_id,
               a.decision, a.expires_at
        FROM agent_jobs j JOIN approval_requests a ON a.job_id=j.id AND a.demo_session_id=j.demo_session_id
        WHERE j.id=:job_id AND j.demo_session_id=:demo_session_id
    """), {"job_id": job_id, "demo_session_id": demo_session_id}).mappings().first()
    if not row:
        return None
    plan = _json(row["plan_json"])
    return {
        "jobId": row["id"], "status": row["status"], "intent": plan["intent"],
        "items": plan["items"], "saved": plan.get("saved", []),
        "approval": {"id": row["approval_id"], "decision": row["decision"],
                     "scope": "life.write", "expiresAt": row["expires_at"].isoformat() + "Z"},
    }


def get_plan(demo_session_id: int, job_id: int) -> dict | None:
    with session_engine().connect() as connection:
        return _present(connection, demo_session_id, job_id)


def get_plan_by_key(demo_session_id: int, body: LifePlanCreate) -> dict | None:
    with session_engine().connect() as connection:
        row = connection.execute(text("""
            SELECT id, plan_json FROM agent_jobs WHERE demo_session_id=:demo_session_id AND idempotency_key=:key
        """), {"demo_session_id": demo_session_id, "key": body.idempotencyKey}).mappings().first()
        if not row:
            return None
        items = body.items or _suggest_items(body.intent)
        original = {"intent": body.intent.strip(), "items": [item.model_dump(mode="json", exclude_none=True) for item in items]}
        fingerprint = hashlib.sha256(json.dumps(original, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        if _json(row["plan_json"])["requestFingerprint"] != fingerprint:
            raise LifeConflict("此幂等键已用于其他草案。")
        return _present(connection, demo_session_id, row["id"])


def create_plan(demo_session_id: int, body: LifePlanCreate) -> dict:
    items = body.items or _suggest_items(body.intent)
    plan = {"intent": body.intent.strip(), "items": [item.model_dump(mode="json", exclude_none=True) for item in items]}
    fingerprint = hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    plan["requestFingerprint"] = fingerprint
    with session_engine().begin() as connection:
        existing = connection.scalar(text("""
            SELECT id FROM agent_jobs WHERE demo_session_id=:demo_session_id AND idempotency_key=:key
        """), {"demo_session_id": demo_session_id, "key": body.idempotencyKey})
        if existing:
            current = _present(connection, demo_session_id, existing)
            current_plan = connection.scalar(text("SELECT plan_json FROM agent_jobs WHERE id=:id"), {"id": existing})
            if _json(current_plan)["requestFingerprint"] != fingerprint:
                raise LifeConflict("此幂等键已用于其他草案。")
            return current
        job_id = connection.execute(text("""
            INSERT INTO agent_jobs (demo_session_id, status, plan_json, budget_json, idempotency_key)
            VALUES (:demo_session_id, 'waiting_approval', :plan, :budget, :key)
        """), {"demo_session_id": demo_session_id, "plan": json.dumps(plan, ensure_ascii=False),
               "budget": json.dumps({"maxSteps": 8, "maxSeconds": 30, "modelCost": 0}),
               "key": body.idempotencyKey}).lastrowid
        preview = "；".join(f"{item.kind}: {item.title}" for item in items)[:1000]
        connection.execute(text("""
            INSERT INTO approval_requests (demo_session_id, job_id, scope, payload_preview, decision, expires_at)
            VALUES (:demo_session_id, :job_id, 'life.write', :preview, 'pending', UTC_TIMESTAMP(3) + INTERVAL 15 MINUTE)
        """), {"demo_session_id": demo_session_id, "job_id": job_id, "preview": preview})
        _event(connection, demo_session_id, job_id, "draft_created", "已生成待确认的生活任务草案。")
        return _present(connection, demo_session_id, job_id)


def edit_plan(demo_session_id: int, job_id: int, items: list[LifeItemDraft]) -> dict | None:
    with session_engine().begin() as connection:
        row = connection.execute(text("""
            SELECT j.status, j.plan_json, a.decision, a.expires_at
            FROM agent_jobs j JOIN approval_requests a ON a.job_id=j.id AND a.demo_session_id=j.demo_session_id
            WHERE j.id=:job_id AND j.demo_session_id=:demo_session_id FOR UPDATE
        """), {"job_id": job_id, "demo_session_id": demo_session_id}).mappings().first()
        if not row:
            return None
        if row["status"] != "waiting_approval" or row["decision"] != "pending" or row["expires_at"] <= datetime.now(timezone.utc).replace(tzinfo=None):
            raise LifeConflict("草案已无法编辑，请重新创建。")
        plan = _json(row["plan_json"])
        plan["items"] = [item.model_dump(mode="json", exclude_none=True) for item in items]
        connection.execute(text("UPDATE agent_jobs SET plan_json=:plan WHERE id=:job_id"),
                           {"plan": json.dumps(plan, ensure_ascii=False), "job_id": job_id})
        preview = "；".join(f"{item.kind}: {item.title}" for item in items)[:1000]
        connection.execute(text("UPDATE approval_requests SET payload_preview=:preview WHERE job_id=:job_id AND demo_session_id=:demo_session_id"),
                           {"preview": preview, "job_id": job_id, "demo_session_id": demo_session_id})
        _event(connection, demo_session_id, job_id, "draft_edited", "用户修改了待确认的写入清单。")
        return _present(connection, demo_session_id, job_id)


def decide_plan(demo_session_id: int, job_id: int, decision: str) -> dict | None:
    with session_engine().begin() as connection:
        row = connection.execute(text("""
            SELECT j.status, j.plan_json, a.decision, a.expires_at
            FROM agent_jobs j JOIN approval_requests a ON a.job_id=j.id AND a.demo_session_id=j.demo_session_id
            WHERE j.id=:job_id AND j.demo_session_id=:demo_session_id FOR UPDATE
        """), {"job_id": job_id, "demo_session_id": demo_session_id}).mappings().first()
        if not row:
            return None
        if row["status"] in ("succeeded", "cancelled"):
            if row["decision"] == decision:
                return _present(connection, demo_session_id, job_id)
            raise LifeConflict("此草案已经处理，不能改变决定。")
        if row["status"] != "waiting_approval" or row["decision"] != "pending":
            raise LifeConflict("草案不在待授权状态。")
        if row["expires_at"] <= datetime.now(timezone.utc).replace(tzinfo=None):
            connection.execute(text("UPDATE approval_requests SET decision='expired' WHERE job_id=:job_id AND demo_session_id=:demo_session_id"),
                               {"job_id": job_id, "demo_session_id": demo_session_id})
            connection.execute(text("UPDATE agent_jobs SET status='cancelled' WHERE id=:job_id"), {"job_id": job_id})
            _event(connection, demo_session_id, job_id, "approval_expired", "授权已过期，未写入任何事项。")
            return _present(connection, demo_session_id, job_id)
        if decision == "deny":
            connection.execute(text("UPDATE approval_requests SET decision='deny' WHERE job_id=:job_id AND demo_session_id=:demo_session_id"),
                               {"job_id": job_id, "demo_session_id": demo_session_id})
            connection.execute(text("UPDATE agent_jobs SET status='cancelled' WHERE id=:job_id"), {"job_id": job_id})
            _event(connection, demo_session_id, job_id, "approval_denied", "用户拒绝了写入，未保存事项。")
            return _present(connection, demo_session_id, job_id)
        plan = _json(row["plan_json"])
        saved = []
        for raw in plan["items"]:
            item = LifeItemDraft.model_validate(raw)
            if item.kind == "task":
                item_id = connection.execute(text("""
                    INSERT INTO demo_tasks (demo_session_id, title, due_at, status)
                    VALUES (:demo_session_id, :title, :due_at, 'open')
                """), {"demo_session_id": demo_session_id, "title": item.title, "due_at": _utc(item.dueAt)}).lastrowid
            else:
                item_id = connection.execute(text("""
                    INSERT INTO demo_schedules (demo_session_id, title, starts_at, ends_at, status, source)
                    VALUES (:demo_session_id, :title, :starts_at, :ends_at, 'planned', 'jarvis_plan')
                """), {"demo_session_id": demo_session_id, "title": item.title, "starts_at": _utc(item.startsAt),
                       "ends_at": _utc(item.endsAt)}).lastrowid
            saved.append({"kind": item.kind, "id": item_id})
        plan["saved"] = saved
        connection.execute(text("UPDATE agent_jobs SET plan_json=:plan, status='succeeded' WHERE id=:job_id"),
                           {"plan": json.dumps(plan, ensure_ascii=False), "job_id": job_id})
        connection.execute(text("UPDATE approval_requests SET decision='allow_once' WHERE job_id=:job_id AND demo_session_id=:demo_session_id"),
                           {"job_id": job_id, "demo_session_id": demo_session_id})
        _event(connection, demo_session_id, job_id, "write_succeeded", f"已保存 {len(saved)} 个生活事项。")
        return _present(connection, demo_session_id, job_id)


def list_items(demo_session_id: int) -> dict:
    with session_engine().connect() as connection:
        tasks = connection.execute(text("""
            SELECT id, title, due_at, status FROM demo_tasks WHERE demo_session_id=:demo_session_id ORDER BY id DESC LIMIT 100
        """), {"demo_session_id": demo_session_id}).mappings().all()
        schedules = connection.execute(text("""
            SELECT id, title, starts_at, ends_at, status FROM demo_schedules WHERE demo_session_id=:demo_session_id ORDER BY starts_at DESC LIMIT 100
        """), {"demo_session_id": demo_session_id}).mappings().all()
    return {
        "tasks": [{"id": row["id"], "title": row["title"], "dueAt": row["due_at"].isoformat() + "Z" if row["due_at"] else None, "status": row["status"]} for row in tasks],
        "schedules": [{"id": row["id"], "title": row["title"], "startsAt": row["starts_at"].isoformat() + "Z", "endsAt": row["ends_at"].isoformat() + "Z", "status": row["status"]} for row in schedules],
    }
