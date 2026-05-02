from __future__ import annotations

"""DB 命令处理：导入 CSV、查看表结构、删除表和执行只读 SQL。"""

import json
import re
from pathlib import Path

import typer

from agent.config import get_settings
from agent.db.local_database import LocalDatabase


def csv_files(path: Path) -> list[Path]:
    """把用户输入的文件或目录解析为待导入的 CSV 文件列表。"""
    if path.is_file():
        if path.suffix.lower() != ".csv":
            raise ValueError(f"db-add only supports .csv files: {path}")
        return [path]
    if path.is_dir():
        return sorted(item for item in path.rglob("*.csv") if item.is_file())
    raise ValueError(f"Path does not exist: {path}")


def table_name_from_csv_path(path: Path) -> str:
    """根据 CSV 文件名生成安全的 SQLite 表名，不包含 .csv 扩展名。"""
    table_name = re.sub(r"\W+", "_", path.stem).strip("_")
    if not table_name:
        table_name = "csv_table"
    if table_name[0].isdigit():
        table_name = f"csv_{table_name}"
    return table_name


def import_csv_path(database: LocalDatabase, path: Path, if_exists: str = "replace") -> list[tuple[Path, str, int]]:
    """把一个路径下的 CSV 文件逐个导入数据库，并返回导入结果。"""
    files = csv_files(path)
    results = []
    for csv_path in files:
        table_name = table_name_from_csv_path(csv_path)
        rows = database.import_csv(csv_path, table_name, if_exists=if_exists)
        results.append((csv_path, table_name, rows))
    return results


def add(path: Path, if_exists: str = "replace") -> None:
    """实现 db-add 命令：导入 CSV 并打印每个表的导入行数。"""
    db = LocalDatabase(get_settings().csv_db_path)
    try:
        results = import_csv_path(db, path, if_exists=if_exists)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if not results:
        typer.echo(f"No CSV files found: {path}")
        return
    for csv_path, table_name, rows in results:
        typer.echo(f"Imported {rows} rows from {csv_path} into table '{table_name}'")


def list_tables() -> None:
    """实现 db-list 命令：输出 CSV 数据库的表结构。"""
    db = LocalDatabase(get_settings().csv_db_path)
    typer.echo(db.schema_text())


def delete(table: str) -> None:
    """实现 db-delete 命令：删除指定业务表。"""
    db = LocalDatabase(get_settings().csv_db_path)
    db.drop_table(table)
    typer.echo(f"Deleted table: {table}")


def query(sql: str, limit: int = 100) -> None:
    """实现 db-query 命令：执行只读 SQL 并以 JSON 输出结果。"""
    db = LocalDatabase(get_settings().csv_db_path)
    result = db.run_readonly_query(sql, limit=limit)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
