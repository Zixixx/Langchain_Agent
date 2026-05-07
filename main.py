from __future__ import annotations

"""项目命令行入口：进入交互式主菜单并把命令分发到 command 模块。"""

import shlex
from pathlib import Path

import typer

from agent.command import chat as chat_commands
from agent.command import db as db_commands
from agent.command import deps as deps_commands
from agent.command import help as help_commands
from agent.command import libreoffice as libreoffice_commands
from agent.command import memory as memory_commands
from agent.command import rag as rag_commands
from agent.config import get_settings


def _ensure_sqlite_files() -> None:
    """启动时确保 SQLite 文件存在，避免后续命令第一次访问时报路径错误。"""
    settings = get_settings()
    sqlite_paths = [
        settings.local_db_path,
        settings.table_db_path,
        settings.rag_db_path,
        settings.rag_persist_dir / "chroma.sqlite3",
    ]
    for path in sqlite_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)


def _ensure_io_dirs() -> None:
    """启动时确保 Agent 可见的输入/输出目录存在。"""
    settings = get_settings()
    for name in ("input", "output"):
        (settings.workspace / name).mkdir(parents=True, exist_ok=True)


def _split_console_args(line: str) -> list[str]:
    """分割命令行输入的命令， posix=False 保留 Windows 路径中的反斜杠"""
    return shlex.split(line, posix=False)


def console() -> None:
    """循环等待用户输入本地命令。"""
    typer.echo("Hybrid AI Agent console. Type 'help / ?' for help, 'exit / quit' to quit.")
    while True:
        try:
            line = typer.prompt("agent-cli").strip()
        except (EOFError, KeyboardInterrupt):
            typer.echo("\nbye")
            break

        if not line:
            continue
        if line.lower() in {"exit", "quit"}:
            break
        if line.lower() in {"help", "?"}:
            typer.echo(help_commands.console_help_text())
            continue

        try:
            _dispatch_console_command(line)
        except Exception as exc:
            typer.echo(f"Command failed: {exc}")


def _dispatch_console_command(line: str) -> None:
    """解析主菜单输入，并调用对应的命令处理模块。"""
    parts = _split_console_args(line)
    if not parts:
        return

    command = parts[0].lower()
    rest = line[len(parts[0]) :].strip()

    if command == "chat":
        chat_commands.chat_request_flow(_split_console_args)
    elif command == "rag-list":
        if len(parts) == 2 and parts[1] == "-a":
            typer.echo(rag_commands.list_libraries(all_flag=True))
        elif len(parts) == 2:
            typer.echo(rag_commands.list_libraries(parts[1]))
        else:
            raise ValueError("Usage: rag-list [rag_id|number] OR rag-list -a")
    elif command == "rag-show":
        if len(parts) == 2 and parts[1] == "-a":
            typer.echo(rag_commands.show_documents(all_flag=True))
        elif len(parts) == 2:
            typer.echo(rag_commands.show_documents(parts[1]))
        else:
            raise ValueError("Usage: rag-show <rag_id|number> OR rag-show -a")
    elif command == "rag-new":
        if len(parts) > 2:
            raise ValueError("Usage: rag-new [rag_id]")
        typer.echo(rag_commands.new(parts[1] if len(parts) == 2 else None))
    elif command == "rag-add":
        if len(parts) in {3, 4} and parts[1] == "-a":
            typer.echo(rag_commands.add_all(Path(parts[2]), parts[3] if len(parts) == 4 else "replace"))
        elif len(parts) in {3, 4}:
            typer.echo(rag_commands.add(Path(parts[1]), parts[2], parts[3] if len(parts) == 4 else "replace"))
        else:
            raise ValueError("Usage: rag-add <file_path|dir> <rag_id|number> [replace|append|fail] OR rag-add -a <file_path|dir> [replace|append|fail]")
    elif command == "rag-remove":
        if len(parts) == 2 and parts[1] == "-a":
            typer.echo(rag_commands.remove(all_flag=True))
        elif len(parts) == 3 and parts[1] == "-a":
            typer.echo(rag_commands.remove(rag_ref=parts[2], all_flag=True))
        elif len(parts) == 2:
            typer.echo(rag_commands.remove(source=parts[1]))
        elif len(parts) == 3:
            typer.echo(rag_commands.remove(source=parts[1], rag_ref=parts[2]))
        else:
            raise ValueError("Usage: rag-remove <source> [rag_id|number] OR rag-remove -a [rag_id|number]")
    elif command == "rag-delete":
        if len(parts) == 2 and parts[1] == "-a":
            typer.echo(rag_commands.delete(all_flag=True))
        elif len(parts) == 3 and parts[1] == "-a":
            typer.echo(rag_commands.delete(parts[2], all_flag=True))
        elif len(parts) == 2:
            typer.echo(rag_commands.delete_source(parts[1]))
        elif len(parts) == 3:
            typer.echo(rag_commands.delete_source(parts[1], parts[2]))
        else:
            raise ValueError("Usage: rag-delete <source> [rag_id|number] OR rag-delete -a [rag_id|number]")
    elif command == "rag-search":
        if len(parts) < 2:
            raise ValueError("Usage: rag-search <query> [rag_id|number]")
        rag_ref = None
        if len(parts) >= 3:
            try:
                rag_ref = rag_commands.resolve_rag_ref(parts[-1])
            except ValueError:
                rag_ref = None
        query = " ".join(parts[1:-1]) if rag_ref else " ".join(parts[1:])
        typer.echo(rag_commands.search(query, rag_ref=rag_ref))
    elif command == "db-list":
        if len(parts) == 2 and parts[1] == "-a":
            typer.echo(db_commands.list_tables(all_flag=True))
        elif len(parts) == 2:
            typer.echo(db_commands.list_tables(parts[1]))
        else:
            raise ValueError("Usage: db-list [table|number] OR db-list -a")
    elif command == "db-show":
        if len(parts) == 2 and parts[1] == "-a":
            typer.echo(db_commands.show_tables(all_flag=True))
        elif len(parts) == 2:
            typer.echo(db_commands.show_tables(parts[1]))
        else:
            raise ValueError("Usage: db-show <table|number> OR db-show -a")
    elif command == "db-add":
        if len(parts) not in {2, 3}:
            raise ValueError("Usage: db-add <table_file|dir> [replace|append|fail]")
        typer.echo(db_commands.add(Path(parts[1]), parts[2] if len(parts) == 3 else "replace"))
    elif command == "db-delete":
        if len(parts) == 2 and parts[1] == "-a":
            typer.echo(db_commands.delete_all())
        elif len(parts) == 2:
            typer.echo(db_commands.delete(parts[1]))
        else:
            raise ValueError("Usage: db-delete <table|number> OR db-delete -a")
    elif command == "db-query":
        if not rest:
            raise ValueError("Usage: db-query <sql>")
        typer.echo(db_commands.query(rest))
    elif command == "deps-list":
        if len(parts) == 2 and parts[1] == "-a":
            typer.echo(deps_commands.deps_list(all_flag=True))
        elif len(parts) == 2:
            session_id = memory_commands.resolve_window_ref(parts[1])
            typer.echo(deps_commands.deps_list(session_id=session_id))
        else:
            raise ValueError("Usage: deps-list [window_id|number] OR deps-list -a")
    elif command == "deps-show":
        if len(parts) == 2 and parts[1] == "-a":
            typer.echo(deps_commands.deps_show(all_flag=True))
        elif len(parts) == 2:
            session_id = memory_commands.resolve_window_ref(parts[1])
            typer.echo(deps_commands.deps_show(session_id=session_id))
        else:
            raise ValueError("Usage: deps-show [window_id|number] OR deps-show -a")
    elif command == "deps-install":
        if len(parts) == 2 and parts[1] == "-a":
            typer.echo(deps_commands.deps_install(all_flag=True))
        elif len(parts) == 3 and parts[1] == "-a":
            session_id = memory_commands.resolve_window_ref(parts[2])
            typer.echo(deps_commands.deps_install(all_flag=True, session_id=session_id))
        elif len(parts) == 2:
            typer.echo(deps_commands.deps_install(parts[1]))
        else:
            raise ValueError("Usage: deps-install <module> OR deps-install -a [window-number|window-id]")
    elif command == "deps-ignore":
        if len(parts) == 2 and parts[1] == "-a":
            typer.echo(deps_commands.deps_ignore(all_flag=True))
        elif len(parts) == 3 and parts[1] == "-a":
            session_id = memory_commands.resolve_window_ref(parts[2])
            typer.echo(deps_commands.deps_ignore(all_flag=True, session_id=session_id))
        elif len(parts) == 2:
            typer.echo(deps_commands.deps_ignore(parts[1]))
        elif len(parts) == 3:
            session_id = memory_commands.resolve_window_ref(parts[2])
            typer.echo(deps_commands.deps_ignore(parts[1], session_id=session_id))
        else:
            raise ValueError("Usage: deps-ignore <module> OR deps-ignore <module> <window-number|window-id> OR deps-ignore -a [window-number|window-id]")
    elif command == "memory-list":
        if len(parts) == 2 and parts[1] == "-a":
            typer.echo(memory_commands.list_memory())
        elif len(parts) == 2:
            session_id = memory_commands.resolve_window_ref(parts[1])
            typer.echo(memory_commands.list_memory(session_id))
        else:
            raise ValueError("Usage: memory-list [session_id|number] OR memory-list -a")
    elif command == "memory-show":
        if len(parts) == 2 and parts[1] == "-a":
            typer.echo(memory_commands.show_all_memory())
        elif len(parts) == 2:
            session_id = memory_commands.resolve_window_ref(parts[1])
            typer.echo(memory_commands.show_memory(session_id))
        else:
            raise ValueError("Usage: memory-show <session_id|number> OR memory-show -a")
    elif command == "memory-new":
        session_id = parts[1] if len(parts) > 1 else None
        typer.echo(memory_commands.new_memory(session_id))
    elif command == "memory-clear":
        if len(parts) == 2 and parts[1] == "-a":
            typer.echo(memory_commands.clear_all_memory())
            chat_commands.clear_executor_cache()
        elif len(parts) == 2:
            session_id = memory_commands.resolve_window_ref(parts[1])
            typer.echo(memory_commands.clear_memory(session_id))
            chat_commands.clear_executor_cache(session_id)
        else:
            raise ValueError("Usage: memory-clear <session_id|number> OR memory-clear -a")
    elif command == "memory-delete":
        if len(parts) == 2 and parts[1] == "-a":
            typer.echo(memory_commands.delete_all_memory())
            chat_commands.clear_executor_cache()
        elif len(parts) == 2:
            session_id = memory_commands.resolve_window_ref(parts[1])
            typer.echo(memory_commands.delete_memory(session_id))
            chat_commands.clear_executor_cache(session_id)
        else:
            raise ValueError("Usage: memory-delete <session_id|number> OR memory-delete -a")
    elif command == "libreoffice-check":
        if len(parts) != 1:
            raise ValueError("Usage: libreoffice-check")
        libreoffice_commands.check()
    elif command == "libreoffice-install":
        if len(parts) != 1:
            raise ValueError("Usage: libreoffice-install")
        libreoffice_commands.install()
    else:
        raise ValueError(f"Unknown command: {command}. Type 'help / ?' for help.")


if __name__ == "__main__":
    _ensure_io_dirs()
    _ensure_sqlite_files()
    console()
