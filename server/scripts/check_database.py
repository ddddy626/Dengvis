"""Read-only check of the manually applied Jarvis MySQL schema."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError


ROOT = Path(__file__).resolve().parents[2]
SQL_FILE = ROOT / "infra" / "sql" / "001_initial_schema.mysql.sql"
SYSTEM_SCHEMAS = {"mysql", "information_schema", "performance_schema", "sys"}


def expected_tables() -> set[str]:
    sql = SQL_FILE.read_text(encoding="utf-8")
    names = re.findall(r"^CREATE TABLE ([a-z_]+) \(", sql, re.MULTILINE)
    if len(names) != 18 or len(set(names)) != 18:
        raise ValueError("SQL 文件的建表清单不是预期的 18 张表。")
    return set(names)


def database_url() -> URL:
    load_dotenv(ROOT / ".env", override=False)
    values = {
        "host": os.getenv("JARVIS_DB_HOST", "").strip(),
        "port": os.getenv("JARVIS_DB_PORT", "").strip(),
        "database": os.getenv("JARVIS_DB_NAME", "").strip(),
        "username": os.getenv("JARVIS_DB_USER", "").strip(),
        "password": os.getenv("JARVIS_DB_PASSWORD", ""),
    }
    if any(not value for value in values.values()):
        raise ValueError("请在项目根目录 .env 中填写全部 JARVIS_DB_* 配置。")
    if values["database"].lower() in SYSTEM_SCHEMAS:
        raise ValueError("数据库名称指向 MySQL 系统库，请改为 Jarvis 专用库。")
    try:
        port = int(values["port"])
    except ValueError as exc:
        raise ValueError("JARVIS_DB_PORT 必须是有效端口号。") from exc
    if not 1 <= port <= 65535:
        raise ValueError("JARVIS_DB_PORT 必须介于 1 和 65535 之间。")
    return URL.create(
        "mysql+pymysql",
        username=values["username"],
        password=values["password"],
        host=values["host"],
        port=port,
        database=values["database"],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="核对 Jarvis SQL 文件及已建 MySQL 表名；不写入数据库。")
    parser.add_argument("--offline", action="store_true", help="只读取本地 SQL 文件，不连接数据库")
    args = parser.parse_args()

    try:
        expected = expected_tables()
    except (OSError, ValueError) as exc:
        print(f"本地 SQL 检查失败：{exc}", file=sys.stderr)
        return 2
    print(f"本地 SQL 列出 {len(expected)} 张表。")
    if args.offline:
        return 0

    try:
        url = database_url()
    except ValueError as exc:
        print(f"连接配置未就绪：{exc}", file=sys.stderr)
        return 2

    engine = create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5, "read_timeout": 5},
    )
    try:
        with engine.connect() as connection:
            selected = connection.scalar(text("SELECT DATABASE()"))
            if selected != url.database:
                print("实际连接的数据库与配置不一致；已停止检查。", file=sys.stderr)
                return 3
            existing = set(inspect(connection).get_table_names())
    except SQLAlchemyError as exc:
        # Do not print driver errors: URLs and credentials may appear in them.
        print(f"连接或查询失败（{type(exc).__name__}）。请检查服务、端口、库名和读取权限。", file=sys.stderr)
        return 3
    finally:
        engine.dispose()

    missing = sorted(expected - existing)
    print(f"已连接专用库 {url.database}；找到 {len(expected & existing)}/{len(expected)} 张目标表。")
    if missing:
        print("缺少表：" + ", ".join(missing), file=sys.stderr)
        return 1
    print("目标表名齐全；列、索引、外键及数据隔离仍待进一步核验。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
