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


def build_memory(db_path: Path, session_id: str, max_messages: int = 20, create_if_missing: bool = True):
    """构造 ChatMemory 对象，用于 Agent 调用前后加载和保存历史。"""
    from agent.model.memory import ChatMemory

    return ChatMemory(
        LocalDatabase(db_path),
        session_id=session_id,
        max_messages=max_messages,
        create_if_missing=create_if_missing,
    )


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


def delete_memory_window(session_id: str) -> dict[str, int]:
    """删除窗口、轮次记录和该窗口的依赖申请。"""
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
        if 1 <= index <= len(ids):
            return ids[index - 1]
        if memory_window_exists(ref):
            return ref
        raise ValueError(f"Memory window number or id does not exist: {ref}")
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
        lines.append(f"{index}. id={row['session_id']} | turns={row['turn_count']} | updated_at={row['updated_at']}")
    return "\n".join(lines)


def show_memory(session_id: str, limit: int = 20) -> str:
    """按轮展示指定窗口的操作记忆。"""
    _require_memory_window(session_id)
    settings = get_settings()
    memory = build_memory(settings.local_db_path, session_id, max_messages=limit, create_if_missing=False)
    return memory.transcript(limit=limit)


def show_all_memory(limit: int = 20) -> str:
    """按轮展示所有窗口的操作记忆。"""
    rows = memory_window_rows()
    if not rows:
        return "No memory windows."
    blocks = [show_memory(row["session_id"], limit=limit) for row in rows]
    return "\n\n" + ("\n\n" + "=" * 60 + "\n\n").join(blocks)


def new_memory(session_id: str | None = None) -> str:
    """新建窗口；未传 id 时自动生成一个唯一 id。"""
    target_session = session_id or generate_session_id()
    create_new_memory_window(target_session)
    return f"Created memory window: {target_session}"


def list_memory(session_id: str | None = None) -> str:
    """返回一个或所有记忆窗口的统计信息。"""
    if not session_id:
        return memory_windows_text()
    _require_memory_window(session_id)
    for index, row in enumerate(memory_window_rows(), start=1):
        if row["session_id"] == session_id:
            return (
                "Memory window:\n"
                f"{index}. id={row['session_id']} | turns={row['turn_count']} | updated_at={row['updated_at']}"
            )
    raise ValueError(f"Memory window does not exist: {session_id}")


def clear_memory(session_id: str) -> str:
    """清空指定窗口的轮次记录和依赖申请，但保留窗口。"""
    _require_memory_window(session_id)
    settings = get_settings()
    memory = build_memory(settings.local_db_path, session_id, create_if_missing=False)
    counts = memory.clear()
    return f"Cleared memory window: {session_id} (turns={counts['turns']}, dependencies={counts['dependencies']})"


def clear_all_memory() -> str:
    """清空所有记忆窗口中的轮次记录和依赖申请，但保留窗口本身。"""
    counts = _agent_database().clear_all_chat_turns()
    return f"Cleared all memory windows (turns={counts['turns']}, dependencies={counts['dependencies']})"


def delete_memory(session_id: str) -> str:
    """删除指定窗口及其关联数据。"""
    _require_memory_window(session_id)
    counts = delete_memory_window(session_id)
    return (
        f"Deleted memory window: {session_id} "
        f"(turns={counts['turns']}, dependencies={counts['dependencies']}, sessions={counts['sessions']})"
    )


def delete_all_memory() -> str:
    """删除所有记忆窗口、轮次记录和依赖请求。"""
    counts = _agent_database().delete_all_chat_sessions()
    return (
        "Deleted all memory windows "
        f"(turns={counts['turns']}, dependencies={counts['dependencies']}, sessions={counts['sessions']})"
    )


def _require_memory_window(session_id: str) -> None:
    """要求窗口必须存在；只读/删除类命令不能隐式创建窗口。"""
    if not memory_window_exists(session_id):
        raise ValueError(f"Memory window does not exist: {session_id}")


def _agent_database() -> LocalDatabase:
    """打开 agent.sqlite3 并确保表结构存在。"""
    settings = get_settings()
    db = LocalDatabase(settings.local_db_path)
    db.initialize()
    return db
