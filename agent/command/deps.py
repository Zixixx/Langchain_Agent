from __future__ import annotations

"""依赖申请命令：查看、安装或忽略 Agent/沙箱记录的缺包请求。"""

import re
import subprocess
import sys
from typing import Optional

import typer

from agent.config import get_settings
from agent.db.local_database import LocalDatabase


def dependency_rows(session_id: str, status: str | None = "pending") -> list[dict]:
    """读取单个记忆窗口中的依赖申请记录。"""
    return _agent_database().list_dependency_requests(session_id=session_id, status=status)


def all_dependency_rows(status: str | None = "pending") -> list[dict]:
    """读取所有记忆窗口中的依赖申请记录。"""
    return _agent_database().list_all_dependency_requests(status=status)


def dependency_text(session_id: str, status: str | None = "pending") -> str:
    """把单个窗口的依赖申请格式化成 CLI 可读文本。"""
    rows = dependency_rows(session_id=session_id, status=status)
    if not rows:
        return f"No dependency requests for memory window: {session_id}"
    lines = [f"Dependency requests for memory window: {session_id}"]
    for index, row in enumerate(rows, start=1):
        lines.append(
            f"{index}. module={row['module_name']} | package={row['package_name']} "
            f"| status={row['status']} | updated_at={row['updated_at']}"
        )
    return "\n".join(lines)


def all_dependency_text(status: str | None = "pending") -> str:
    """把所有窗口的依赖申请按 session_id 分组展示。"""
    rows = all_dependency_rows(status=status)
    if not rows:
        return "No dependency requests."
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["session_id"], []).append(row)

    lines = ["Dependency request lists:"]
    for list_index, (session_id, session_rows) in enumerate(grouped.items(), start=1):
        lines.append(f"{list_index}. id={session_id}")
        for dep_index, row in enumerate(session_rows, start=1):
            lines.append(
                f"   {dep_index}. module={row['module_name']} | package={row['package_name']} "
                f"| status={row['status']} | updated_at={row['updated_at']}"
            )
    return "\n".join(lines)


def resolve_dependency_by_ref(ref: str, session_id: str) -> dict:
    """在任务窗口内按序号、模块名或包名定位一条依赖申请。"""
    rows = dependency_rows(session_id=session_id, status="pending")
    if ref.isdigit():
        index = int(ref)
        if index < 1 or index > len(rows):
            raise ValueError(f"Dependency request number out of range: {ref}")
        return rows[index - 1]
    return resolve_dependency_by_name(ref, session_id)


def resolve_dependency_by_name(ref: str, session_id: str) -> dict:
    """在指定窗口中按 module_name 或 package_name 查找依赖申请。"""
    rows = dependency_rows(session_id=session_id, status="pending")
    for row in rows:
        if row["module_name"] == ref or row["package_name"] == ref:
            return row
    raise ValueError(f"No pending dependency request found for window '{session_id}': {ref}")


def resolve_dependency_globally(ref: str) -> dict:
    """在所有窗口中按 module_name 或 package_name 查找依赖申请。"""
    rows = all_dependency_rows(status="pending")
    for row in rows:
        if row["module_name"] == ref or row["package_name"] == ref:
            return row
    raise ValueError(f"No pending dependency request found: {ref}")


def resolve_dependency_list_ref(ref: str) -> str:
    """把主菜单中的窗口序号或窗口 id 解析成 session_id。"""
    grouped_session_ids = list(dict.fromkeys(row["session_id"] for row in all_dependency_rows(status="pending")))
    if ref.isdigit():
        index = int(ref)
        if index < 1 or index > len(grouped_session_ids):
            raise ValueError(f"Dependency list number out of range: {ref}")
        return grouped_session_ids[index - 1]
    if ref not in grouped_session_ids:
        raise ValueError(f"No pending dependency list found for window: {ref}")
    return ref


def dispatch_main_deps_install(parts: list[str]) -> None:
    """解析主菜单 deps-install 参数，并转交给安装逻辑。"""
    if len(parts) == 3 and parts[1] == "-a":
        session_id = resolve_dependency_list_ref(parts[2])
        deps_install(None, all_flag=True, session_id=session_id)
        return
    if len(parts) == 2:
        deps_install(parts[1])
        return
    raise ValueError("Usage: deps-install <module> OR deps-install -a <window-number|window-id>")


def dispatch_main_deps_ignore(parts: list[str]) -> None:
    """解析主菜单 deps-ignore 参数，并转交给忽略逻辑。"""
    if len(parts) == 3 and parts[1] == "-a":
        session_id = resolve_dependency_list_ref(parts[2])
        deps_ignore(None, all_flag=True, session_id=session_id)
        return
    if len(parts) == 2:
        deps_ignore(parts[1])
        return
    if len(parts) == 3:
        session_id = resolve_dependency_list_ref(parts[2])
        deps_ignore(parts[1], session_id=session_id)
        return
    raise ValueError(
        "Usage: deps-ignore <module> OR deps-ignore <module> <window-number|window-id> "
        "OR deps-ignore -a <window-number|window-id>"
    )


def handle_task_window_command(parts: list[str], session_id: str) -> bool:
    """处理对话窗口内的 deps 命令；返回 True 表示不需要调用 DeepSeek。"""
    if not parts:
        return True

    command = parts[0].lower()
    if command == "deps-list":
        deps_list(session_id)
        return True
    if command == "deps-install":
        if len(parts) == 2 and parts[1] == "-a":
            deps_install(None, all_flag=True, session_id=session_id)
        elif len(parts) != 2:
            typer.echo("Usage: deps-install <module|number> OR deps-install -a")
        else:
            deps_install(parts[1], session_id=session_id)
        return True
    if command == "deps-ignore":
        if len(parts) == 2 and parts[1] == "-a":
            deps_ignore(None, all_flag=True, session_id=session_id)
        elif len(parts) != 2:
            typer.echo("Usage: deps-ignore <module|number> OR deps-ignore -a")
        else:
            deps_ignore(parts[1], session_id=session_id)
        return True
    return False


def deps_list(session_id: Optional[str] = None, all_statuses: bool = False) -> None:
    """打印依赖申请列表；传入 session_id 时只看当前窗口。"""
    status = None if all_statuses else "pending"
    if session_id:
        typer.echo(dependency_text(session_id=session_id, status=status))
    else:
        typer.echo(all_dependency_text(status=status))


def deps_install(
    ref: Optional[str] = None,
    all_flag: bool = False,
    session_id: Optional[str] = None,
) -> None:
    """安装待处理依赖；-a 会安装目标窗口中的全部 pending 申请。"""
    if all_flag is True:
        if not session_id and ref:
            session_id = resolve_dependency_list_ref(ref)
        if not session_id:
            raise typer.BadParameter("-a requires a target dependency list/window id")
        rows = list(dependency_rows(session_id=session_id, status="pending"))
        if not rows:
            typer.echo(f"No dependency requests for memory window: {session_id}")
            return
        for row in rows:
            install_dependency_row(row)
        return

    if not ref:
        raise typer.BadParameter("Missing dependency name")
    if session_id:
        row = resolve_dependency_by_ref(ref, session_id)
    else:
        row = resolve_dependency_globally(ref)
    install_dependency_row(row)


def deps_ignore(
    ref: Optional[str] = None,
    target: Optional[str] = None,
    all_flag: bool = False,
    session_id: Optional[str] = None,
) -> None:
    """忽略待处理依赖；主菜单可按模块全局忽略，也可限定某个窗口。"""
    if all_flag is True:
        if not session_id and ref:
            session_id = resolve_dependency_list_ref(ref)
        if not session_id:
            raise typer.BadParameter("-a requires a target dependency list/window id")
        deleted = _agent_database().delete_dependency_requests_by_session(session_id)
        typer.echo(f"Ignored {deleted} dependency request(s) for memory window: {session_id}")
        return

    if isinstance(target, str) and target:
        session_id = resolve_dependency_list_ref(target)

    if ref and not session_id:
        db = _agent_database()
        row = resolve_dependency_globally(ref)
        deleted = db.delete_dependency_requests_by_module(row["module_name"])
        typer.echo(
            f"Ignored {deleted} dependency request(s) for module: "
            f"{row['module_name']} -> {row['package_name']}"
        )
        return

    if not ref or not session_id:
        raise typer.BadParameter(
            "Usage: deps-ignore <module> OR deps-ignore <module> <window-id> "
            "or task-window deps-ignore <dependency>"
        )
    row = resolve_dependency_by_ref(ref, session_id)
    _agent_database().delete_dependency_request(session_id, row["module_name"])
    typer.echo(f"Ignored dependency request: {row['module_name']} -> {row['package_name']}")


def install_dependency_row(row: dict) -> None:
    """执行 pip install，并在成功后清理所有窗口中的同模块申请。"""
    session_id = row["session_id"]
    module_name = row["module_name"]
    package_name = row["package_name"]
    validate_package_name(package_name)

    typer.echo(f"Installing package '{package_name}' for missing module '{module_name}'...")
    completed = subprocess.run(
        [sys.executable, "-m", "pip", "install", package_name],
        capture_output=True,
        text=True,
        check=False,
    )

    db = _agent_database()
    if completed.returncode == 0:
        deleted = db.delete_dependency_requests_by_module(module_name)
        typer.echo(f"Installed {package_name}")
        typer.echo(f"Removed {deleted} pending request(s) for module '{module_name}' across all memory windows.")
    else:
        error = completed.stderr[-4000:] if completed.stderr else "pip install failed"
        db.update_dependency_status(session_id, module_name, "failed", error)
        typer.echo(f"Failed to install {package_name}")
        typer.echo(error)


def validate_package_name(package_name: str) -> None:
    """只允许普通包名字符，避免把危险参数传给 pip。"""
    if not re.match(r"^[A-Za-z0-9_.-]+$", package_name):
        raise ValueError(f"Unsafe package name: {package_name}")


def _agent_database() -> LocalDatabase:
    """打开 agent.sqlite3 并确保基础表已初始化。"""
    settings = get_settings()
    db = LocalDatabase(settings.local_db_path)
    db.initialize()
    return db
