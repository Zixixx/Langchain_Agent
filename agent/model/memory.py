from __future__ import annotations

"""对话记忆封装：把每轮任务记录转换为 LangChain Message 对象。"""

from collections.abc import Sequence
import json

from agent.db.local_database import LocalDatabase


class ChatMemory:
    """把窗口轮次持久化到 SQLite，并转换为 LangChain 可用的消息对象。"""

    def __init__(
        self,
        database: LocalDatabase,
        session_id: str,
        max_messages: int | None = None,
        create_if_missing: bool = True,
    ):
        """绑定数据库和窗口 id；只在需要写入新对话时自动创建窗口。"""
        self.database = database
        self.session_id = session_id
        self.max_messages = max_messages
        self.database.initialize()
        if create_if_missing:
            self.database.create_chat_session(session_id)

    def load(self):
        """按轮数从低到高加载历史轮次，并转换成 LangChain 的 HumanMessage/AIMessage。"""
        from langchain_core.messages import AIMessage, HumanMessage

        rows = self.database.load_chat_turns(self.session_id, newest_first=False)
        messages = []
        for row in rows:
            messages.append(
                HumanMessage(
                    content=(
                        f"[Memory turn {row['turn_index']}]\n"
                        f"User input:\n{row['user_input']}"
                    )
                )
            )
            messages.append(
                AIMessage(
                    content=(
                        f"[Memory turn {row['turn_index']}]\n"
                        f"Status: {row['status']}\n"
                        f"Tool calls:\n{_format_tool_calls(row['tool_calls_json'])}\n"
                        f"Agent output:\n{row['agent_output'] or ''}"
                    )
                )
            )
        return messages

    def load_trimmed(self, max_tokens: int | None):
        """加载历史消息，并按最大输入 token 数保留最近能放下的轮次。"""
        messages = self.load()
        if max_tokens is None or not messages:
            return messages
        try:
            from langchain_core.messages import trim_messages
        except ImportError:
            return messages
        try:
            return trim_messages(
                messages,
                max_tokens=max_tokens,
                token_counter=_estimate_message_tokens,
                strategy="last",
                start_on="human",
                end_on=("human", "ai"),
                include_system=False,
                allow_partial=False,
            )
        except TypeError:
            try:
                return trim_messages(
                    messages,
                    max_tokens=max_tokens,
                    token_counter=_estimate_message_tokens,
                    strategy="last",
                    allow_partial=False,
                )
            except TypeError:
                return messages

    def save_turn(
        self,
        user_input: str,
        assistant_output: str,
        tool_calls_json: str = "[]",
        status: str = "success",
        error_message: str = "",
    ) -> None:
        """保存一轮用户输入、工具调用摘要和助手回复。"""
        self.database.add_chat_turn(
            self.session_id,
            user_input=user_input,
            agent_output=assistant_output,
            tool_calls_json=tool_calls_json,
            status=status,
            error_message=error_message,
        )

    def transcript(self, limit: int = 20) -> str:
        """把窗口轮次按轮展示为可读文本。"""
        rows = self.database.load_chat_turns(self.session_id, newest_first=False)
        if not rows:
            return f"Memory session: {self.session_id}\nNo turns."
        lines = [f"Memory session: {self.session_id}"]
        for row in rows:
            lines.append("")
            lines.append(f"Turn {row['turn_index']} | {row['status']} | {row['created_at']}")
            lines.append("User input:")
            lines.append(row["user_input"])
            lines.append("Tool calls:")
            lines.append(_format_tool_calls(row["tool_calls_json"]))
            lines.append("Agent output:")
            lines.append(row["agent_output"] or "")
            if row["error_message"]:
                lines.append("Error:")
                lines.append(row["error_message"])
        return "\n".join(lines)

    def clear(self) -> dict[str, int]:
        """清空当前窗口的轮次记录和依赖申请，并返回分项计数。"""
        return self.database.clear_chat_turns(self.session_id)

def _format_tool_calls(tool_calls_json: str) -> str:
    """把工具调用 JSON 摘要格式化成人和模型都容易阅读的短文本。"""
    try:
        calls = json.loads(tool_calls_json or "[]")
    except json.JSONDecodeError:
        return tool_calls_json or "[]"
    if not calls:
        return "(none)"
    lines = []
    for call in calls:
        step = call.get("step", "?")
        tool = call.get("tool", "unknown_tool")
        purpose = call.get("purpose", "")
        status = call.get("status", "")
        result = call.get("result_summary", "")
        input_summary = call.get("input_summary", {})
        lines.append(f"- step={step} | tool={tool} | status={status}")
        if purpose:
            lines.append(f"  purpose: {purpose}")
        if input_summary:
            lines.append(f"  input: {input_summary}")
        if result:
            lines.append(f"  result: {result}")
    return "\n".join(lines)


def _estimate_message_tokens(messages: object) -> int:
    """用字符数粗估 token 数，供 trim_messages 在本地裁剪历史轮次。"""
    if isinstance(messages, Sequence) and not isinstance(messages, (str, bytes)):
        return sum(_estimate_message_tokens(message) for message in messages)
    content = getattr(messages, "content", messages)
    if isinstance(content, list):
        text = json.dumps(content, ensure_ascii=False)
    else:
        text = str(content or "")
    return max(1, len(text) // 4)
