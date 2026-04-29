from __future__ import annotations

"""SQL 工具：只暴露 CSV 业务库的 schema 和只读查询能力。"""

import json

from langchain_core.tools import tool

from agent.config import Settings
from agent.db.local_database import LocalDatabase


def build_sql_tools(settings: Settings):
    """构造 Text-to-SQL 所需的表结构查看和只读查询工具。"""

    def db() -> LocalDatabase:
        """连接 csv.sqlite3，避免 Agent 直接访问记忆、依赖和 RAG 元数据表。"""
        return LocalDatabase(settings.csv_db_path)

    @tool
    def sql_database_schema() -> str:
        """Return SQLite database table names and column names for Text-to-SQL."""
        try:
            return db().schema_text()
        except Exception as exc:
            return f"sql_database_schema failed: {exc}"

    @tool
    def sql_readonly_query(sql: str, limit: int = 100) -> str:
        """Run a read-only SQLite SELECT/WITH query. Use sql_database_schema before writing SQL."""
        try:
            # 只读查询由 LocalDatabase 再做 SQL 类型校验和 LIMIT 包装。
            result = db().run_readonly_query(sql, limit=limit)
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as exc:
            return f"sql_readonly_query failed: {exc}"

    return [sql_database_schema, sql_readonly_query]
