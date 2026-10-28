"""Explicit account permission preferences. No grant bypasses plan approval."""

from sqlalchemy import text

from .demo_sessions import session_engine


def grant_life_preference(connection, user_id: int) -> None:
    # Serialize grants from distinct plans of the same account.
    connection.execute(text("SELECT id FROM users WHERE id=:id FOR UPDATE"), {"id": user_id}).scalar_one()
    active = connection.scalar(text("""
        SELECT id FROM permission_grants
        WHERE user_id=:id AND scope='life.write' AND data_source='internal_life'
          AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at>UTC_TIMESTAMP(3))
        LIMIT 1
    """), {"id": user_id})
    if not active:
        connection.execute(text("""
            INSERT INTO permission_grants (user_id, scope, data_source, grant_type)
            VALUES (:id, 'life.write', 'internal_life', 'allow_scope')
        """), {"id": user_id})


def list_permissions(user_id: int) -> list[dict]:
    with session_engine().connect() as connection:
        rows = connection.execute(text("""
            SELECT id, scope, data_source, grant_type, expires_at FROM permission_grants
            WHERE user_id=:id AND revoked_at IS NULL
              AND (expires_at IS NULL OR expires_at>UTC_TIMESTAMP(3))
            ORDER BY id DESC
        """), {"id": user_id}).mappings().all()
    return [{"id": row["id"], "scope": row["scope"], "dataSource": row["data_source"],
             "grantType": row["grant_type"],
             "expiresAt": row["expires_at"].isoformat() + "Z" if row["expires_at"] else None}
            for row in rows]


def revoke_permission(user_id: int, scope: str) -> bool:
    with session_engine().begin() as connection:
        changed = connection.execute(text("""
            UPDATE permission_grants SET revoked_at=UTC_TIMESTAMP(3)
            WHERE user_id=:id AND scope=:scope AND revoked_at IS NULL
        """), {"id": user_id, "scope": scope})
        return changed.rowcount > 0
