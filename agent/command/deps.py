from __future__ import annotations

"""依赖申请命令：查看、安装或忽略 Agent/沙箱记录的缺包请求。"""

import re
import subprocess
import sys
from typing import Optional

import typer

from agent.config import get_settings
from agent.db.local_database import LocalDatabase
from agent.command import memory as memory_commands


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
    """把所有记忆窗口的依赖申请按 session_id 分组展示，包括空列表窗口。"""
    grouped: dict[str, list[dict]] = {row["session_id"]: [] for row in memory_commands.memory_window_rows()}
    for row in all_dependency_rows(status=status):
        grouped.setdefault(row["session_id"], []).append(row)
    if not grouped:
        return "No memory windows."
    lines = ["Dependency request lists:"]
    for list_index, (session_id, session_rows) in enumerate(grouped.items(), start=1):
        lines.append(f"{list_index}. id={session_id}")
        if not session_rows:
            lines.append("   (empty)")
            continue
        for dep_index, row in enumerate(session_rows, start=1):
            lines.append(
                f"   {dep_index}. module={row['module_name']} | package={row['package_name']} "
                f"| status={row['status']} | updated_at={row['updated_at']}"
            )
    return "\n".join(lines)


def dependency_summary_text(session_id: str, status: str | None = "pending") -> str:
    """把单个窗口的依赖申请统计格式化成 CLI 可读文本。"""
    rows = dependency_rows(session_id=session_id, status=status)
    return f"Dependency list: id={session_id} | pending={len(rows)}"


def all_dependency_summary_text(status: str | None = "pending") -> str:
    """把所有窗口的依赖申请统计格式化成 CLI 可读文本。"""
    windows = memory_commands.memory_window_rows()
    if not windows:
        return "No memory windows."
    lines = ["Dependency lists:"]
    for index, window in enumerate(windows, start=1):
        rows = dependency_rows(session_id=window["session_id"], status=status)
        lines.append(f"{index}. id={window['session_id']} | pending={len(rows)}")
    return "\n".join(lines)


def resolve_dependency_by_ref(ref: str, session_id: str) -> dict:
    """在任务窗口内按序号、模块名或包名定位一条依赖申请。"""
    rows = dependency_rows(session_id=session_id, status="pending")
    if ref.isdigit():
        index = int(ref)
        if 1 <= index <= len(rows):
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


def deps_list(session_id: Optional[str] = None, all_flag: bool = True) -> str:
    """打印依赖申请统计；传入 session_id 时只看当前窗口。"""
    status = None if not all_flag else "pending"
    if session_id:
        return dependency_summary_text(session_id=session_id, status=status)
    return all_dependency_summary_text(status=status)


def deps_show(session_id: Optional[str] = None, all_flag: bool = True) -> str:
    """打印依赖申请具体清单；传入 session_id 时只看当前窗口。"""
    status = None if not all_flag else "pending"
    if session_id:
        return dependency_text(session_id=session_id, status=status)
    return all_dependency_text(status=status)


def deps_install(
    ref: Optional[str] = None,
    all_flag: bool = False,
    session_id: Optional[str] = None,
) -> str:
    """安装待处理依赖；-a 会安装目标窗口中的全部 pending 申请。"""
    if all_flag is True:
        if not session_id:
            installed_any = False
            for window in memory_commands.memory_window_rows():
                rows = list(dependency_rows(session_id=window["session_id"], status="pending"))
                for row in rows:
                    installed_any = True
                    install_dependency_row(row)
            if not installed_any:
                return "No dependency requests."
            return "Installed all pending dependency requests."
        rows = list(dependency_rows(session_id=session_id, status="pending"))
        if not rows:
            return f"No dependency requests for memory window: {session_id}"
        return "\n".join(install_dependency_row(row) for row in rows)

    if not ref:
        raise typer.BadParameter("Missing dependency name")
    if session_id:
        row = resolve_dependency_by_ref(ref, session_id)
    else:
        row = resolve_dependency_globally(ref)
    return install_dependency_row(row)


def deps_ignore(
    ref: Optional[str] = None,
    all_flag: bool = False,
    session_id: Optional[str] = None,
) -> str:
    """忽略待处理依赖；主菜单可按模块全局忽略，也可限定某个窗口。"""
    if all_flag is True:
        if not session_id:
            deleted = 0
            for row in memory_commands.memory_window_rows():
                deleted += _agent_database().delete_dependency_requests_by_session(row["session_id"])
            return f"Ignored {deleted} dependency request(s) for all memory windows."
        deleted = _agent_database().delete_dependency_requests_by_session(session_id)
        return f"Ignored {deleted} dependency request(s) for memory window: {session_id}"

    if ref and not session_id:
        db = _agent_database()
        row = resolve_dependency_globally(ref)
        deleted = db.delete_dependency_requests_by_module(row["module_name"])
        return (
            f"Ignored {deleted} dependency request(s) for module: "
            f"{row['module_name']} -> {row['package_name']}"
        )

    if not ref or not session_id:
        raise typer.BadParameter(
            "Usage: deps-ignore <module> OR deps-ignore <module> <window-id> "
            "or task-window deps-ignore <dependency>"
        )
    row = resolve_dependency_by_ref(ref, session_id)
    _agent_database().delete_dependency_request(session_id, row["module_name"])
    return f"Ignored dependency request: {row['module_name']} -> {row['package_name']}"


def install_dependency_row(row: dict) -> str:
    """执行 pip install，并在成功后清理所有窗口中的同模块申请。"""
    session_id = row["session_id"]
    module_name = row["module_name"]
    package_name = row["package_name"]
    validate_package_name(package_name)

    completed = subprocess.run(
        [sys.executable, "-m", "pip", "install", package_name],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    db = _agent_database()
    lines = [f"Installing package '{package_name}' for missing module '{module_name}'..."]
    if completed.returncode == 0:
        deleted = db.delete_dependency_requests_by_module(module_name)
        lines.append(f"Installed {package_name}")
        lines.append(f"Removed {deleted} pending request(s) for module '{module_name}' across all memory windows.")
        return "\n".join(lines)

    error = completed.stderr[-4000:] if completed.stderr else "pip install failed"
    db.update_dependency_status(session_id, module_name, "failed", error)
    lines.append(f"Failed to install {package_name}")
    lines.append(error)
    return "\n".join(lines)


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
