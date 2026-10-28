"""Guarded version registration for a manually created Jarvis schema."""

from __future__ import annotations

import argparse
import hashlib
import sys

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from server.scripts.check_database import ROOT, SQL_FILE, database_url
from server.scripts.verify_schema import actual_schema, compare, expected_schema


REVISION = "20261014_01"
SQL_SHA256 = "2ba86f807af4a67fe09abd770248cb882c80a78af9e8df32eb00ef90b5945196"


def main() -> int:
    parser = argparse.ArgumentParser(description="核对手工建好的 Jarvis 库，并可显式登记初始迁移版本。")
    parser.add_argument("--stamp", action="store_true", help="核对通过后登记版本；会写入 alembic_version")
    parser.add_argument(
        "--reviewed",
        action="store_true",
        help="确认已人工核对本工具未覆盖的默认值和检查约束表达式；须与 --stamp 同用",
    )
    args = parser.parse_args()
    if args.stamp != args.reviewed:
        print("版本登记需同时指定 --stamp --reviewed；普通核对请不带参数。", file=sys.stderr)
        return 2
    try:
        digest = hashlib.sha256(SQL_FILE.read_bytes()).hexdigest()
        if digest != SQL_SHA256:
            raise ValueError("初始 SQL 文件哈希已变化，不能登记旧基线。")
        expected = expected_schema()
        url = database_url()
    except (OSError, ValueError) as exc:
        print(f"准备检查失败：{exc}", file=sys.stderr)
        return 2

    engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5, "read_timeout": 5})
    try:
        with engine.connect() as connection:
            if connection.scalar(text("SELECT DATABASE()")) != url.database:
                print("实际连接的数据库与配置不一致。", file=sys.stderr)
                return 3
            actual = actual_schema(connection, url.database)
    except SQLAlchemyError as exc:
        print(f"元数据查询失败（{type(exc).__name__}）。", file=sys.stderr)
        return 3
    finally:
        engine.dispose()

    problems = compare(expected, actual)
    extra_tables = sorted(actual.keys() - expected.keys())
    if extra_tables:
        problems.append("目标库含有额外表：" + ", ".join(extra_tables))
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        print("结构未通过核对，未登记版本。", file=sys.stderr)
        return 1
    print("18 张业务表的可自动核对部分通过；默认值与 CHECK 表达式仍需人工复核。")
    if not args.stamp:
        print("当前为只读核对；没有登记迁移版本。")
        return 0

    try:
        config = Config(str(ROOT / "server" / "alembic.ini"))
        command.stamp(config, REVISION)
    except Exception as exc:
        # Avoid serialising SQLAlchemy exceptions that may contain connection details.
        print(f"版本登记失败（{type(exc).__name__}）。请先检查 alembic_version 状态。", file=sys.stderr)
        return 3
    print(f"已登记迁移版本 {REVISION}。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
