"""One-time PC pairing and revocable worker tokens."""

from alembic import op


revision = "20261017_03"
down_revision = "20261017_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE pc_pair_requests (
          id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
          user_id BIGINT UNSIGNED NOT NULL,
          code_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
          expires_at DATETIME(3) NOT NULL,
          consumed_at DATETIME(3) NULL,
          created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
          UNIQUE KEY uq_pc_pair_code (code_hash),
          KEY ix_pc_pair_user (user_id, expires_at),
          CONSTRAINT fk_pc_pair_user FOREIGN KEY (user_id) REFERENCES users (id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """)
    op.execute("""
        CREATE TABLE pc_worker_tokens (
          id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
          user_id BIGINT UNSIGNED NOT NULL,
          device_id BIGINT UNSIGNED NOT NULL,
          token_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
          expires_at DATETIME(3) NOT NULL,
          revoked_at DATETIME(3) NULL,
          created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
          UNIQUE KEY uq_pc_worker_token (token_hash),
          KEY ix_pc_worker_user (user_id, revoked_at),
          CONSTRAINT fk_pc_worker_token_user FOREIGN KEY (user_id) REFERENCES users (id),
          CONSTRAINT fk_pc_worker_token_device FOREIGN KEY (device_id) REFERENCES devices (id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """)


def downgrade() -> None:
    raise RuntimeError("PC 配对记录可能包含仍有效的设备令牌；请先审查与撤销，不自动删除。")
