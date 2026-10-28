"""Transactional account plans, approvals, and real task writes."""

import hashlib
import json
import re
from datetime import datetime, timezone

from sqlalchemy import text

from .demo_sessions import session_engine
from .life_contracts import LifeItemDraft, LifePlanCreate
from .memory_store import planning_memories
from .permission_store import grant_life_preference


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


def _memory_suggestions(user_id: int, intent: str) -> tuple[list[LifeItemDraft], list[str]]:
    if not ("安排今天" in intent or "我的习惯" in intent):
        return [], []
    suggestions = []
    used = []
    for memory in planning_memories(user_id):
        match = re.search(r"提醒(?:我)?([^，,。；;]+)", memory)
        if not match:
            continue
        title = match.group(1).strip()[:255]
        if title and title not in {item.title for item in suggestions}:
            suggestions.append(LifeItemDraft(kind="task", title=title))
            used.append(memory)
        if len(suggestions) >= 4:
            break
    return suggestions, used


def _event(connection, user_id: int, job_id: int, event_type: str, summary: str) -> None:
    seq = connection.scalar(text("SELECT COALESCE(MAX(seq_no), 0) + 1 FROM agent_job_events WHERE job_id=:job_id"), {"job_id": job_id})
    connection.execute(text("""
        INSERT INTO agent_job_events (user_id, job_id, seq_no, event_type, summary)
        VALUES (:user_id, :job_id, :seq, :event_type, :summary)
    """), {"user_id": user_id, "job_id": job_id, "seq": seq, "event_type": event_type, "summary": summary[:500]})


def _present(connection, user_id: int, job_id: int) -> dict | None:
    row = connection.execute(text("""
        SELECT j.id, j.status, j.plan_json, j.created_at, a.id AS approval_id,
               a.decision, a.expires_at
        FROM agent_jobs j JOIN approval_requests a ON a.job_id=j.id AND a.user_id=j.user_id
        WHERE j.id=:job_id AND j.user_id=:user_id
    """), {"job_id": job_id, "user_id": user_id}).mappings().first()
    if not row:
        return None
    plan = _json(row["plan_json"])
    return {
        "jobId": row["id"], "status": row["status"], "intent": plan["intent"],
        "items": plan["items"], "saved": plan.get("saved", []), "memoryUsed": plan.get("memoryUsed", []),
        "approval": {"id": row["approval_id"], "decision": row["decision"],
                     "scope": "life.write", "expiresAt": row["expires_at"].isoformat() + "Z"},
    }


def get_plan(user_id: int, job_id: int) -> dict | None:
    with session_engine().connect() as connection:
        return _present(connection, user_id, job_id)


def get_plan_by_key(user_id: int, body: LifePlanCreate) -> dict | None:
    with session_engine().connect() as connection:
        row = connection.execute(text("""
            SELECT id, plan_json FROM agent_jobs WHERE user_id=:user_id AND idempotency_key=:key
        """), {"user_id": user_id, "key": body.idempotencyKey}).mappings().first()
        if not row:
            return None
        items = body.items or _suggest_items(body.intent)
        original = {"intent": body.intent.strip(), "items": [item.model_dump(mode="json", exclude_none=True) for item in items]}
        fingerprint = hashlib.sha256(json.dumps(original, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        if _json(row["plan_json"])["requestFingerprint"] != fingerprint:
            raise LifeConflict("此幂等键已用于其他草案。")
        return _present(connection, user_id, row["id"])


def create_plan(user_id: int, body: LifePlanCreate) -> dict:
    items = body.items or _suggest_items(body.intent)
    plan = {"intent": body.intent.strip(), "items": [item.model_dump(mode="json", exclude_none=True) for item in items]}
    fingerprint = hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    plan["requestFingerprint"] = fingerprint
    if body.items is None:
        suggestions, used = _memory_suggestions(user_id, body.intent)
        existing_titles = {item.title for item in items}
        plan["items"].extend(item.model_dump(mode="json", exclude_none=True) for item in suggestions
                             if item.title not in existing_titles)
        plan["items"] = plan["items"][:8]
        plan["memoryUsed"] = used
    with session_engine().begin() as connection:
        existing = connection.scalar(text("""
            SELECT id FROM agent_jobs WHERE user_id=:user_id AND idempotency_key=:key
        """), {"user_id": user_id, "key": body.idempotencyKey})
        if existing:
            current = _present(connection, user_id, existing)
            current_plan = connection.scalar(text("SELECT plan_json FROM agent_jobs WHERE id=:id"), {"id": existing})
            if _json(current_plan)["requestFingerprint"] != fingerprint:
                raise LifeConflict("此幂等键已用于其他草案。")
            return current
        job_id = connection.execute(text("""
            INSERT INTO agent_jobs (user_id, status, plan_json, budget_json, idempotency_key)
            VALUES (:user_id, 'waiting_approval', :plan, :budget, :key)
        """), {"user_id": user_id, "plan": json.dumps(plan, ensure_ascii=False),
               "budget": json.dumps({"maxSteps": 8, "maxSeconds": 30, "modelCost": 0}),
               "key": body.idempotencyKey}).lastrowid
        preview = "；".join(f"{item['kind']}: {item['title']}" for item in plan["items"])[:1000]
        connection.execute(text("""
            INSERT INTO approval_requests (user_id, job_id, scope, payload_preview, decision, expires_at)
            VALUES (:user_id, :job_id, 'life.write', :preview, 'pending', UTC_TIMESTAMP(3) + INTERVAL 15 MINUTE)
        """), {"user_id": user_id, "job_id": job_id, "preview": preview})
        _event(connection, user_id, job_id, "draft_created", "已生成待确认的生活任务草案。")
        return _present(connection, user_id, job_id)


def edit_plan(user_id: int, job_id: int, items: list[LifeItemDraft]) -> dict | None:
    with session_engine().begin() as connection:
        row = connection.execute(text("""
            SELECT j.status, j.plan_json, a.decision, a.expires_at
            FROM agent_jobs j JOIN approval_requests a ON a.job_id=j.id AND a.user_id=j.user_id
            WHERE j.id=:job_id AND j.user_id=:user_id FOR UPDATE
        """), {"job_id": job_id, "user_id": user_id}).mappings().first()
        if not row:
            return None
        if row["status"] != "waiting_approval" or row["decision"] != "pending" or row["expires_at"] <= datetime.now(timezone.utc).replace(tzinfo=None):
            raise LifeConflict("草案已无法编辑，请重新创建。")
        plan = _json(row["plan_json"])
        plan["items"] = [item.model_dump(mode="json", exclude_none=True) for item in items]
        connection.execute(text("UPDATE agent_jobs SET plan_json=:plan WHERE id=:job_id"),
                           {"plan": json.dumps(plan, ensure_ascii=False), "job_id": job_id})
        preview = "；".join(f"{item.kind}: {item.title}" for item in items)[:1000]
        connection.execute(text("UPDATE approval_requests SET payload_preview=:preview WHERE job_id=:job_id AND user_id=:user_id"),
                           {"preview": preview, "job_id": job_id, "user_id": user_id})
        _event(connection, user_id, job_id, "draft_edited", "用户修改了待确认的写入清单。")
        return _present(connection, user_id, job_id)


def decide_plan(user_id: int, job_id: int, decision: str) -> dict | None:
    with session_engine().begin() as connection:
        row = connection.execute(text("""
            SELECT j.status, j.plan_json, a.decision, a.expires_at
            FROM agent_jobs j JOIN approval_requests a ON a.job_id=j.id AND a.user_id=j.user_id
            WHERE j.id=:job_id AND j.user_id=:user_id FOR UPDATE
        """), {"job_id": job_id, "user_id": user_id}).mappings().first()
        if not row:
            return None
        if row["status"] in ("succeeded", "cancelled"):
            if row["decision"] == decision:
                return _present(connection, user_id, job_id)
            raise LifeConflict("此草案已经处理，不能改变决定。")
        if row["status"] != "waiting_approval" or row["decision"] != "pending":
            raise LifeConflict("草案不在待授权状态。")
        if row["expires_at"] <= datetime.now(timezone.utc).replace(tzinfo=None):
            connection.execute(text("UPDATE approval_requests SET decision='expired' WHERE job_id=:job_id AND user_id=:user_id"),
                               {"job_id": job_id, "user_id": user_id})
            connection.execute(text("UPDATE agent_jobs SET status='cancelled' WHERE id=:job_id"), {"job_id": job_id})
            _event(connection, user_id, job_id, "approval_expired", "授权已过期，未写入任何事项。")
            return _present(connection, user_id, job_id)
        if decision == "deny":
            connection.execute(text("UPDATE approval_requests SET decision='deny' WHERE job_id=:job_id AND user_id=:user_id"),
                               {"job_id": job_id, "user_id": user_id})
            connection.execute(text("UPDATE agent_jobs SET status='cancelled' WHERE id=:job_id"), {"job_id": job_id})
            _event(connection, user_id, job_id, "approval_denied", "用户拒绝了写入，未保存事项。")
            return _present(connection, user_id, job_id)
        plan = _json(row["plan_json"])
        saved = []
        for raw in plan["items"]:
            item = LifeItemDraft.model_validate(raw)
            if item.kind == "task":
                item_id = connection.execute(text("""
                    INSERT INTO tasks (user_id, title, due_at, status)
                    VALUES (:user_id, :title, :due_at, 'open')
                """), {"user_id": user_id, "title": item.title, "due_at": _utc(item.dueAt)}).lastrowid
            else:
                item_id = connection.execute(text("""
                    INSERT INTO schedules (user_id, title, starts_at, ends_at, status, source)
                    VALUES (:user_id, :title, :starts_at, :ends_at, 'planned', 'jarvis_plan')
                """), {"user_id": user_id, "title": item.title, "starts_at": _utc(item.startsAt),
                       "ends_at": _utc(item.endsAt)}).lastrowid
            saved.append({"kind": item.kind, "id": item_id})
        plan["saved"] = saved
        connection.execute(text("UPDATE agent_jobs SET plan_json=:plan, status='succeeded' WHERE id=:job_id"),
                           {"plan": json.dumps(plan, ensure_ascii=False), "job_id": job_id})
        if decision == "allow_scope":
            grant_life_preference(connection, user_id)
        connection.execute(text("UPDATE approval_requests SET decision=:decision WHERE job_id=:job_id AND user_id=:user_id"),
                           {"decision": decision, "job_id": job_id, "user_id": user_id})
        _event(connection, user_id, job_id, "write_succeeded", f"已保存 {len(saved)} 个生活事项。")
        return _present(connection, user_id, job_id)


def list_items(user_id: int) -> dict:
    with session_engine().connect() as connection:
        tasks = connection.execute(text("""
            SELECT id, title, due_at, status FROM tasks WHERE user_id=:user_id ORDER BY id DESC LIMIT 100
        """), {"user_id": user_id}).mappings().all()
        schedules = connection.execute(text("""
            SELECT id, title, starts_at, ends_at, status FROM schedules WHERE user_id=:user_id ORDER BY starts_at DESC LIMIT 100
        """), {"user_id": user_id}).mappings().all()
    return {
        "tasks": [{"id": row["id"], "title": row["title"], "dueAt": row["due_at"].isoformat() + "Z" if row["due_at"] else None, "status": row["status"]} for row in tasks],
        "schedules": [{"id": row["id"], "title": row["title"], "startsAt": row["starts_at"].isoformat() + "Z", "endsAt": row["ends_at"].isoformat() + "Z", "status": row["status"]} for row in schedules],
    }
