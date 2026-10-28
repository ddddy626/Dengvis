"""Owner-bound life item changes and morning reports from recorded sources."""

import json
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import text

from .demo_sessions import session_engine
from .life_contracts import LifeItemUpdate


class LifeItemConflict(Exception):
    pass


def _owner(owner_kind: str, item_kind: str) -> tuple[str, str]:
    if owner_kind not in ("account", "demo") or item_kind not in ("task", "schedule"):
        raise LifeItemConflict("不支持的事项类型。")
    column = "user_id" if owner_kind == "account" else "demo_session_id"
    table = ("" if owner_kind == "account" else "demo_") + ("tasks" if item_kind == "task" else "schedules")
    return column, table


def _utc(value: datetime | None) -> datetime | None:
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value else None


def update_item(owner_kind: str, owner_id: int, item_kind: str, item_id: int, body: LifeItemUpdate) -> dict | None:
    column, table = _owner(owner_kind, item_kind)
    if not body.title.strip():
        raise LifeItemConflict("事项标题不能为空。")
    if item_kind == "task":
        if body.status not in ("open", "done", "cancelled") or body.startsAt or body.endsAt:
            raise LifeItemConflict("待办状态或时间无效。")
    elif body.status not in ("planned", "completed", "cancelled") or body.dueAt or not body.startsAt or not body.endsAt or body.endsAt <= body.startsAt:
        raise LifeItemConflict("日程状态或时间无效。")
    with session_engine().begin() as connection:
        row = connection.execute(text(f"SELECT id FROM {table} WHERE id=:item_id AND {column}=:owner_id FOR UPDATE"),
                                 {"item_id": item_id, "owner_id": owner_id}).first()
        if not row:
            return None
        if item_kind == "task":
            connection.execute(text(f"""
                UPDATE {table} SET title=:title, due_at=:due_at, status=:status WHERE id=:item_id AND {column}=:owner_id
            """), {"title": body.title.strip(), "due_at": _utc(body.dueAt), "status": body.status,
                   "item_id": item_id, "owner_id": owner_id})
        else:
            connection.execute(text(f"""
                UPDATE {table} SET title=:title, starts_at=:starts_at, ends_at=:ends_at, status=:status
                WHERE id=:item_id AND {column}=:owner_id
            """), {"title": body.title.strip(), "starts_at": _utc(body.startsAt), "ends_at": _utc(body.endsAt),
                   "status": body.status, "item_id": item_id, "owner_id": owner_id})
        return {"id": item_id, "kind": item_kind, "title": body.title.strip(), "status": body.status}


def morning_report(owner_kind: str, owner_id: int, report_date: date) -> dict:
    column, task_table = _owner(owner_kind, "task")
    _, schedule_table = _owner(owner_kind, "schedule")
    local_zone = timezone(timedelta(hours=8))
    start = datetime.combine(report_date, time.min, local_zone).astimezone(timezone.utc).replace(tzinfo=None)
    end = datetime.combine(date.fromordinal(report_date.toordinal() + 1), time.min, local_zone).astimezone(timezone.utc).replace(tzinfo=None)
    with session_engine().begin() as connection:
        tasks = connection.execute(text(f"""
            SELECT id, title, due_at, status FROM {task_table}
            WHERE {column}=:owner_id AND status <> 'cancelled' AND (due_at IS NULL OR due_at < :end)
            ORDER BY due_at, id LIMIT 100
        """), {"owner_id": owner_id, "end": end}).mappings().all()
        schedules = connection.execute(text(f"""
            SELECT id, title, starts_at, ends_at, status FROM {schedule_table}
            WHERE {column}=:owner_id AND status <> 'cancelled' AND starts_at >= :start AND starts_at < :end
            ORDER BY starts_at, id LIMIT 100
        """), {"owner_id": owner_id, "start": start, "end": end}).mappings().all()
        sleep = {"status": "not_authorized", "source": "health_summaries", "minutes": None}
        if owner_kind == "account":
            grant = connection.scalar(text("""
                SELECT id FROM permission_grants WHERE user_id=:owner_id AND scope='health.sleep.read'
                AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at > UTC_TIMESTAMP(3))
                LIMIT 1
            """), {"owner_id": owner_id})
            if grant:
                row = connection.execute(text("""
                    SELECT sleep_minutes, source_status FROM health_summaries
                    WHERE user_id=:owner_id AND record_date=:report_date ORDER BY id DESC LIMIT 1
                """), {"owner_id": owner_id, "report_date": report_date}).mappings().first()
                if not row:
                    sleep["status"] = "not_synced"
                elif row["source_status"] == "failed":
                    sleep["status"] = "failed"
                elif row["sleep_minutes"] is not None:
                    sleep["status"] = "available"
                    sleep["minutes"] = row["sleep_minutes"]
                else:
                    sleep["status"] = "not_synced"
        task_data = [{"id": row["id"], "title": row["title"], "status": row["status"],
                      "dueAt": row["due_at"].isoformat() + "Z" if row["due_at"] else None} for row in tasks]
        schedule_data = [{"id": row["id"], "title": row["title"], "status": row["status"],
                          "startsAt": row["starts_at"].isoformat() + "Z",
                          "endsAt": row["ends_at"].isoformat() + "Z"} for row in schedules]
        content = {"date": report_date.isoformat(), "tasks": task_data, "schedules": schedule_data, "sleep": sleep,
                   "sources": {"tasks": "internal", "schedules": "internal", "sleep": sleep["status"]}}
        if owner_kind == "account":
            connection.execute(text("""
                INSERT INTO morning_reports (user_id, report_date, data_sources_json, content_json, status, generated_at)
                VALUES (:owner_id, :report_date, :sources, :content, 'ready', UTC_TIMESTAMP(3))
                ON DUPLICATE KEY UPDATE data_sources_json=VALUES(data_sources_json), content_json=VALUES(content_json),
                                        status='ready', generated_at=UTC_TIMESTAMP(3)
            """), {"owner_id": owner_id, "report_date": report_date,
                   "sources": json.dumps(content["sources"]), "content": json.dumps(content, ensure_ascii=False)})
        return content
