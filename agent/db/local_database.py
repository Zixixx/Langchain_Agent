from __future__ import annotations

"""SQLite 访问层：集中管理 Agent 状态、RAG 元数据和表格数据查询。"""

import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


SYSTEM_TABLE_PREFIX = "sqlite_"
SAFE_SELECT_RE = re.compile(r"^\s*(select|with)\b", re.IGNORECASE | re.DOTALL)
TABLE_TEXT_ENCODINGS = ("utf-8", "utf-8-sig", "gb18030", "gbk", "cp936", "big5", "latin-1")
SPREADSHEET_SUFFIXES = {".csv", ".xlsx", ".xls"}


def local_timestamp() -> str:
    """返回本机本地时区时间字符串，避免 SQLite CURRENT_TIMESTAMP 的 UTC 偏移。"""
    return datetime.now().astimezone().replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")


class LocalDatabase:
    """对 sqlite3 的薄封装，避免上层命令直接拼接数据库细节。"""

    def __init__(self, db_path: Path):
        """保存数据库路径，并确保父目录存在。"""
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        """创建 SQLite 连接，并开启项目需要的基础 PRAGMA。"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = MEMORY")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def initialize(self) -> None:
        """创建 agent.sqlite3 需要的记忆窗口和依赖申请表；重复调用是安全的。"""
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    session_id TEXT PRIMARY KEY,
                    title TEXT,
                    turn_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS chat_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    turn_index INTEGER NOT NULL,
                    user_input TEXT NOT NULL,
                    tool_calls_json TEXT NOT NULL DEFAULT '[]',
                    agent_output TEXT,
                    status TEXT NOT NULL DEFAULT 'success'
                        CHECK(status IN ('running', 'success', 'failed')),
                    error_message TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(session_id, turn_index),
                    FOREIGN KEY(session_id) REFERENCES chat_sessions(session_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_chat_turns_session_id_turn_index
                ON chat_turns(session_id, turn_index);

                CREATE TABLE IF NOT EXISTS dependency_requests (
                    session_id TEXT NOT NULL,
                    module_name TEXT NOT NULL,
                    package_name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending', 'installed', 'failed', 'ignored')),
                    error_message TEXT,
                    requested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(session_id, module_name),
                    FOREIGN KEY(session_id) REFERENCES chat_sessions(session_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_dependency_requests_module_name
                ON dependency_requests(module_name);
                """
            )

    def initialize_rag(self) -> None:
        """创建 rag.sqlite3 需要的 RAG 元数据表；向量本体仍由 Chroma 管理。"""
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS rag_libraries (
                    rag_id TEXT PRIMARY KEY,
                    title TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    rag_id TEXT NOT NULL DEFAULT 'default',
                    source TEXT NOT NULL,
                    title TEXT,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(rag_id, source),
                    FOREIGN KEY(rag_id) REFERENCES rag_libraries(rag_id)
                );

                CREATE TABLE IF NOT EXISTS rag_chunks (
                    id TEXT PRIMARY KEY,
                    rag_id TEXT NOT NULL DEFAULT 'default',
                    document_source TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(rag_id, document_source) REFERENCES documents(rag_id, source)
                );
                """
            )

    def import_table_file(self, table_path: Path, table_name: str, if_exists: str = "replace") -> int:
        """把 CSV/XLSX/XLS 表格文件导入指定 SQLite 表，并返回导入行数。"""
        if if_exists not in {"fail", "replace", "append"}:
            raise ValueError("if_exists must be one of: fail, replace, append")
        # pandas 负责 CSV/XLSX/XLS 表格类型推断和写入 SQLite；CSV 编码不确定时会尝试常见 Windows 编码。
        df = _read_table_file(table_path)
        with self.connect() as conn:
            df.to_sql(table_name, conn, if_exists=if_exists, index=False)
        return len(df)

    def drop_table(self, table_name: str) -> None:
        """删除 SQLite 表；表名会先加引号转义，避免特殊字符影响 SQL。"""
        with self.connect() as conn:
            existing = conn.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type = 'table' AND name = ? AND name NOT LIKE ?
                LIMIT 1
                """,
                (table_name, f"{SYSTEM_TABLE_PREFIX}%"),
            ).fetchone()
            if existing is None:
                raise ValueError(f"Table does not exist: {table_name}")
            conn.execute(f"DROP TABLE {_quote_identifier(table_name)}")

    def drop_all_user_tables(self) -> int:
        """删除 SQLite 库中的所有用户表，返回删除的表数量。"""
        with self.connect() as conn:
            tables = self._table_names(conn)
            for table in tables:
                conn.execute(f"DROP TABLE {_quote_identifier(table)}")
            return len(tables)

    def create_rag_library(self, rag_id: str, title: str | None = None) -> None:
        """创建或刷新一个 RAG 库记录。"""
        now = local_timestamp()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO rag_libraries(rag_id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(rag_id) DO UPDATE SET
                    title = COALESCE(excluded.title, rag_libraries.title),
                    updated_at = excluded.updated_at
                """,
                (rag_id, title or rag_id, now, now),
            )

    def rag_library_exists(self, rag_id: str) -> bool:
        """判断指定 RAG 库是否存在。"""
        with self.connect() as conn:
            row = conn.execute("SELECT 1 FROM rag_libraries WHERE rag_id = ? LIMIT 1", (rag_id,)).fetchone()
        return row is not None

    def list_rag_libraries(self) -> list[dict[str, Any]]:
        """列出所有 RAG 库，并附带文档和 chunk 数量。"""
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    l.rag_id,
                    l.title,
                    l.created_at,
                    l.updated_at,
                    COUNT(DISTINCT d.source) AS document_count,
                    COUNT(c.id) AS chunk_count
                FROM rag_libraries l
                LEFT JOIN documents d ON d.rag_id = l.rag_id
                LEFT JOIN rag_chunks c ON c.rag_id = d.rag_id AND c.document_source = d.source
                GROUP BY l.rag_id, l.title, l.created_at, l.updated_at
                ORDER BY l.created_at ASC, l.rag_id ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_rag_library(self, rag_id: str) -> int:
        """删除一个 RAG 库及其文档元数据，返回删除的 chunk 数。"""
        with self.connect() as conn:
            chunk_cursor = conn.execute("DELETE FROM rag_chunks WHERE rag_id = ?", (rag_id,))
            conn.execute("DELETE FROM documents WHERE rag_id = ?", (rag_id,))
            conn.execute("DELETE FROM rag_libraries WHERE rag_id = ?", (rag_id,))
            return chunk_cursor.rowcount

    def delete_all_rag_libraries(self) -> int:
        """删除所有 RAG 库及其文档元数据，返回删除的 chunk 数。"""
        with self.connect() as conn:
            chunk_cursor = conn.execute("DELETE FROM rag_chunks")
            conn.execute("DELETE FROM documents")
            conn.execute("DELETE FROM rag_libraries")
            return chunk_cursor.rowcount

    def save_document(self, source: str, title: str | None, content: str, rag_id: str = "default") -> None:
        """保存或更新一篇 RAG 文档的结构化元数据。"""
        now = local_timestamp()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO rag_libraries(rag_id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(rag_id) DO UPDATE SET updated_at = excluded.updated_at
                """,
                (rag_id, rag_id, now, now),
            )
            conn.execute(
                """
                INSERT INTO documents(rag_id, source, title, content, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(rag_id, source) DO UPDATE SET
                    title = excluded.title,
                    content = excluded.content,
                    updated_at = excluded.updated_at
                """,
                (rag_id, source, title, content, now, now),
            )

    def append_document_content(self, source: str, title: str | None, content: str, rag_id: str = "default") -> None:
        """向指定 RAG source 的文档内容后追加文本；不存在时创建文档。"""
        now = local_timestamp()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO rag_libraries(rag_id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(rag_id) DO UPDATE SET updated_at = excluded.updated_at
                """,
                (rag_id, rag_id, now, now),
            )
            conn.execute(
                """
                INSERT INTO documents(rag_id, source, title, content, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(rag_id, source) DO UPDATE SET
                    title = COALESCE(excluded.title, documents.title),
                    content = documents.content || char(10) || char(10) || excluded.content,
                    updated_at = excluded.updated_at
                """,
                (rag_id, source, title, content, now, now),
            )

    def replace_chunks(self, source: str, chunks: list[tuple[str, int, str]], rag_id: str = "default") -> None:
        """替换指定 RAG source 的 chunk 元数据。"""
        now = local_timestamp()
        with self.connect() as conn:
            conn.execute("DELETE FROM rag_chunks WHERE rag_id = ? AND document_source = ?", (rag_id, source))
            conn.executemany(
                """
                INSERT INTO rag_chunks(id, rag_id, document_source, chunk_index, content, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [(chunk_id, rag_id, source, index, content, now) for chunk_id, index, content in chunks],
            )

    def append_chunks(self, source: str, chunks: list[tuple[str, int, str]], rag_id: str = "default") -> None:
        """向指定 RAG source 追加 chunk 元数据。"""
        now = local_timestamp()
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO rag_chunks(id, rag_id, document_source, chunk_index, content, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [(chunk_id, rag_id, source, index, content, now) for chunk_id, index, content in chunks],
            )

    def count_chunks(self, source: str, rag_id: str = "default") -> int:
        """统计指定 RAG source 已有的 chunk 数量，供 append 计算后续序号。"""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM rag_chunks WHERE rag_id = ? AND document_source = ?",
                (rag_id, source),
            ).fetchone()
        return int(row["count"])

    def document_exists(self, source: str, rag_id: str = "default") -> bool:
        """判断某个 RAG source 是否已经导入过。"""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM documents WHERE rag_id = ? AND source = ? LIMIT 1",
                (rag_id, source),
            ).fetchone()
        return row is not None

    def delete_document(self, source: str, rag_id: str = "default") -> tuple[int, int]:
        """删除某个 RAG source 的文档和 chunk 元数据，返回 document/chunk 删除数。"""
        with self.connect() as conn:
            chunk_cursor = conn.execute(
                "DELETE FROM rag_chunks WHERE rag_id = ? AND document_source = ?",
                (rag_id, source),
            )
            document_cursor = conn.execute("DELETE FROM documents WHERE rag_id = ? AND source = ?", (rag_id, source))
            return document_cursor.rowcount, chunk_cursor.rowcount

    def delete_all_documents(self, rag_id: str | None = None) -> int:
        """删除全部 RAG 文档和 chunk 元数据，返回删除的 chunk 数量。"""
        with self.connect() as conn:
            if rag_id:
                chunk_cursor = conn.execute("DELETE FROM rag_chunks WHERE rag_id = ?", (rag_id,))
                conn.execute("DELETE FROM documents WHERE rag_id = ?", (rag_id,))
                conn.execute(
                    "UPDATE rag_libraries SET updated_at = ? WHERE rag_id = ?",
                    (local_timestamp(), rag_id),
                )
            else:
                chunk_cursor = conn.execute("DELETE FROM rag_chunks")
                conn.execute("DELETE FROM documents")
            return chunk_cursor.rowcount

    def list_documents(self, rag_id: str | None = None) -> list[dict[str, Any]]:
        """列出所有 RAG 文档及其 chunk 数量。"""
        with self.connect() as conn:
            if rag_id:
                rows = conn.execute(
                    """
                    SELECT
                        d.rag_id,
                        d.source,
                        d.title,
                        d.created_at,
                        d.updated_at,
                        COUNT(c.id) AS chunk_count
                    FROM documents d
                    LEFT JOIN rag_chunks c ON c.rag_id = d.rag_id AND c.document_source = d.source
                    WHERE d.rag_id = ?
                    GROUP BY d.rag_id, d.source, d.title, d.created_at, d.updated_at
                    ORDER BY d.created_at ASC, d.id ASC
                    """,
                    (rag_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT
                        d.rag_id,
                        d.source,
                        d.title,
                        d.created_at,
                        d.updated_at,
                        COUNT(c.id) AS chunk_count
                    FROM documents d
                    LEFT JOIN rag_chunks c ON c.rag_id = d.rag_id AND c.document_source = d.source
                    GROUP BY d.rag_id, d.source, d.title, d.created_at, d.updated_at
                    ORDER BY d.created_at ASC, d.id ASC
                    """
                ).fetchall()
        return [dict(row) for row in rows]

    def create_chat_session(self, session_id: str, title: str | None = None) -> None:
        """创建或刷新一个记忆窗口记录。"""
        now = local_timestamp()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_sessions(session_id, title, turn_count, created_at, updated_at)
                VALUES (?, ?, 0, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    title = COALESCE(excluded.title, chat_sessions.title),
                    updated_at = excluded.updated_at
                """,
                (session_id, title or session_id, now, now),
            )

    def chat_session_exists(self, session_id: str) -> bool:
        """检查记忆窗口是否存在。"""
        with self.connect() as conn:
            row = conn.execute("SELECT 1 FROM chat_sessions WHERE session_id = ? LIMIT 1", (session_id,)).fetchone()
        return row is not None

    def list_chat_sessions(self) -> list[dict[str, Any]]:
        """列出所有记忆窗口，并附带总轮数。"""
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT session_id, title, turn_count, created_at, updated_at
                FROM chat_sessions
                ORDER BY created_at ASC, session_id ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def add_chat_turn(
        self,
        session_id: str,
        user_input: str,
        agent_output: str | None,
        tool_calls_json: str = "[]",
        status: str = "success",
        error_message: str = "",
    ) -> int:
        """保存一轮任务记录，并同步窗口总轮数。"""
        if status not in {"running", "success", "failed"}:
            raise ValueError("status must be 'running', 'success' or 'failed'")
        now = local_timestamp()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_sessions(session_id, title, turn_count, created_at, updated_at)
                VALUES (?, ?, 0, ?, ?)
                ON CONFLICT(session_id) DO NOTHING
                """,
                (session_id, session_id, now, now),
            )
            row = conn.execute("SELECT turn_count FROM chat_sessions WHERE session_id = ?", (session_id,)).fetchone()
            turn_index = int(row["turn_count"]) + 1
            cursor = conn.execute(
                """
                INSERT INTO chat_turns(
                    session_id, turn_index, user_input, tool_calls_json,
                    agent_output, status, error_message, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    turn_index,
                    user_input,
                    tool_calls_json or "[]",
                    agent_output,
                    status,
                    error_message,
                    now,
                    now,
                ),
            )
            conn.execute(
                "UPDATE chat_sessions SET turn_count = ?, updated_at = ? WHERE session_id = ?",
                (turn_index, now, session_id),
            )
            return int(cursor.lastrowid)

    def load_chat_turns(self, session_id: str, newest_first: bool = True) -> list[dict[str, Any]]:
        """读取指定窗口的所有轮次；默认按轮数从大到小返回。"""
        order = "DESC" if newest_first else "ASC"
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    id, session_id, turn_index, user_input, tool_calls_json,
                    agent_output, status, error_message, created_at, updated_at
                FROM chat_turns
                WHERE session_id = ?
                ORDER BY turn_index {order}
                """,
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def clear_chat_turns(self, session_id: str) -> dict[str, int]:
        """清空指定窗口的轮次记录和依赖申请，并返回分项删除数量。"""
        now = local_timestamp()
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM chat_turns WHERE session_id = ?", (session_id,))
            dependency_cursor = conn.execute("DELETE FROM dependency_requests WHERE session_id = ?", (session_id,))
            conn.execute(
                "UPDATE chat_sessions SET turn_count = 0, updated_at = ? WHERE session_id = ?",
                (now, session_id),
            )
            return {"turns": cursor.rowcount, "dependencies": dependency_cursor.rowcount}

    def clear_all_chat_turns(self) -> dict[str, int]:
        """清空所有窗口的轮次记录和依赖申请，并返回分项删除数量。"""
        now = local_timestamp()
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM chat_turns")
            dependency_cursor = conn.execute("DELETE FROM dependency_requests")
            conn.execute("UPDATE chat_sessions SET turn_count = 0, updated_at = ?", (now,))
            return {"turns": cursor.rowcount, "dependencies": dependency_cursor.rowcount}

    def delete_chat_session(self, session_id: str) -> dict[str, int]:
        """删除窗口、轮次和依赖申请，并返回分项删除数量。"""
        with self.connect() as conn:
            turn_count = conn.execute(
                "SELECT COUNT(*) AS count FROM chat_turns WHERE session_id = ?",
                (session_id,),
            ).fetchone()["count"]
            dependency_count = conn.execute(
                "SELECT COUNT(*) AS count FROM dependency_requests WHERE session_id = ?",
                (session_id,),
            ).fetchone()["count"]
            session_cursor = conn.execute("DELETE FROM chat_sessions WHERE session_id = ?", (session_id,))
            return {
                "turns": int(turn_count),
                "dependencies": int(dependency_count),
                "sessions": session_cursor.rowcount,
            }

    def delete_all_chat_sessions(self) -> dict[str, int]:
        """删除所有记忆窗口、轮次和依赖请求，并返回分项删除数量。"""
        with self.connect() as conn:
            turn_count = conn.execute("SELECT COUNT(*) AS count FROM chat_turns").fetchone()["count"]
            dependency_count = conn.execute("SELECT COUNT(*) AS count FROM dependency_requests").fetchone()["count"]
            session_cursor = conn.execute("DELETE FROM chat_sessions")
            return {
                "turns": int(turn_count),
                "dependencies": int(dependency_count),
                "sessions": session_cursor.rowcount,
            }

    def add_dependency_request(
        self,
        session_id: str,
        module_name: str,
        package_name: str,
        error_message: str = "",
    ) -> None:
        """记录缺失依赖申请；同一窗口同一模块会更新为 pending。"""
        now = local_timestamp()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_sessions(session_id, title, turn_count, created_at, updated_at)
                VALUES (?, ?, 0, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET updated_at = excluded.updated_at
                """,
                (session_id, session_id, now, now),
            )
            conn.execute(
                """
                INSERT INTO dependency_requests(
                    session_id, module_name, package_name, error_message, requested_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, module_name) DO UPDATE SET
                    package_name = excluded.package_name,
                    status = 'pending',
                    error_message = excluded.error_message,
                    updated_at = excluded.updated_at
                """,
                (session_id, module_name, package_name, error_message, now, now),
            )

    def list_dependency_requests(self, session_id: str, status: str | None = None) -> list[dict[str, Any]]:
        """列出指定窗口的依赖申请，可按状态过滤。"""
        with self.connect() as conn:
            if status:
                rows = conn.execute(
                    """
                    SELECT session_id, module_name, package_name, status, requested_at, updated_at
                    FROM dependency_requests
                    WHERE session_id = ? AND status = ?
                    ORDER BY updated_at DESC
                    """,
                    (session_id, status),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT session_id, module_name, package_name, status, requested_at, updated_at
                    FROM dependency_requests
                    WHERE session_id = ?
                    ORDER BY updated_at DESC
                    """,
                    (session_id,),
                ).fetchall()
        return [dict(row) for row in rows]

    def list_all_dependency_requests(self, status: str | None = None) -> list[dict[str, Any]]:
        """列出所有窗口的依赖申请，可按状态过滤。"""
        with self.connect() as conn:
            if status:
                rows = conn.execute(
                    """
                    SELECT session_id, module_name, package_name, status, requested_at, updated_at
                    FROM dependency_requests
                    WHERE status = ?
                    ORDER BY session_id, updated_at DESC
                    """,
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT session_id, module_name, package_name, status, requested_at, updated_at
                    FROM dependency_requests
                    ORDER BY session_id, updated_at DESC
                    """
                ).fetchall()
        return [dict(row) for row in rows]

    def update_dependency_status(
        self,
        session_id: str,
        module_name: str,
        status: str,
        error_message: str = "",
    ) -> None:
        """更新依赖申请状态，例如 failed 或 ignored。"""
        now = local_timestamp()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE dependency_requests
                SET status = ?, error_message = ?, updated_at = ?
                WHERE session_id = ? AND module_name = ?
                """,
                (status, error_message, now, session_id, module_name),
            )

    def delete_dependency_request(self, session_id: str, module_name: str) -> int:
        """删除指定窗口中的某个模块依赖申请。"""
        with self.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM dependency_requests WHERE session_id = ? AND module_name = ?",
                (session_id, module_name),
            )
            return cursor.rowcount

    def delete_dependency_requests_by_session(self, session_id: str) -> int:
        """删除某个窗口的全部依赖申请。"""
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM dependency_requests WHERE session_id = ?", (session_id,))
            return cursor.rowcount

    def delete_dependency_requests_by_module(self, module_name: str) -> int:
        """删除所有窗口中同一模块名的依赖申请。"""
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM dependency_requests WHERE module_name = ?", (module_name,))
            return cursor.rowcount

    def schema_text(self) -> str:
        """把用户表结构格式化为 Text-to-SQL 可读的文本。"""
        with self.connect() as conn:
            tables = self._table_names(conn)
            if not tables:
                return "No user tables found."
            blocks = []
            for table in tables:
                columns = conn.execute(f"PRAGMA table_info({_quote_identifier(table)})").fetchall()
                col_lines = [
                    f"- {row['name']} {row['type'] or 'TEXT'}"
                    + (" PRIMARY KEY" if row["pk"] else "")
                    + (" NOT NULL" if row["notnull"] else "")
                    for row in columns
                ]
                blocks.append(f"Table: {table}\nSQL table name: {_quote_identifier(table)}\nColumns:\n" + "\n".join(col_lines))
            return "\n\n".join(blocks)

    def table_schema_rows(self) -> list[dict[str, Any]]:
        """返回用户表及其字段列表，供 db-list 编号展示和按编号删除使用。"""
        with self.connect() as conn:
            rows = []
            for table in self._table_names(conn):
                columns = conn.execute(f"PRAGMA table_info({_quote_identifier(table)})").fetchall()
                rows.append(
                    {
                        "table": table,
                        "columns": [
                            {
                                "name": column["name"],
                                "type": column["type"] or "TEXT",
                                "primary_key": bool(column["pk"]),
                                "not_null": bool(column["notnull"]),
                            }
                            for column in columns
                        ],
                    }
                )
        return rows

    def table_rows(self, table_name: str, limit: int | None = None) -> list[dict[str, Any]]:
        """读取某个用户表的内容；limit 为 None 时读取全部。"""
        with self.connect() as conn:
            if table_name not in self._table_names(conn):
                raise ValueError(f"Table does not exist: {table_name}")
            sql = f"SELECT * FROM {_quote_identifier(table_name)}"
            if limit is None:
                rows = conn.execute(sql).fetchall()
            else:
                rows = conn.execute(f"{sql} LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def run_readonly_query(self, sql: str, limit: int = 100) -> dict[str, Any]:
        """执行只读 SELECT/WITH 查询，并用外层 LIMIT 控制返回行数。"""
        if not SAFE_SELECT_RE.match(sql):
            raise ValueError("Only SELECT or WITH queries are allowed.")
        if ";" in sql.strip().rstrip(";"):
            raise ValueError("Only one SQL statement is allowed.")
        sql = sql.strip().rstrip(";")
        with self.connect() as conn:
            conn.execute("PRAGMA query_only = ON")
            sql = _quote_known_table_names(sql, self._table_names(conn))
            # 外层 LIMIT 兜底，避免一次查询返回过多行。
            cursor = conn.execute(f"SELECT * FROM ({sql}) LIMIT ?", (limit,))
            rows = [dict(row) for row in cursor.fetchall()]
            return {"row_count": len(rows), "rows": rows}

    def _table_names(self, conn: sqlite3.Connection) -> list[str]:
        """读取非 sqlite_ 开头的用户表名。"""
        rows = conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE ?
            ORDER BY name
            """,
            (f"{SYSTEM_TABLE_PREFIX}%",),
        ).fetchall()
        return [row["name"] for row in rows]


def _read_table_csv_with_encoding_fallback(csv_path: Path) -> pd.DataFrame:
    """按常见编码尝试读取 CSV，兼容 Windows 上常见的 GBK/GB18030 文件。"""
    last_error: Exception | None = None
    for encoding in TABLE_TEXT_ENCODINGS:
        try:
            return pd.read_csv(csv_path, encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error:
        raise last_error
    return pd.read_csv(csv_path)


def _read_table_file(table_path: Path) -> pd.DataFrame:
    """按扩展名读取 CSV/XLSX/XLS 表格文件。"""
    suffix = table_path.suffix.lower()
    if suffix == ".csv":
        return _read_table_csv_with_encoding_fallback(table_path)
    if suffix == ".xlsx":
        return pd.read_excel(table_path, engine="openpyxl")
    if suffix == ".xls":
        try:
            return pd.read_excel(table_path, engine="xlrd")
        except ImportError as exc:
            raise RuntimeError("Reading .xls for db-add requires xlrd. Install it with: deps-install xlrd") from exc
    raise ValueError(f"Unsupported table file type: {table_path}")


def _quote_identifier(identifier: str) -> str:
    """给任意表名加双引号，并转义表名内部的双引号。"""
    return '"' + identifier.replace('"', '""') + '"'


def _quote_known_table_names(sql: str, table_names: list[str]) -> str:
    """把 SQL 中未加引号的已知业务表名自动改成 SQLite 引号表名。"""
    candidates = sorted(table_names, key=len, reverse=True)
    if not candidates:
        return sql

    result: list[str] = []
    index = 0
    in_single_quote = False
    in_double_quote = False
    while index < len(sql):
        char = sql[index]
        if char == "'" and not in_double_quote:
            result.append(char)
            if in_single_quote and index + 1 < len(sql) and sql[index + 1] == "'":
                result.append(sql[index + 1])
                index += 2
                continue
            in_single_quote = not in_single_quote
            index += 1
            continue
        if char == '"' and not in_single_quote:
            result.append(char)
            if in_double_quote and index + 1 < len(sql) and sql[index + 1] == '"':
                result.append(sql[index + 1])
                index += 2
                continue
            in_double_quote = not in_double_quote
            index += 1
            continue

        if not in_single_quote and not in_double_quote:
            matched = _match_table_name_at(sql, index, candidates)
            if matched:
                result.append(_quote_identifier(matched))
                index += len(matched)
                continue

        result.append(char)
        index += 1
    return "".join(result)


def _match_table_name_at(sql: str, index: int, table_names: list[str]) -> str | None:
    """在指定位置匹配一个完整表名，避免把更长标识符的一部分误替换。"""
    for table_name in table_names:
        if not sql.startswith(table_name, index):
            continue
        before = sql[index - 1] if index > 0 else ""
        after_index = index + len(table_name)
        after = sql[after_index] if after_index < len(sql) else ""
        if _is_identifier_char(before) or _is_identifier_char(after):
            continue
        return table_name
    return None


def _is_identifier_char(char: str) -> bool:
    """判断字符是否像 SQL 标识符的一部分，用于自动引用表名时做边界判断。"""
    return bool(char) and (char.isalnum() or char == "_")
