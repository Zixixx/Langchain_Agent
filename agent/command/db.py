from __future__ import annotations

"""DB 命令处理：导入 CSV/XLSX/XLS 表格、查看表结构、删除表和执行只读 SQL。"""

import json
from dataclasses import dataclass
from pathlib import Path

import typer

from agent.config import get_settings
from agent.db.local_database import LocalDatabase, SPREADSHEET_SUFFIXES


@dataclass(frozen=True)
class TableImportResult:
    """记录单个表格文件导入结果，目录导入时单文件失败不影响后续文件。"""

    path: Path
    table_name: str
    rows: int = 0
    error: str | None = None


def table_files(path: Path) -> list[Path]:
    """把用户输入的文件或目录解析为待导入的 CSV/XLSX/XLS 文件列表。"""
    if path.is_file():
        if path.suffix.lower() not in SPREADSHEET_SUFFIXES:
            raise ValueError(f"db-add only supports .csv, .xlsx and .xls files: {path}")
        return [path]
    if path.is_dir():
        return sorted(
            item
            for item in path.rglob("*")
            if item.is_file() and item.suffix.lower() in SPREADSHEET_SUFFIXES
        )
    raise ValueError(f"Path does not exist: {path}")


def table_name_from_path(path: Path) -> str:
    """表名取自文件名和扩展名。"""
    return path.name


def import_table_path(database: LocalDatabase, path: Path, if_exists: str = "replace") -> list[TableImportResult]:
    """把一个路径下的 CSV/XLSX/XLS 文件逐个导入数据库，并返回导入结果。"""
    if if_exists not in {"fail", "replace", "append"}:
        raise ValueError("if_exists must be one of: fail, replace, append")

    files = table_files(path)
    results = []
    for table_path in files:
        table_name = table_name_from_path(table_path)
        try:
            rows = database.import_table_file(table_path, table_name, if_exists=if_exists)
        except Exception as exc:
            results.append(TableImportResult(table_path, table_name, error=str(exc)))
            continue
        results.append(TableImportResult(table_path, table_name, rows=rows))
    return results


def add(path: Path, if_exists: str = "replace") -> str:
    """实现 db-add 命令：导入 CSV/XLSX/XLS 并打印每个表的导入行数。"""
    db = LocalDatabase(get_settings().table_db_path)
    try:
        results = import_table_path(db, path, if_exists=if_exists)
    except (RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    if not results:
        return f"No supported table files found: {path}"
    lines = []
    imported = 0
    failed = 0
    for result in results:
        if result.error:
            failed += 1
            lines.append(f"Failed {result.path}: {result.error}")
        else:
            imported += 1
            lines.append(f"Imported {result.rows} rows from {result.path} into table '{result.table_name}'")
    lines.append(f"Imported {imported} table file(s), failed {failed}.")
    return "\n".join(lines)


def list_tables(table_ref: str | None = None, all_flag: bool = False) -> str:
    """实现 db-list 命令：输出表结构统计信息。"""
    db = LocalDatabase(get_settings().table_db_path)
    if table_ref:
        table = resolve_table_ref(db, table_ref)
        return db_table_schema_text(db, table)
    return db_tables_text(db)


def show_tables(table_ref: str | None = None, all_flag: bool = False) -> str:
    """实现 db-show 命令：输出表内容。"""
    db = LocalDatabase(get_settings().table_db_path)
    if all_flag:
        rows = db.table_schema_rows()
        if not rows:
            return "No user tables found."
        return "\n\n".join(db_table_content_text(db, row["table"]) for row in rows)
    if not table_ref:
        raise ValueError("Usage: db-show <table|number> OR db-show -a")
    table = resolve_table_ref(db, table_ref)
    return db_table_content_text(db, table)


def delete(table_ref: str) -> str:
    """实现 db-delete 命令：按表名或 db-list 编号删除指定业务表。"""
    db = LocalDatabase(get_settings().table_db_path)
    table = resolve_table_ref(db, table_ref)
    db.drop_table(table)
    return f"Deleted table: {table}"


def delete_all() -> str:
    """实现 db-delete -a 命令：删除业务数据库中的全部用户表。"""
    db = LocalDatabase(get_settings().table_db_path)
    deleted = db.drop_all_user_tables()
    return f"Deleted all database tables: {deleted} table(s)."


def query(sql: str, limit: int = 100) -> str:
    """实现 db-query 命令：执行只读 SQL 并以 JSON 输出结果。"""
    db = LocalDatabase(get_settings().table_db_path)
    result = db.run_readonly_query(sql, limit=limit)
    return json.dumps(result, ensure_ascii=False, indent=2)


def db_tables_text(database: LocalDatabase) -> str:
    """把业务数据库表结构格式化成带编号的列表。"""
    rows = database.table_schema_rows()
    if not rows:
        return "No user tables found."
    lines = ["Database tables:"]
    for index, row in enumerate(rows, start=1):
        lines.append(f"{index}. table={row['table']}")
        for column in row["columns"]:
            flags = []
            if column["primary_key"]:
                flags.append("PRIMARY KEY")
            if column["not_null"]:
                flags.append("NOT NULL")
            suffix = f" {' '.join(flags)}" if flags else ""
            lines.append(f"   - {column['name']} {column['type']}{suffix}")
    return "\n".join(lines)


def db_table_content_text(database: LocalDatabase, table: str) -> str:
    """把某个表的内容格式化输出。"""
    rows = database.table_rows(table)
    if not rows:
        return f"Table: {table}\n(empty)"
    lines = [f"Table: {table}", json.dumps(rows, ensure_ascii=False, indent=2)]
    return "\n".join(lines)


def db_table_schema_text(database: LocalDatabase, table: str) -> str:
    """把某个业务表结构格式化成概览文本。"""
    rows = database.table_schema_rows()
    for index, row in enumerate(rows, start=1):
        if row["table"] != table:
            continue
        lines = [f"{index}. table={row['table']}"]
        for column in row["columns"]:
            flags = []
            if column["primary_key"]:
                flags.append("PRIMARY KEY")
            if column["not_null"]:
                flags.append("NOT NULL")
            suffix = f" {' '.join(flags)}" if flags else ""
            lines.append(f"   - {column['name']} {column['type']}{suffix}")
        return "\n".join(lines)
    raise ValueError(f"Table does not exist: {table}")


def resolve_table_ref(database: LocalDatabase, ref: str) -> str:
    """把参数解析为表名。"""
    rows = database.table_schema_rows()
    table_names = [row["table"] for row in rows]
    if ref.isdigit():
        index = int(ref)
        if 1 <= index <= len(table_names):
            return table_names[index - 1]
        if ref in table_names:
            return ref
        raise ValueError(f"Table number or name does not exist: {ref}")
    if ref not in table_names:
        raise ValueError(f"Table does not exist: {ref}")
    return ref
