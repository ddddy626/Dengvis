"""Isolated life items for short-lived Web demo sessions."""

from alembic import op


revision = "20261017_02"
down_revision = "20261014_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE demo_tasks (
          id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
          demo_session_id BIGINT UNSIGNED NOT NULL,
          title VARCHAR(255) NOT NULL,
          due_at DATETIME(3) NULL,
          priority VARCHAR(24) NOT NULL DEFAULT 'normal',
          status VARCHAR(32) NOT NULL DEFAULT 'open',
          created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
          updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
          KEY ix_demo_tasks_session_status (demo_session_id, status),
          CONSTRAINT fk_demo_tasks_session FOREIGN KEY (demo_session_id) REFERENCES demo_sessions (id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """)
    op.execute("""
        CREATE TABLE demo_schedules (
          id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
          demo_session_id BIGINT UNSIGNED NOT NULL,
          title VARCHAR(255) NOT NULL,
          starts_at DATETIME(3) NOT NULL,
          ends_at DATETIME(3) NOT NULL,
          status VARCHAR(32) NOT NULL,
          source VARCHAR(120) NOT NULL,
          created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
          updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
          KEY ix_demo_schedules_session_starts (demo_session_id, starts_at),
          CONSTRAINT fk_demo_schedules_session FOREIGN KEY (demo_session_id) REFERENCES demo_sessions (id),
          CONSTRAINT ck_demo_schedules_time CHECK (ends_at > starts_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """)


def downgrade() -> None:
    raise RuntimeError("演示事项可能包含数据；回退前请先导出并审查，不自动删除表。")
