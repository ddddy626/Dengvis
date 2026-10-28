"""Initial 18-table schema from the reviewed SQL file.

Run on a dedicated empty database only. Existing manually created schemas must
be verified before they are marked as this revision.
"""

from pathlib import Path
import hashlib
import re

from alembic import context, op
from sqlalchemy import inspect


revision = "20261014_01"
down_revision = None
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parents[3] / "infra" / "sql" / "001_initial_schema.mysql.sql"
SQL_SHA256 = "2ba86f807af4a67fe09abd770248cb882c80a78af9e8df32eb00ef90b5945196"


def _statements() -> list[str]:
    sql_bytes = SQL_FILE.read_bytes()
    if hashlib.sha256(sql_bytes).hexdigest() != SQL_SHA256:
        raise RuntimeError("初始 SQL 文件与迁移基线不一致，请先审查差异。")
    sql = sql_bytes.decode("utf-8")
    # This fixed DDL contains no semicolons inside strings or procedural blocks.
    ddl = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    statements = [part.strip() for part in ddl.split(";") if part.strip()]
    if len(statements) != 18 or any(not re.match(r"^CREATE TABLE [a-z_]+ \(", item) for item in statements):
        raise RuntimeError("初始 SQL 文件不是预期的 18 条建表语句。")
    return statements


def upgrade() -> None:
    statements = _statements()
    if not context.is_offline_mode():
        existing = set(inspect(op.get_bind()).get_table_names())
        target = {re.match(r"^CREATE TABLE ([a-z_]+)", item).group(1) for item in statements}
        occupied = sorted(existing & target)
        if occupied:
            raise RuntimeError("目标库已有 Jarvis 表，已拒绝重复建表：" + ", ".join(occupied))
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    raise RuntimeError("初始结构包含用户数据；请先制定备份和逐表清理方案，再单独编写回退迁移。")
