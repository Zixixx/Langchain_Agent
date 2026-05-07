from __future__ import annotations

"""chat 命令流程：选择记忆窗口、处理窗口内本地命令，并调用 Agent。"""

import json
from collections.abc import Callable
from pprint import pformat
from typing import Optional

import typer

from agent.command import deps as deps_commands
from agent.command import help as help_commands
from agent.command import libreoffice as libreoffice_commands
from agent.command import memory as memory_commands
from agent.config import get_settings


_EXECUTOR_CACHE: dict[str, object] = {}


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
        typer.echo("  new [session_id]              - create and use a new window")
        typer.echo("  use <session_id|number>       - use an existing window")
        typer.echo("  delete <session_id|number>    - delete an old window")
        typer.echo("  delete -a                     - delete all windows")
        typer.echo("  exit / quit                   - return to previous level")

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
            try:
                session_id = memory_commands.resolve_window_ref(parts[1])
            except ValueError as exc:
                typer.echo(str(exc))
                continue
            typer.echo(f"Using memory window: {session_id}")
            return session_id
        elif command == "new":
            if len(parts) > 2:
                typer.echo("Usage: new [session_id]")
                continue
            session_id = parts[1] if len(parts) > 1 else memory_commands.generate_session_id()
            try:
                memory_commands.create_new_memory_window(session_id)
            except ValueError as exc:
                typer.echo(str(exc))
                continue
            typer.echo(f"Created and using memory window: {session_id}")
            return session_id
        elif command == "delete":
            if len(parts) == 2 and parts[1] == "-a":
                typer.echo(memory_commands.delete_all_memory())
                clear_executor_cache()
                continue
            if len(parts) != 2:
                typer.echo("Usage: delete <id|number> OR delete -a")
                continue
            try:
                session_id = memory_commands.resolve_window_ref(parts[1])
            except ValueError as exc:
                typer.echo(str(exc))
                continue
            message = memory_commands.delete_memory(session_id)
            clear_executor_cache(session_id)
            typer.echo(message)
            continue
        else:
            typer.echo("Unknown option. Use: use <id|number>, new [session_id], delete <id|number>, delete -a, exit.")


def chat_task_loop(session_id: str, split_args: Callable[[str], list[str]]) -> None:
    """在指定记忆窗口内循环读取任务；本地命令不会发送给 DeepSeek。"""
    _preload_agent_executor(session_id)
    typer.echo(f"Entered memory window: {session_id}. ")
    typer.echo("Type a task to call AI, 'help / ?' for help, or 'exit / quit' to return.")
    while True:
        task = typer.prompt(f"task[{session_id}]").strip()
        if not task:
            continue
        parts = split_args(task)
        command = parts[0].lower() if parts else ""
        try:
            if command in {"exit", "quit"}:
                if len(parts) == 1:
                    typer.echo("Returned to memory window selection.")
                    break
                typer.echo("Usage: exit OR quit")
                continue
            elif command in {"help", "?"}:
                if len(parts) == 1:
                    typer.echo(help_commands.task_window_help_text())
                else:
                    typer.echo("Usage: help OR ?")
                continue
            elif command == "deps-list":
                if len(parts) != 1:
                    typer.echo("Usage: deps-list")
                else:
                    typer.echo(deps_commands.deps_list(session_id=session_id))
                continue
            elif command == "deps-show":
                if len(parts) != 1:
                    typer.echo("Usage: deps-show")
                else:
                    typer.echo(deps_commands.deps_show(session_id=session_id))
                continue
            elif command == "deps-install":
                if len(parts) == 2 and parts[1] == "-a":
                    typer.echo(deps_commands.deps_install(all_flag=True, session_id=session_id))
                elif len(parts) == 2:
                    typer.echo(deps_commands.deps_install(parts[1], session_id=session_id))
                else:
                    typer.echo("Usage: deps-install <module|number> OR deps-install -a")
                continue
            elif command == "deps-ignore":
                if len(parts) == 2 and parts[1] == "-a":
                    typer.echo(deps_commands.deps_ignore(all_flag=True, session_id=session_id))
                elif len(parts) == 2:
                    typer.echo(deps_commands.deps_ignore(parts[1], session_id=session_id))
                else:
                    typer.echo("Usage: deps-ignore <module|number> OR deps-ignore -a")
                continue
            elif command == "libreoffice-check":
                if len(parts) == 1:
                    libreoffice_commands.check()
                else:
                    typer.echo("Usage: libreoffice-check")
                continue
            elif command == "libreoffice-install":
                if len(parts) == 1:
                    libreoffice_commands.install()
                else:
                    typer.echo("Usage: libreoffice-install")
                continue
            invoke_agent_task(task, session_id)
        except Exception as exc:
            typer.echo(f"Command failed: {exc}")
            continue


def invoke_agent_task(task: str, session_id: str) -> str:
    """构建 AgentExecutor，加载窗口记忆，执行任务并保存本轮对话。"""
    settings = get_settings()
    executor = _get_agent_executor(session_id)
    memory = memory_commands.build_memory(settings.local_db_path, session_id)
    try:
        result = executor.invoke({"input": task, "chat_history": memory.load_trimmed(settings.max_input_tokens)})
    except Exception as exc:
        memory.save_turn(task, "", status="failed", error_message=str(exc))
        raise
    output = result["output"]
    tool_calls_json = _summarize_intermediate_steps(result.get("intermediate_steps", []))
    memory.save_turn(task, output, tool_calls_json=tool_calls_json)
    typer.echo(output)
    return output


def _summarize_intermediate_steps(intermediate_steps: object) -> str:
    """把 LangChain intermediate_steps 转成结构化工具调用摘要。"""
    if not intermediate_steps:
        return "[]"
    if not isinstance(intermediate_steps, list):
        return json.dumps(
            [
                {
                    "step": 1,
                    "tool": "unknown",
                    "purpose": "记录非标准工具调用结果",
                    "input_summary": {},
                    "result_summary": _truncate_text(pformat(intermediate_steps), 800),
                    "status": "success",
                }
            ],
            ensure_ascii=False,
        )

    calls = []
    for index, step in enumerate(intermediate_steps, start=1):
        try:
            action, observation = step
        except Exception:
            calls.append(
                {
                    "step": index,
                    "tool": "unknown",
                    "purpose": "记录无法解析的工具调用步骤",
                    "input_summary": {},
                    "result_summary": _truncate_text(pformat(step), 800),
                    "status": "success",
                }
            )
            continue
        tool_name = getattr(action, "tool", "unknown_tool")
        tool_input = getattr(action, "tool_input", "")
        observation_text = str(observation)
        calls.append(
            {
                "step": index,
                "tool": tool_name,
                "purpose": _infer_tool_purpose(tool_name, tool_input),
                "input_summary": _summarize_tool_input(tool_input),
                "result_summary": _summarize_observation(observation_text),
                "status": "failed" if _looks_failed_observation(observation_text) else "success",
            }
        )
    return json.dumps(calls, ensure_ascii=False)


def _summarize_tool_input(tool_input: object) -> object:
    """摘要化工具入参；content/code 等长字段只记录字符数。"""
    if isinstance(tool_input, dict):
        summary = {}
        for key, value in tool_input.items():
            if key in {"content", "code", "old_text", "new_text"} and isinstance(value, str):
                summary[key] = {"char_count": len(value)}
            elif isinstance(value, str):
                summary[key] = _truncate_text(value, 300)
            else:
                summary[key] = value
        return summary
    if isinstance(tool_input, str):
        return _truncate_text(tool_input, 300)
    return _truncate_text(pformat(tool_input), 300)


def _summarize_observation(observation: str) -> str:
    """摘要化工具返回结果，避免单轮记录过大。"""
    if not observation:
        return ""
    return _truncate_text(observation, 800)


def _infer_tool_purpose(tool_name: str, tool_input: object) -> str:
    """根据工具名和关键参数生成“用来干什么”的概述。"""
    data = tool_input if isinstance(tool_input, dict) else {}
    path = data.get("path") or data.get("source_path") or data.get("output_path")
    new_path = data.get("new_path")
    if tool_name.startswith("read_"):
        return f"读取文件内容：{path}" if path else "读取文件内容"
    if tool_name in {"write_text_file", "append_text_file", "replace_text_file"}:
        return f"写入或修改输出文件：{path}" if path else "写入或修改输出文件"
    if tool_name in {"copy_file", "copy_directory"}:
        return "复制文件或目录到 output"
    if tool_name in {"rename_file", "rename_directory"}:
        return f"移动或重命名路径：{path} -> {new_path}" if new_path else "移动或重命名路径"
    if tool_name in {"delete_file", "delete_directory"}:
        return f"删除 output 路径：{path}" if path else "删除 output 路径"
    if tool_name.startswith("rag_"):
        return "查询 RAG 知识库"
    if tool_name.startswith("sql_"):
        return "查询 SQLite 业务数据库"
    if tool_name.startswith("cpp_"):
        return "调用 C++ 高性能工具计算"
    if tool_name.startswith("run_python"):
        return "运行 Python 代码或脚本"
    if tool_name == "request_dependency_install":
        return "记录缺失依赖安装申请"
    return f"调用工具：{tool_name}"


def _looks_failed_observation(observation: str) -> bool:
    """根据工具返回文本粗略判断该工具调用是否失败。"""
    lowered = observation.lower()
    return lowered.startswith(("command failed", "failed", "sandbox policy rejected")) or "error:" in lowered


def _truncate_text(text: str, max_chars: int) -> str:
    """限制单段轨迹长度，避免长脚本或大输出写入记忆库。"""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n... [truncated {len(text) - max_chars} chars]"


def _preload_agent_executor(session_id: str) -> None:
    """进入窗口时预热 Agent。"""
    if session_id in _EXECUTOR_CACHE:
        return
    typer.echo("Loading Agent tools for this memory window...")
    _get_agent_executor(session_id)


def _get_agent_executor(session_id: str):
    """缓存每个窗口的 AgentExecutor，避免同一进程内重复构建工具链。"""
    if session_id not in _EXECUTOR_CACHE:
        from agent.model.react_agent import build_agent_executor

        settings = get_settings()
        _EXECUTOR_CACHE[session_id] = build_agent_executor(settings, session_id)
    return _EXECUTOR_CACHE[session_id]


def clear_executor_cache(session_id: str | None = None) -> int:
    """清理对话窗口的 AgentExecutor 缓存；删除窗口时调用。"""
    if session_id is None:
        deleted = len(_EXECUTOR_CACHE)
        _EXECUTOR_CACHE.clear()
        return deleted
    return 1 if _EXECUTOR_CACHE.pop(session_id, None) is not None else 0
