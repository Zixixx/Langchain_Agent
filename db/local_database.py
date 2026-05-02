from __future__ import annotations

"""SQLite 访问层：集中管理 RAG 元数据、记忆窗口、依赖申请和 CSV 表查询。"""

import re
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd


SYSTEM_TABLE_PREFIX = "sqlite_"
SAFE_SELECT_RE = re.compile(r"^\s*(select|with)\b", re.IGNORECASE | re.DOTALL)
CSV_ENCODINGS = ("utf-8", "utf-8-sig", "gb18030", "gbk", "cp936", "big5", "latin-1")


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
        """创建 agent.sqlite3 需要的系统表；重复调用是安全的。"""
        with self.connect() as conn:
            # documents/rag_chunks 保存 RAG 元数据；向量本体由 Chroma 管理。
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL UNIQUE,
                    title TEXT,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS rag_chunks (
                    id TEXT PRIMARY KEY,
                    document_source TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(document_source) REFERENCES documents(source)
                );

                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS chat_sessions (
                    session_id TEXT PRIMARY KEY,
                    title TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id_id
                ON chat_messages(session_id, id);

                CREATE TABLE IF NOT EXISTS dependency_requests (
                    session_id TEXT NOT NULL,
                    module_name TEXT NOT NULL,
                    package_name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending', 'installed', 'failed', 'ignored')),
                    error_message TEXT,
                    requested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(session_id, module_name)
                );

                CREATE INDEX IF NOT EXISTS idx_dependency_requests_module_name
                ON dependency_requests(module_name);
                """
            )
            self._migrate_dependency_requests(conn)

    def import_csv(self, csv_path: Path, table_name: str, if_exists: str = "replace") -> int:
        """使用 pandas 把 CSV 导入指定表，并返回导入行数。"""
        if if_exists not in {"fail", "replace", "append"}:
            raise ValueError("if_exists must be one of: fail, replace, append")
        _validate_identifier(table_name)
        # pandas 负责 CSV 类型推断和写入 SQLite；编码不确定时尝试常见 Windows 编码。
        df = _read_csv_with_encoding_fallback(csv_path)
        with self.connect() as conn:
            df.to_sql(table_name, conn, if_exists=if_exists, index=False)
        return len(df)

    def drop_table(self, table_name: str) -> None:
        """删除用户 CSV 表；会拒绝非法表名和不存在的表。"""
        _validate_identifier(table_name)
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

    def save_document(self, source: str, title: str | None, content: str) -> None:
        """保存或更新一篇 RAG 文档的结构化元数据。"""
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO documents(source, title, content)
                VALUES (?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                    title = excluded.title,
                    content = excluded.content,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (source, title, content),
            )

    def replace_chunks(self, source: str, chunks: list[tuple[str, int, str]]) -> None:
        """替换指定 RAG source 的 chunk 元数据。"""
        with self.connect() as conn:
            conn.execute("DELETE FROM rag_chunks WHERE document_source = ?", (source,))
            conn.executemany(
                "INSERT INTO rag_chunks(id, document_source, chunk_index, content) VALUES (?, ?, ?, ?)",
                [(chunk_id, source, index, content) for chunk_id, index, content in chunks],
            )

    def document_exists(self, source: str) -> bool:
        """判断某个 RAG source 是否已经导入过。"""
        with self.connect() as conn:
            row = conn.execute("SELECT 1 FROM documents WHERE source = ? LIMIT 1", (source,)).fetchone()
        return row is not None

    def delete_document(self, source: str) -> int:
        """删除某个 RAG source 的文档和 chunk 元数据，返回删除 chunk 数。"""
        with self.connect() as conn:
            chunk_cursor = conn.execute("DELETE FROM rag_chunks WHERE document_source = ?", (source,))
            conn.execute("DELETE FROM documents WHERE source = ?", (source,))
            return chunk_cursor.rowcount

    def list_documents(self) -> list[dict[str, Any]]:
        """列出所有 RAG 文档及其 chunk 数量。"""
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    d.source,
                    d.title,
                    d.created_at,
                    d.updated_at,
                    COUNT(c.id) AS chunk_count
                FROM documents d
                LEFT JOIN rag_chunks c ON c.document_source = d.source
                GROUP BY d.source, d.title, d.created_at, d.updated_at
                ORDER BY d.updated_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def add_chat_message(self, session_id: str, role: str, content: str) -> None:
        """追加一条用户或助手消息，并自动刷新窗口更新时间。"""
        if role not in {"user", "assistant"}:
            raise ValueError("role must be 'user' or 'assistant'")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_sessions(session_id, title)
                VALUES (?, ?)
                ON CONFLICT(session_id) DO UPDATE SET updated_at = CURRENT_TIMESTAMP
                """,
                (session_id, session_id),
            )
            conn.execute(
                "INSERT INTO chat_messages(session_id, role, content) VALUES (?, ?, ?)",
                (session_id, role, content),
            )
            conn.execute("UPDATE chat_sessions SET updated_at = CURRENT_TIMESTAMP WHERE session_id = ?", (session_id,))

    def create_chat_session(self, session_id: str, title: str | None = None) -> None:
        """创建或刷新一个 chat session 记录。"""
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_sessions(session_id, title)
                VALUES (?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    title = COALESCE(excluded.title, chat_sessions.title),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (session_id, title or session_id),
            )

    def chat_session_exists(self, session_id: str) -> bool:
        """检查记忆窗口是否存在。"""
        with self.connect() as conn:
            row = conn.execute("SELECT 1 FROM chat_sessions WHERE session_id = ? LIMIT 1", (session_id,)).fetchone()
        return row is not None

    def list_chat_sessions(self) -> list[dict[str, Any]]:
        """列出所有记忆窗口，并附带消息数量。"""
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    s.session_id,
                    s.title,
                    s.created_at,
                    s.updated_at,
                    COUNT(m.id) AS message_count
                FROM chat_sessions s
                LEFT JOIN chat_messages m ON m.session_id = s.session_id
                GROUP BY s.session_id, s.title, s.created_at, s.updated_at
                ORDER BY s.updated_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def load_chat_messages(self, session_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """按时间顺序加载指定窗口最近的若干条消息。"""
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT role, content, created_at
                FROM chat_messages
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def clear_chat_messages(self, session_id: str) -> int:
        """清空指定窗口的聊天消息，返回删除条数。"""
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
            return cursor.rowcount

    def delete_chat_session(self, session_id: str) -> int:
        """删除窗口、消息和依赖申请，返回总删除记录数。"""
        with self.connect() as conn:
            message_cursor = conn.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
            dependency_cursor = conn.execute("DELETE FROM dependency_requests WHERE session_id = ?", (session_id,))
            session_cursor = conn.execute("DELETE FROM chat_sessions WHERE session_id = ?", (session_id,))
            return message_cursor.rowcount + dependency_cursor.rowcount + session_cursor.rowcount

    def add_dependency_request(
        self,
        session_id: str,
        module_name: str,
        package_name: str,
        error_message: str = "",
    ) -> None:
        """记录缺失依赖申请；同一窗口同一模块会更新为 pending。"""
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_sessions(session_id, title)
                VALUES (?, ?)
                ON CONFLICT(session_id) DO UPDATE SET updated_at = CURRENT_TIMESTAMP
                """,
                (session_id, session_id),
            )
            conn.execute(
                """
                INSERT INTO dependency_requests(session_id, module_name, package_name, error_message)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id, module_name) DO UPDATE SET
                    package_name = excluded.package_name,
                    status = 'pending',
                    error_message = excluded.error_message,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (session_id, module_name, package_name, error_message),
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
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE dependency_requests
                SET status = ?, error_message = ?, updated_at = CURRENT_TIMESTAMP
                WHERE session_id = ? AND module_name = ?
                """,
                (status, error_message, session_id, module_name),
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
                blocks.append(f"Table: {table}\nColumns:\n" + "\n".join(col_lines))
            return "\n\n".join(blocks)

    def run_readonly_query(self, sql: str, limit: int = 100) -> dict[str, Any]:
        """执行只读 SELECT/WITH 查询，并用外层 LIMIT 控制返回行数。"""
        if not SAFE_SELECT_RE.match(sql):
            raise ValueError("Only SELECT or WITH queries are allowed.")
        if ";" in sql.strip().rstrip(";"):
            raise ValueError("Only one SQL statement is allowed.")
        sql = sql.strip().rstrip(";")
        with self.connect() as conn:
            conn.execute("PRAGMA query_only = ON")
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

    def _migrate_dependency_requests(self, conn: sqlite3.Connection) -> None:
        """兼容旧版 dependency_requests 表，把无 session_id 的记录迁移到 legacy。"""
        columns = conn.execute("PRAGMA table_info(dependency_requests)").fetchall()
        column_names = {row["name"] for row in columns}
        if "session_id" in column_names:
            return

        conn.executescript(
            """
            ALTER TABLE dependency_requests RENAME TO dependency_requests_old;

            CREATE TABLE dependency_requests (
                session_id TEXT NOT NULL,
                module_name TEXT NOT NULL,
                package_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'installed', 'failed', 'ignored')),
                error_message TEXT,
                requested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(session_id, module_name)
            );

            INSERT INTO dependency_requests(
                session_id, module_name, package_name, status, error_message, requested_at, updated_at
            )
            SELECT
                'legacy', module_name, package_name, status, error_message, requested_at, updated_at
            FROM dependency_requests_old;

            DROP TABLE dependency_requests_old;
            """
        )


def _validate_identifier(identifier: str) -> None:
    """校验 SQLite 标识符，避免表名拼接导致 SQL 注入。"""
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", identifier):
        raise ValueError("Table name must be a valid SQL identifier, e.g. sample_sales")


def _read_csv_with_encoding_fallback(csv_path: Path) -> pd.DataFrame:
    """按常见编码尝试读取 CSV，兼容 Windows 上常见的 GBK/GB18030 文件。"""
    last_error: Exception | None = None
    for encoding in CSV_ENCODINGS:
        try:
            return pd.read_csv(csv_path, encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error:
        raise last_error
    return pd.read_csv(csv_path)


def _quote_identifier(identifier: str) -> str:
    """给已经校验过的表名加双引号，供 PRAGMA/DROP 等语句使用。"""
    _validate_identifier(identifier)
    return '"' + identifier.replace('"', '""') + '"'
