"""Compare the manual MySQL schema with the initial checked-in DDL, read only."""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from server.scripts.check_database import SQL_FILE, database_url


TABLE_RE = re.compile(r"(?ms)^CREATE TABLE ([a-z_]+) \(\n(.*?)^\) ENGINE=InnoDB")
COLUMN_RE = re.compile(r"^  (`?[a-z_]+`?) (.+?) (NOT NULL|NULL)(?:\b|$)")
INDEX_RE = re.compile(r"^  (UNIQUE KEY|KEY) ([a-z_]+) \(([^)]+)\)")
FOREIGN_KEY_RE = re.compile(
    r"^  CONSTRAINT ([a-z_]+) FOREIGN KEY \(([^)]+)\) REFERENCES ([a-z_]+) \(([^)]+)\)"
)
CHECK_RE = re.compile(r"^  CONSTRAINT ([a-z_]+) CHECK \(")


def _names(raw: str) -> tuple[str, ...]:
    return tuple(item.strip().strip("`") for item in raw.split(","))


def expected_schema() -> dict[str, dict]:
    sql = SQL_FILE.read_text(encoding="utf-8")
    tables: dict[str, dict] = {}
    for match in TABLE_RE.finditer(sql):
        table_name, body = match.groups()
        columns: dict[str, tuple[str, str, str, bool]] = {}
        indexes: dict[str, tuple[tuple[str, ...], bool]] = {"PRIMARY": (("id",), True)}
        foreign_keys: dict[str, tuple[tuple[str, ...], str, tuple[str, ...]]] = {}
        checks: set[str] = set()
        for line in body.splitlines():
            column = COLUMN_RE.match(line)
            index = INDEX_RE.match(line)
            foreign_key = FOREIGN_KEY_RE.match(line)
            check = CHECK_RE.match(line)
            if column:
                name, type_spec, nullable = column.groups()
                name = name.strip("`")
                base_type = type_spec.split(" CHARACTER SET ")[0].split(" COLLATE ")[0].lower()
                columns[name] = (base_type, nullable, "auto_increment" if "AUTO_INCREMENT" in line else "", name == "id")
            elif index:
                kind, name, raw_columns = index.groups()
                indexes[name] = (_names(raw_columns), kind == "UNIQUE KEY")
            elif foreign_key:
                name, raw_columns, parent, raw_parent_columns = foreign_key.groups()
                foreign_keys[name] = (_names(raw_columns), parent, _names(raw_parent_columns))
            elif check:
                checks.add(check.group(1))
        tables[table_name] = {
            "columns": columns,
            "indexes": indexes,
            "foreign_keys": foreign_keys,
            "checks": checks,
        }
    if len(tables) != 18 or any(not spec["columns"] for spec in tables.values()):
        raise ValueError("初始 SQL 无法解析为 18 张完整业务表。")
    return tables


def actual_schema(connection, database: str) -> dict[str, dict]:
    params = {"database": database}
    table_rows = connection.execute(text("""
        SELECT TABLE_NAME, ENGINE, TABLE_COLLATION
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = :database AND TABLE_TYPE = 'BASE TABLE'
    """), params).mappings()
    tables = {
        row["TABLE_NAME"]: {
            "engine": row["ENGINE"],
            "collation": row["TABLE_COLLATION"],
            "columns": {}, "indexes": {}, "foreign_keys": {}, "checks": set(),
        }
        for row in table_rows
    }

    column_rows = connection.execute(text("""
        SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, EXTRA, COLUMN_KEY
        FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = :database
    """), params).mappings()
    for row in column_rows:
        table = tables.get(row["TABLE_NAME"])
        if table is not None:
            table["columns"][row["COLUMN_NAME"]] = (
                row["COLUMN_TYPE"].lower(),
                "NULL" if row["IS_NULLABLE"] == "YES" else "NOT NULL",
                "auto_increment" if "auto_increment" in row["EXTRA"].lower() else "",
                row["COLUMN_KEY"] == "PRI",
            )

    index_rows = connection.execute(text("""
        SELECT TABLE_NAME, INDEX_NAME, NON_UNIQUE, SEQ_IN_INDEX, COLUMN_NAME
        FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = :database
        ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX
    """), params).mappings()
    index_parts: dict[tuple[str, str], list[str]] = defaultdict(list)
    index_unique: dict[tuple[str, str], bool] = {}
    for row in index_rows:
        key = (row["TABLE_NAME"], row["INDEX_NAME"])
        index_parts[key].append(row["COLUMN_NAME"])
        index_unique[key] = row["NON_UNIQUE"] == 0
    for (table_name, name), columns in index_parts.items():
        if table_name in tables:
            tables[table_name]["indexes"][name] = (tuple(columns), index_unique[(table_name, name)])

    fk_rows = connection.execute(text("""
        SELECT TABLE_NAME, CONSTRAINT_NAME, COLUMN_NAME,
               REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME, ORDINAL_POSITION
        FROM information_schema.KEY_COLUMN_USAGE
        WHERE TABLE_SCHEMA = :database AND REFERENCED_TABLE_NAME IS NOT NULL
        ORDER BY TABLE_NAME, CONSTRAINT_NAME, ORDINAL_POSITION
    """), params).mappings()
    fk_parts: dict[tuple[str, str], list[tuple[str, str, str]]] = defaultdict(list)
    for row in fk_rows:
        fk_parts[(row["TABLE_NAME"], row["CONSTRAINT_NAME"])].append((
            row["COLUMN_NAME"], row["REFERENCED_TABLE_NAME"], row["REFERENCED_COLUMN_NAME"]
        ))
    for (table_name, name), parts in fk_parts.items():
        if table_name in tables:
            tables[table_name]["foreign_keys"][name] = (
                tuple(part[0] for part in parts), parts[0][1], tuple(part[2] for part in parts)
            )

    check_rows = connection.execute(text("""
        SELECT TABLE_NAME, CONSTRAINT_NAME
        FROM information_schema.TABLE_CONSTRAINTS
        WHERE TABLE_SCHEMA = :database AND CONSTRAINT_TYPE = 'CHECK'
    """), params).mappings()
    for row in check_rows:
        if row["TABLE_NAME"] in tables:
            tables[row["TABLE_NAME"]]["checks"].add(row["CONSTRAINT_NAME"])
    return tables


def compare(expected: dict[str, dict], actual: dict[str, dict]) -> list[str]:
    problems: list[str] = []
    for table_name, spec in expected.items():
        found = actual.get(table_name)
        if found is None:
            problems.append(f"缺少表 {table_name}")
            continue
        if found["engine"] != "InnoDB" or found["collation"] != "utf8mb4_0900_ai_ci":
            problems.append(f"{table_name}: 存储引擎或排序规则不符")
        for column_name, expected_column in spec["columns"].items():
            if found["columns"].get(column_name) != expected_column:
                problems.append(f"{table_name}.{column_name}: 列类型、空值或主键属性不符")
        extra_columns = sorted(found["columns"].keys() - spec["columns"].keys())
        if extra_columns:
            problems.append(f"{table_name}: 多出列 {', '.join(extra_columns)}")
        for index_name, expected_index in spec["indexes"].items():
            if found["indexes"].get(index_name) != expected_index:
                problems.append(f"{table_name}: 索引 {index_name} 不符")
        for fk_name, expected_fk in spec["foreign_keys"].items():
            if found["foreign_keys"].get(fk_name) != expected_fk:
                problems.append(f"{table_name}: 外键 {fk_name} 不符")
        for check_name in spec["checks"] - found["checks"]:
            problems.append(f"{table_name}: 缺少检查约束 {check_name}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="只读核对 MySQL 结构与初始 SQL。")
    parser.add_argument("--offline", action="store_true", help="只解析本地初始 SQL，不连接数据库")
    args = parser.parse_args()
    try:
        expected = expected_schema()
    except (OSError, ValueError) as exc:
        print(f"本地 SQL 解析失败：{exc}", file=sys.stderr)
        return 2
    print(f"已解析 {len(expected)} 张表、{sum(len(s['columns']) for s in expected.values())} 个列定义。")
    if args.offline:
        return 0
    try:
        url = database_url()
    except ValueError as exc:
        print(f"连接配置未就绪：{exc}", file=sys.stderr)
        return 2
    engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5, "read_timeout": 5})
    try:
        with engine.connect() as connection:
            selected = connection.scalar(text("SELECT DATABASE()"))
            if selected != url.database:
                print("实际连接的数据库与配置不一致。", file=sys.stderr)
                return 3
            actual = actual_schema(connection, url.database)
    except SQLAlchemyError as exc:
        print(f"元数据查询失败（{type(exc).__name__}）；请检查连接和读取权限。", file=sys.stderr)
        return 3
    finally:
        engine.dispose()
    problems = compare(expected, actual)
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        print(f"发现 {len(problems)} 项结构差异。", file=sys.stderr)
        return 1
    print("18 张表的列、类型、显式索引、外键和检查约束名称核对通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
