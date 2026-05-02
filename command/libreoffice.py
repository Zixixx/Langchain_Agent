from __future__ import annotations

"""LibreOffice install command for Windows/Linux/macOS package managers."""

import platform
import shutil
import subprocess
from pathlib import Path

import typer

from agent.config import project_root


def install() -> None:
    """Detect existing LibreOffice or install it, then refresh cached Agent executors."""
    configured_path = _read_env_libreoffice_path()
    if configured_path is not None:
        if _is_valid_libreoffice_path(configured_path):
            typer.echo(f"LibreOffice already configured: {configured_path}")
        else:
            typer.echo(f"LIBREOFFICE_PATH is set but invalid: {configured_path}")
            _detect_or_install_and_update_env()
    else:
        _detect_or_install_and_update_env()

    _clear_all_agent_executor_cache()


def _detect_or_install_and_update_env() -> None:
    """Detect LibreOffice from the system, or install it and write the detected path to .env."""
    existing_path = _detect_installed_libreoffice_path(required=False)
    if existing_path:
        typer.echo(f"LibreOffice already detected: {existing_path}")
        _update_env_libreoffice_path(existing_path)
        return
    _install_with_package_manager()
    _update_env_libreoffice_path(_detect_installed_libreoffice_path(required=True))


def _install_with_package_manager() -> None:
    """Install LibreOffice through the system package manager."""
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
    """Return platform-specific package-manager install command."""
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
    """Use sudo on Linux when available and not already running as root."""
    try:
        import os

        if hasattr(os, "geteuid") and os.geteuid() == 0:
            return command
    except Exception:
        pass
    return ["sudo", *command] if shutil.which("sudo") else command


def _detect_installed_libreoffice_path(required: bool) -> Path | None:
    """Return a path suitable for LIBREOFFICE_PATH after installation."""
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
    """Read LIBREOFFICE_PATH from .env and resolve relative paths from project root."""
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
    """Check whether a configured LibreOffice path points to a usable executable or install dir."""
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
    """Set LIBREOFFICE_PATH in the project .env file."""
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
    typer.echo(f"Updated .env: LIBREOFFICE_PATH={libreoffice_path}")


def _clear_all_agent_executor_cache() -> None:
    """Clear all cached Agent executors after LibreOffice configuration changes."""
    from agent.command import chat as chat_commands

    deleted = chat_commands.clear_executor_cache()
    if deleted:
        typer.echo(f"Cleared {deleted} cached Agent executor(s).")
