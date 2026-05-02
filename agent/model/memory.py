from __future__ import annotations

"""对话记忆封装：在 SQLite 记录和 LangChain Message 对象之间转换。"""

from agent.db.local_database import LocalDatabase


class ChatMemory:
    """把会话消息持久化到 SQLite，并转换为 LangChain 可用的消息对象。"""

    def __init__(self, database: LocalDatabase, session_id: str, max_messages: int = 20):
        """绑定数据库和窗口 id，并确保窗口记录存在。"""
        self.database = database
        self.session_id = session_id
        self.max_messages = max_messages
        self.database.initialize()
        self.database.create_chat_session(session_id)

    def load(self):
        """加载历史消息，并转换成 LangChain 的 HumanMessage/AIMessage。"""
        from langchain_core.messages import AIMessage, HumanMessage

        rows = self.database.load_chat_messages(self.session_id, limit=self.max_messages)
        messages = []
        for row in rows:
            if row["role"] == "user":
                messages.append(HumanMessage(content=row["content"]))
            elif row["role"] == "assistant":
                messages.append(AIMessage(content=row["content"]))
        return messages

    def save_turn(self, user_input: str, assistant_output: str) -> None:
        """保存一轮用户输入和助手回复。"""
        self.database.add_chat_message(self.session_id, "user", user_input)
        self.database.add_chat_message(self.session_id, "assistant", assistant_output)

    def transcript(self, limit: int = 20) -> str:
        """把最近的记忆记录格式化为可读文本。"""
        rows = self.database.load_chat_messages(self.session_id, limit=limit)
        if not rows:
            return f"No memory for session: {self.session_id}"
        lines = [f"Memory session: {self.session_id}"]
        for row in rows:
            lines.append(f"[{row['created_at']}] {row['role']}: {row['content']}")
        return "\n".join(lines)

    def clear(self) -> int:
        """清空当前窗口的聊天消息。"""
        return self.database.clear_chat_messages(self.session_id)

    def delete_window(self) -> int:
        """删除当前窗口及其关联数据。"""
        return self.database.delete_chat_session(self.session_id)

    def create_window(self, title: str | None = None) -> None:
        """显式创建当前窗口记录。"""
        self.database.create_chat_session(self.session_id, title=title)

    def list_windows(self) -> str:
        """列出所有窗口，主要供调试或命令层展示。"""
        rows = self.database.list_chat_sessions()
        if not rows:
            return "No memory windows."
        lines = ["Memory windows:"]
        for index, row in enumerate(rows, start=1):
            lines.append(
                f"{index}. id={row['session_id']} | messages={row['message_count']} | updated_at={row['updated_at']}"
            )
        return "\n".join(lines)

    def window_ids(self) -> list[str]:
        """返回所有窗口 id。"""
        return [row["session_id"] for row in self.database.list_chat_sessions()]
