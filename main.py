from __future__ import annotations

"""项目命令行入口：负责启动 Typer、进入主菜单并把命令分发到 command 模块。"""

import shlex
from pathlib import Path
from typing import Optional

import typer

from agent.command import chat as chat_commands
from agent.command import db as db_commands
from agent.command import deps as deps_commands
from agent.command import help as help_commands
from agent.command import memory as memory_commands
from agent.command import rag as rag_commands
from agent.config import get_settings


app = typer.Typer(help="Hybrid AI Agent CLI")


@app.callback(invoke_without_command=True)
def main_loop(ctx: typer.Context) -> None:
    """Enter command loop when no subcommand is provided."""
    _ensure_sqlite_files()
    if ctx.invoked_subcommand is None:
        console()


def _ensure_sqlite_files() -> None:
    """启动时确保三个 SQLite 文件存在，避免后续命令第一次访问时报路径错误。"""
    settings = get_settings()
    sqlite_paths = [
        settings.local_db_path,
        settings.csv_db_path,
        settings.rag_persist_dir / "chroma.sqlite3",
    ]
    for path in sqlite_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)


def console() -> None:
    """循环等待用户输入本地命令。"""
    typer.echo("Hybrid AI Agent console. Type 'help' for commands, 'exit' to quit.")
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
    elif command == "rag-add":
        if len(parts) not in {2, 3}:
            raise ValueError("Usage: rag-add <file_path|dir> [replace|append|fail]")
        rag_commands.add(Path(parts[1]), parts[2] if len(parts) == 3 else "replace")
    elif command == "rag-list":
        rag_commands.list_documents()
    elif command == "rag-delete":
        if not rest:
            raise ValueError("Usage: rag-delete <source>")
        rag_commands.delete(rest)
    elif command == "rag-search":
        if not rest:
            raise ValueError("Usage: rag-search <query>")
        rag_commands.search(rest)
    elif command == "db-add":
        if len(parts) not in {2, 3}:
            raise ValueError("Usage: db-add <csv_path|dir> [replace|append|fail]")
        db_commands.add(Path(parts[1]), parts[2] if len(parts) == 3 else "replace")
    elif command == "db-list":
        db_commands.list_tables()
    elif command == "db-delete":
        if len(parts) != 2:
            raise ValueError("Usage: db-delete <table>")
        db_commands.delete(parts[1])
    elif command == "db-query":
        if not rest:
            raise ValueError("Usage: db-query <sql>")
        db_commands.query(_strip_wrapping_quotes(rest))
    elif command == "deps-list":
        deps_commands.deps_list()
    elif command == "deps-install":
        deps_commands.dispatch_main_deps_install(parts)
    elif command == "deps-ignore":
        deps_commands.dispatch_main_deps_ignore(parts)
    elif command == "memory-show":
        if len(parts) != 2:
            raise ValueError("Usage: memory-show <session_id>")
        memory_show(parts[1])
    elif command == "memory-clear":
        if len(parts) != 2:
            raise ValueError("Usage: memory-clear <session_id>")
        memory_clear(parts[1])
    elif command == "memory-delete":
        if len(parts) != 2:
            raise ValueError("Usage: memory-delete <session_id>")
        memory_delete(parts[1])
    elif command == "memory-new":
        session_id = parts[1] if len(parts) > 1 else None
        memory_new(session_id)
    elif command == "memory-list":
        memory_list()
    else:
        raise ValueError(f"Unknown command: {command}. Type 'help' for commands.")


def _split_console_args(line: str) -> list[str]:
    # posix=False 会保留 Windows 路径中的反斜杠；随后去掉简单包裹引号。
    return [part.strip("\"'") for part in shlex.split(line, posix=False)]


def _strip_wrapping_quotes(value: str) -> str:
    """去掉整段参数外层引号，主要用于交互式 db-query 输入 SQL。"""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


@app.command()
def chat(session_id: str = typer.Option(..., "--session-id")) -> None:
    """直接进入指定记忆窗口的对话循环。"""
    chat_commands.chat_task_loop(session_id, _split_console_args)


@app.command("memory-show")
def memory_show(session_id: str, limit: int = 20) -> None:
    """显示指定窗口最近的对话记忆。"""
    typer.echo(memory_commands.show_memory(session_id, limit=limit))


@app.command("memory-new")
def memory_new(session_id: Optional[str] = typer.Argument(None)) -> None:
    """创建一个新的空记忆窗口。"""
    try:
        typer.echo(memory_commands.new_memory(session_id))
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1) from exc


@app.command("memory-list")
def memory_list() -> None:
    """列出所有记忆窗口及其消息数量。"""
    typer.echo(memory_commands.list_memory())


@app.command("memory-clear")
def memory_clear(session_id: str) -> None:
    """清空指定窗口的对话消息，但保留窗口本身。"""
    typer.echo(memory_commands.clear_memory(session_id))


@app.command("memory-delete")
def memory_delete(session_id: str) -> None:
    """删除指定记忆窗口、对话消息以及该窗口的依赖申请。"""
    typer.echo(memory_commands.delete_memory(session_id))


@app.command("deps-list")
def deps_list(session_id: Optional[str] = None, all_statuses: bool = False) -> None:
    """查看沙箱或 Agent 记录的依赖安装申请。"""
    deps_commands.deps_list(session_id=session_id, all_statuses=all_statuses)


@app.command("deps-install")
def deps_install(
    ref: Optional[str] = typer.Argument(None),
    all_flag: bool = typer.Option(False, "-a", "--all"),
    session_id: Optional[str] = None,
) -> None:
    """用户批准后安装一个或一组待处理依赖。"""
    deps_commands.deps_install(ref=ref, all_flag=all_flag, session_id=session_id)


@app.command("deps-ignore")
def deps_ignore(
    ref: Optional[str] = typer.Argument(None),
    target: Optional[str] = typer.Argument(None),
    all_flag: bool = typer.Option(False, "-a", "--all"),
    session_id: Optional[str] = None,
) -> None:
    """忽略一个或一组待处理依赖申请。"""
    deps_commands.deps_ignore(ref=ref, target=target, all_flag=all_flag, session_id=session_id)


@app.command("rag-add")
def rag_add(path: Path, if_exists: str = typer.Argument("replace")) -> None:
    """把 UTF-8 文档或目录导入 RAG 知识库。"""
    rag_commands.add(path, if_exists=if_exists)


@app.command("rag-list")
def rag_list() -> None:
    """列出已经导入 RAG 知识库的文档 source。"""
    rag_commands.list_documents()


@app.command("rag-delete")
def rag_delete(source: str) -> None:
    """按 source 删除 RAG 文档及其向量 chunk。"""
    rag_commands.delete(source)


@app.command("rag-search")
def rag_search(query: str, k: int = 4) -> None:
    """对 RAG 知识库做相似度检索。"""
    rag_commands.search(query, k=k)


@app.command("db-add")
def db_add(path: Path, if_exists: str = typer.Argument("replace")) -> None:
    """把单个 CSV 或目录中的 CSV 批量导入 csv.sqlite3。"""
    db_commands.add(path, if_exists=if_exists)


@app.command("db-list")
def db_list() -> None:
    """显示 CSV 数据库中的表和字段。"""
    db_commands.list_tables()


@app.command("db-delete")
def db_delete(table: str) -> None:
    """删除 CSV 数据库中的指定表。"""
    db_commands.delete(table)


@app.command("db-query")
def db_query(sql: str, limit: int = 100) -> None:
    """执行只读 SELECT/WITH SQL 查询。"""
    db_commands.query(sql, limit=limit)


if __name__ == "__main__":
    app()
