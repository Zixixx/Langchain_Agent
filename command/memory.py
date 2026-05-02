from __future__ import annotations

"""记忆窗口命令：负责创建、列出、清空、删除和解析 session_id。"""

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from agent.config import get_settings
from agent.db.local_database import LocalDatabase


def generate_session_id() -> str:
    """生成带时间戳和随机后缀的唯一记忆窗口 id。"""
    while True:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        session_id = f"mem-{stamp}-{uuid4().hex[:6]}"
        if not memory_window_exists(session_id):
            return session_id


def build_memory(db_path: Path, session_id: str, max_messages: int = 20):
    """构造 ChatMemory 对象，用于 Agent 调用前后加载和保存历史。"""
    from agent.model.memory import ChatMemory

    return ChatMemory(LocalDatabase(db_path), session_id=session_id, max_messages=max_messages)


def create_memory_window(session_id: str) -> None:
    """创建或刷新一个记忆窗口记录。"""
    db = _agent_database()
    db.create_chat_session(session_id, title=session_id)


def create_new_memory_window(session_id: str) -> None:
    """只允许创建不存在的新窗口，避免误复用旧记忆。"""
    if memory_window_exists(session_id):
        raise ValueError(f"Memory window already exists: {session_id}")
    create_memory_window(session_id)


def memory_window_exists(session_id: str) -> bool:
    """检查指定 session_id 是否已经存在。"""
    return _agent_database().chat_session_exists(session_id)


def delete_memory_window(session_id: str) -> int:
    """删除窗口、窗口消息和该窗口的依赖申请。"""
    return _agent_database().delete_chat_session(session_id)


def memory_window_rows() -> list[dict]:
    """读取所有记忆窗口的结构化列表。"""
    return _agent_database().list_chat_sessions()


def memory_window_ids() -> list[str]:
    """提取所有窗口 id，供编号解析使用。"""
    return [row["session_id"] for row in memory_window_rows()]


def resolve_window_ref(ref: str) -> str:
    """把用户输入的窗口编号或窗口 id 解析成 session_id。"""
    if ref.isdigit():
        ids = memory_window_ids()
        index = int(ref)
        if index < 1 or index > len(ids):
            raise ValueError(f"Memory window number out of range: {ref}")
        return ids[index - 1]
    if not memory_window_exists(ref):
        raise ValueError(f"Memory window does not exist: {ref}")
    return ref


def memory_windows_text() -> str:
    """把窗口列表格式化成主菜单/选择界面可读文本。"""
    rows = memory_window_rows()
    if not rows:
        return "No memory windows."
    lines = ["Memory windows:"]
    for index, row in enumerate(rows, start=1):
        lines.append(f"{index}. id={row['session_id']} | messages={row['message_count']} | updated_at={row['updated_at']}")
    return "\n".join(lines)


def show_memory(session_id: str, limit: int = 20) -> str:
    """返回指定窗口最近若干条对话记录。"""
    settings = get_settings()
    memory = build_memory(settings.local_db_path, session_id, max_messages=limit)
    return memory.transcript(limit=limit)


def new_memory(session_id: str | None = None) -> str:
    """新建窗口；未传 id 时自动生成一个唯一 id。"""
    target_session = session_id or generate_session_id()
    create_new_memory_window(target_session)
    return f"Created memory window: {target_session}"


def list_memory() -> str:
    """返回所有记忆窗口的展示文本。"""
    return memory_windows_text()


def clear_memory(session_id: str) -> str:
    """清空指定窗口的消息，但保留窗口和依赖申请。"""
    settings = get_settings()
    memory = build_memory(settings.local_db_path, session_id)
    deleted = memory.clear()
    return f"Deleted {deleted} messages from memory session: {session_id}"


def delete_memory(session_id: str) -> str:
    """删除指定窗口及其关联数据。"""
    deleted = delete_memory_window(session_id)
    return f"Deleted {deleted} records for memory window: {session_id}"


def _agent_database() -> LocalDatabase:
    """打开 agent.sqlite3 并确保表结构存在。"""
    settings = get_settings()
    db = LocalDatabase(settings.local_db_path)
    db.initialize()
    return db
