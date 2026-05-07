from __future__ import annotations

"""跨平台 LibreOffice 检测与安装命令。"""

import os
import platform
import shutil
import subprocess
from pathlib import Path

import typer

from agent.config import project_root


def install() -> None:
    """检测已有 LibreOffice；不存在时安装，并刷新运行时缓存。"""
    configured_path = _read_env_libreoffice_path()
    if configured_path is not None:
        if _is_valid_libreoffice_path(configured_path):
            typer.echo(f"LibreOffice already configured: {configured_path}")
            _refresh_runtime_config(configured_path)
        else:
            typer.echo(f"LIBREOFFICE_PATH is set but invalid: {configured_path}")
            _detect_or_install_and_update_env()
    else:
        _detect_or_install_and_update_env()

    _clear_runtime_caches()


def check() -> None:
    """只检查 LibreOffice 路径；如果能检测到安装位置，则写入 .env。"""
    configured_path = _read_env_libreoffice_path()
    if configured_path is not None and _is_valid_libreoffice_path(configured_path):
        typer.echo(f"LibreOffice path is valid: {configured_path}")
        _refresh_runtime_config(configured_path)
        _clear_runtime_caches()
        return

    if configured_path is not None:
        typer.echo(f"LIBREOFFICE_PATH is set but invalid: {configured_path}")
    else:
        typer.echo("LIBREOFFICE_PATH is empty or missing.")

    detected_path = _detect_installed_libreoffice_path(required=False)
    if detected_path is None:
        typer.echo("LibreOffice was not detected. Run libreoffice-install to install it, or set LIBREOFFICE_PATH manually.")
        return

    typer.echo(f"LibreOffice detected: {detected_path}")
    _update_env_libreoffice_path(detected_path)
    _clear_runtime_caches()


def _clear_runtime_caches() -> None:
    """LibreOffice 配置变化后清理 Agent 和 RAG 缓存。"""
    _clear_all_agent_executor_cache()
    _clear_rag_cache()


def _detect_or_install_and_update_env() -> None:
    """先从系统中检测 LibreOffice；不存在时安装，并把路径写入 .env。"""
    existing_path = _detect_installed_libreoffice_path(required=False)
    if existing_path:
        typer.echo(f"LibreOffice already detected: {existing_path}")
        _update_env_libreoffice_path(existing_path)
        return
    _install_with_package_manager()
    _update_env_libreoffice_path(_detect_installed_libreoffice_path(required=True))


def _install_with_package_manager() -> None:
    """通过当前系统可用的包管理器安装 LibreOffice。"""
    command = _package_manager_install_command()
    if command is None:
        raise RuntimeError(
            "LibreOffice was not detected and no supported package manager was found. "
            "Install LibreOffice manually, then set LIBREOFFICE_PATH in .env."
        )
    typer.echo("LibreOffice was not detected. Installing through system package manager:")
    typer.echo(" ".join(command))
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"LibreOffice package-manager install failed with exit code {completed.returncode}")
    typer.echo("LibreOffice package-manager install finished.")


def _package_manager_install_command() -> list[str] | None:
    """返回当前平台对应的 LibreOffice 安装命令。"""
    system = platform.system().lower()
    if system == "windows":
        if shutil.which("winget"):
            return ["winget", "install", "-e", "--id", "TheDocumentFoundation.LibreOffice"]
        if shutil.which("choco"):
            return ["choco", "install", "libreoffice-fresh", "-y"]
        return None
    if system == "linux":
        if shutil.which("apt"):
            return _with_sudo(["apt", "install", "-y", "libreoffice"])
        if shutil.which("dnf"):
            return _with_sudo(["dnf", "install", "-y", "libreoffice"])
        if shutil.which("yum"):
            return _with_sudo(["yum", "install", "-y", "libreoffice"])
        if shutil.which("pacman"):
            return _with_sudo(["pacman", "-S", "--noconfirm", "libreoffice-fresh"])
        if shutil.which("zypper"):
            return _with_sudo(["zypper", "--non-interactive", "install", "libreoffice"])
    if system == "darwin":
        if shutil.which("brew"):
            return ["brew", "install", "--cask", "libreoffice"]
    return None


def _with_sudo(command: list[str]) -> list[str]:
    """Linux 非 root 环境下优先给安装命令加 sudo。"""
    try:
        import os

        if hasattr(os, "geteuid") and os.geteuid() == 0:
            return command
    except Exception:
        pass
    return ["sudo", *command] if shutil.which("sudo") else command


def _detect_installed_libreoffice_path(required: bool) -> Path | None:
    """检测可写入 LIBREOFFICE_PATH 的 LibreOffice 路径。"""
    system = platform.system().lower()
    if system == "windows":
        executable = shutil.which("soffice") or shutil.which("libreoffice")
        if executable:
            return Path(executable)
        for install_dir in (Path(r"C:\Program Files\LibreOffice"), Path(r"C:\Program Files (x86)\LibreOffice")):
            if install_dir.exists():
                return install_dir
    if system == "linux":
        executable = shutil.which("libreoffice") or shutil.which("soffice")
        if executable:
            return Path(executable)
        for candidate in (Path("/usr/bin/libreoffice"), Path("/usr/bin/soffice")):
            if candidate.exists():
                return candidate
    if system == "darwin":
        executable = shutil.which("libreoffice") or shutil.which("soffice")
        if executable:
            return Path(executable)
        for candidate in (
            Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
            Path("/Applications/LibreOffice.app"),
        ):
            if candidate.exists():
                return candidate
    if required:
        raise RuntimeError("LibreOffice install finished, but no LibreOffice executable was detected.")
    return None


def _read_env_libreoffice_path() -> Path | None:
    """读取 .env 中的 LIBREOFFICE_PATH，并按项目根目录解析相对路径。"""
    env_path = project_root() / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or not stripped.startswith("LIBREOFFICE_PATH="):
            continue
        value = stripped.split("=", 1)[1].strip().strip("\"'")
        if not value:
            return None
        path = Path(value)
        return path if path.is_absolute() else project_root() / path
    return None


def _is_valid_libreoffice_path(path: Path) -> bool:
    """判断 LibreOffice 配置路径是否指向可用程序或安装目录。"""
    if path.is_file():
        return True
    if not path.is_dir():
        return False
    executable_names = (
        "soffice.exe",
        "libreoffice.exe",
        "soffice",
        "libreoffice",
    )
    for search_dir in (path, path / "program", path / "Contents" / "MacOS"):
        for name in executable_names:
            if (search_dir / name).is_file():
                return True
    return False


def _update_env_libreoffice_path(libreoffice_path: Path) -> None:
    """把 LIBREOFFICE_PATH 写入项目 .env 文件。"""
    env_path = project_root() / ".env"
    line = f"LIBREOFFICE_PATH={libreoffice_path}\n"
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
    else:
        lines = []

    replaced = False
    updated: list[str] = []
    for existing in lines:
        if existing.startswith("LIBREOFFICE_PATH="):
            updated.append(line)
            replaced = True
        else:
            updated.append(existing)
    if not replaced:
        if updated and not updated[-1].endswith(("\n", "\r")):
            updated[-1] += "\n"
        updated.append(line)
    env_path.write_text("".join(updated), encoding="utf-8")
    _refresh_runtime_config(libreoffice_path)
    typer.echo(f"Updated .env: LIBREOFFICE_PATH={libreoffice_path}")


def _refresh_runtime_config(libreoffice_path: Path) -> None:
    """刷新当前进程环境变量，让配置读取立即生效。"""
    os.environ["LIBREOFFICE_PATH"] = str(libreoffice_path)


def _clear_all_agent_executor_cache() -> None:
    """LibreOffice 配置变化后清理所有已缓存的 Agent 执行器。"""
    from agent.command import chat as chat_commands

    deleted = chat_commands.clear_executor_cache()
    if deleted:
        typer.echo(f"Cleared {deleted} cached Agent executor(s).")


def _clear_rag_cache() -> None:
    """LibreOffice 配置变化后清理已缓存的 RAG 知识库对象。"""
    try:
        from agent.rag.knowledge_base import clear_knowledge_base_cache
    except ImportError as exc:
        typer.echo(f"Skipped RAG cache cleanup because RAG dependencies are unavailable: {exc}")
        return

    deleted = clear_knowledge_base_cache()
    if deleted:
        typer.echo(f"Cleared {deleted} cached RAG knowledge base instance(s).")
