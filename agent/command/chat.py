from __future__ import annotations

"""chat 命令流程：选择记忆窗口、处理窗口内本地命令，并调用 Agent。"""

from collections.abc import Callable
from typing import Optional

import typer

from agent.command import deps as deps_commands
from agent.command import help as help_commands
from agent.command import memory as memory_commands
from agent.config import get_settings


def chat_request_flow(split_args: Callable[[str], list[str]]) -> None:
    """先选择记忆窗口，再进入该窗口持续输入任务。"""
    while True:
        selected_session = select_memory_window(split_args)
        if selected_session is None:
            typer.echo("Returned to main console.")
            return
        chat_task_loop(selected_session, split_args)


def select_memory_window(split_args: Callable[[str], list[str]]) -> Optional[str]:
    """显示记忆窗口选择菜单，返回用户选中的 session_id。"""
    while True:
        typer.echo("")
        typer.echo("Choose a memory window before calling DeepSeek:")
        typer.echo(memory_commands.memory_windows_text())
        typer.echo("")
        typer.echo("Options:")
        typer.echo("  use <id|number>    - use an existing window")
        typer.echo("  new [session_id]   - create and use a new window")
        typer.echo("  delete <id|number> - delete an old window")
        typer.echo("  exit / quit        - return to previous level")

        choice = typer.prompt("memory-select").strip()
        if not choice:
            continue
        lowered = choice.lower()
        if lowered in {"exit", "quit"}:
            return None

        parts = split_args(choice)
        command = parts[0].lower()
        if command == "use":
            if len(parts) != 2:
                typer.echo("Usage: use <id|number>")
                continue
            session_id = memory_commands.resolve_window_ref(parts[1])
            memory_commands.create_memory_window(session_id)
            typer.echo(f"Using memory window: {session_id}")
            return session_id
        if command == "new":
            session_id = parts[1] if len(parts) > 1 else memory_commands.generate_session_id()
            try:
                memory_commands.create_new_memory_window(session_id)
            except ValueError as exc:
                typer.echo(str(exc))
                continue
            typer.echo(f"Created and using memory window: {session_id}")
            return session_id
        if command == "delete":
            if len(parts) != 2:
                typer.echo("Usage: delete <id|number>")
                continue
            session_id = memory_commands.resolve_window_ref(parts[1])
            deleted = memory_commands.delete_memory_window(session_id)
            typer.echo(f"Deleted {deleted} records for memory window: {session_id}")
            continue

        typer.echo("Unknown option. Use: use <id|number>, new [session_id], delete <id|number>, exit.")


def chat_task_loop(session_id: str, split_args: Callable[[str], list[str]]) -> None:
    """在指定记忆窗口内循环读取任务；本地命令不会发送给 DeepSeek。"""
    typer.echo(
        f"Entered memory window: {session_id}. Type a task to call DeepSeek, "
        "deps-list/deps-install/deps-ignore for dependencies, or 'exit / quit' to return."
    )
    while True:
        task = typer.prompt(f"task[{session_id}]").strip()
        if not task:
            continue
        if task.lower() in {"exit", "quit"}:
            typer.echo("Returned to memory window selection.")
            break
        if task.lower() in {"help", "?"}:
            typer.echo(help_commands.task_window_help_text())
            continue
        if deps_commands.handle_task_window_command(split_args(task), session_id):
            continue
        invoke_agent_task(task, session_id)


def invoke_agent_task(task: str, session_id: str) -> str:
    """构建 AgentExecutor，加载窗口记忆，执行任务并保存本轮对话。"""
    from agent.model.react_agent import build_agent_executor

    settings = get_settings()
    executor = build_agent_executor(settings, session_id)
    memory = memory_commands.build_memory(settings.local_db_path, session_id)
    result = executor.invoke({"input": task, "chat_history": memory.load()})
    output = result["output"]
    memory.save_turn(task, output)
    typer.echo(output)
    return output
