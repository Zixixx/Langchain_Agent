from __future__ import annotations

"""Python 沙箱工具：用临时工程目录执行脚本，并只把 result/ 合并回真实 output/。"""

import re
import shutil
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from langchain_core.tools import tool

from agent.db.local_database import LocalDatabase
from agent.tools.file_tools import _read_text_with_fallback, _resolve_input_or_output_path


BLOCKED_INSTALL_PATTERNS = (
    r"\bpip\s+install\b",
    r"\bpython\s+-m\s+pip\s+install\b",
    r"\buv\s+pip\s+install\b",
    r"\bconda\s+install\b",
    r"\bmamba\s+install\b",
)

BLOCKED_SYSTEM_PATTERNS = (
    r"\bshutdown(?:\.exe)?\b",
    r"\breboot\b",
    r"\bformat(?:\.com|\.exe)?\s+[a-z]:",
    r"\bmkfs(?:\.[a-z0-9_+-]+)?\b",
    r"\bdiskpart(?:\.exe)?\b",
)


class SandboxPolicyError(ValueError):
    """代码在进入子进程前没有通过基础安全策略。"""


@dataclass(frozen=True)
class SandboxRunResult:
    """记录一次沙箱运行的结构化结果。"""

    stdout: str
    stderr: str
    exit_code: int | str
    result_synced: list[str]


def build_python_tools(
    workspace: Path,
    timeout_seconds: int | None,
    db_path: Path | None = None,
    session_id: str = "",
):
    """构造 Python 执行工具，使用本地轻量工程隔离沙箱。"""
    workspace = workspace.resolve()

    @tool
    def show_python_sandbox_policy() -> str:
        """Show Python sandbox runtime directories, result sync rules, blocked commands, and timeout."""
        timeout_text = "unlimited" if timeout_seconds is None else f"{timeout_seconds}s"
        return python_sandbox_policy_text(timeout_text)

    @tool
    def run_python_sandbox(code: str) -> str:
        """Run Python code in the local sandbox. Save final files under result/."""
        try:
            _check_code_policy(code)
        except SandboxPolicyError as exc:
            install_packages = _extract_install_packages(code)
            if install_packages:
                return _record_blocked_install_requests(install_packages, db_path, session_id, str(exc))
            return f"Sandbox policy rejected the code: {exc}"
        result = _run_local_engineering_sandbox(workspace, code, timeout_seconds)
        return _format_execution_result(result, db_path, session_id)

    @tool
    def run_python_script(path: str) -> str:
        """Run an existing .py script from input/ or output/. The script should save final files under result/."""
        try:
            script_path = _resolve_input_or_output_path(workspace, path)
            if script_path.suffix.lower() != ".py":
                raise ValueError(f"Only .py scripts can be executed: {path}")
            if not script_path.is_file():
                raise ValueError(f"Script does not exist: {path}")
            code, _encoding = _read_text_with_fallback(script_path)
            _check_code_policy(code)
        except SandboxPolicyError as exc:
            install_packages = _extract_install_packages(code) if "code" in locals() else []
            if install_packages:
                return _record_blocked_install_requests(install_packages, db_path, session_id, str(exc))
            return f"Sandbox policy rejected the script: {exc}"
        except Exception as exc:
            return f"Failed to load script: {exc}"
        result = _run_local_engineering_sandbox(workspace, code, timeout_seconds)
        return _format_execution_result(result, db_path, session_id)

    return [show_python_sandbox_policy, run_python_sandbox, run_python_script]


def _run_local_engineering_sandbox(workspace: Path, code: str, timeout_seconds: int | None) -> SandboxRunResult:
    """创建 temp/input/output/result，执行 script.py，并把 result/ 合并回真实 output/。"""
    temp_root = workspace / "temp"
    real_input = workspace / "input"
    real_output = workspace / "output"
    sandbox_input = temp_root / "input"
    sandbox_output = temp_root / "output"
    sandbox_result = temp_root / "result"
    script_path = temp_root / "script.py"
    exit_code: int | str = "not_run"
    stdout = ""
    stderr = ""
    result_synced: list[str] = []

    try:
        _reset_directory(temp_root)
        _copy_directory_snapshot(real_input, sandbox_input)
        _copy_directory_snapshot(real_output, sandbox_output)
        sandbox_result.mkdir(parents=True, exist_ok=True)
        script_path.write_text(code, encoding="utf-8")

        try:
            completed = subprocess.run(
                [sys.executable, str(script_path)],
                cwd=temp_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                check=False,
            )
            exit_code = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as exc:
            exit_code = "timeout"
            stdout = _stringify_timeout_output(exc.stdout)
            stderr = _stringify_timeout_output(exc.stderr)
            timeout_text = "unlimited" if timeout_seconds is None else f"{timeout_seconds}s"
            stderr = (stderr + "\n" if stderr else "") + f"Execution timed out after {timeout_text}."

        result_synced = _sync_result_to_output(sandbox_result, real_output)
    finally:
        _remove_tree(temp_root, ignore_errors=True)

    return SandboxRunResult(
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        result_synced=result_synced,
    )


def _reset_directory(path: Path) -> None:
    """删除并重建目录，用于确保每次运行的 temp 都是全新环境。"""
    if path.exists():
        _remove_tree(path, ignore_errors=False)
    path.mkdir(parents=True, exist_ok=True)


def _remove_tree(path: Path, ignore_errors: bool) -> None:
    """递归删除目录；Windows 下遇到只读/短暂占用时做少量重试。"""
    if not path.exists():
        return
    last_error: Exception | None = None
    for _attempt in range(5):
        try:
            _rmtree_with_retry_callback(path)
            return
        except Exception as exc:
            last_error = exc
            time.sleep(0.2)
    if not ignore_errors and last_error:
        raise last_error


def _rmtree_with_retry_callback(path: Path) -> None:
    """递归删除目录。"""
    shutil.rmtree(path, onexc=_make_writable_and_retry)


def _make_writable_and_retry(function, path: str, _exception) -> None:
    """把只读文件改为可写后重试删除。"""
    try:
        Path(path).chmod(stat.S_IWRITE)
        function(path)
    except Exception:
        raise


def _copy_directory_snapshot(source: Path, target: Path) -> None:
    """复制目录快照；源目录不存在时创建空目标目录。"""
    if source.exists():
        shutil.copytree(source, target)
    else:
        target.mkdir(parents=True, exist_ok=True)


def _sync_result_to_output(result_dir: Path, output_dir: Path) -> list[str]:
    """把 result/ 顶层文件和目录合并到真实 output/，重名时追加 _new。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    synced: list[str] = []
    if not result_dir.exists():
        return synced

    for item in sorted(result_dir.iterdir(), key=lambda path: path.name):
        destination = _next_available_output_path(output_dir / item.name)
        if item.is_dir():
            shutil.copytree(item, destination)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)
        synced.append(f"result/{item.name} -> output/{destination.name}")
    return synced


def _next_available_output_path(path: Path) -> Path:
    """目标路径存在时不断追加 _new，直到找到未占用的文件或目录名。"""
    candidate = path
    while candidate.exists():
        if candidate.suffix:
            candidate = candidate.with_name(f"{candidate.stem}_new{candidate.suffix}")
        else:
            candidate = candidate.with_name(f"{candidate.name}_new")
    return candidate


def _check_code_policy(code: str) -> None:
    """只做少量硬限制：禁止安装依赖和明显系统级危险命令。"""
    lowered_code = code.lower()
    for pattern in BLOCKED_INSTALL_PATTERNS:
        if re.search(pattern, lowered_code):
            raise SandboxPolicyError(f"Blocked dependency installation command: {pattern}")
    for pattern in BLOCKED_SYSTEM_PATTERNS:
        if re.search(pattern, lowered_code):
            raise SandboxPolicyError(f"Blocked dangerous system command: {pattern}")


def _format_execution_result(
    result: SandboxRunResult,
    db_path: Path | None,
    session_id: str,
) -> str:
    """格式化 Python 子进程执行结果，并在缺少依赖时追加安装申请提示。"""
    synced_text = "\n".join(result.result_synced) if result.result_synced else "(none)"
    output = (
        f"exit_code: {result.exit_code}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}\n"
        f"result_synced:\n{synced_text}"
    )
    missing_module = _extract_missing_module(result.stderr)
    if missing_module:
        if db_path and session_id:
            database = LocalDatabase(db_path)
            database.initialize()
            database.add_dependency_request(session_id, missing_module, missing_module, result.stderr)
        output += (
            "\n\nDEPENDENCY_INSTALL_REQUEST\n"
            f"missing_module: {missing_module}\n"
            "The Agent must infer the correct pip/PyPI package name and tell the user to approve it with deps-show/deps-install."
        )
    return output


def python_sandbox_policy_text(timeout_text: str = "") -> str:
    """把新沙箱目录语义和少量限制格式化，供 Agent 写代码前查看。"""
    install_patterns = ", ".join(pattern.strip("\\b") for pattern in BLOCKED_INSTALL_PATTERNS)
    system_patterns = ", ".join(pattern.strip("\\b") for pattern in BLOCKED_SYSTEM_PATTERNS)
    sections = [
        "Python sandbox policy:",
        "- isolation: local temporary-directory isolation, not a security container.",
        f"- timeout: {timeout_text or 'configured by PYTHON_SANDBOX_TIMEOUT'}",
        "- runtime cwd is a fresh temp/ directory created for each run.",
        "- temp/input/ is a copied snapshot of the real input/ directory.",
        "- temp/output/ is a copied snapshot of the real output/ directory.",
        "- temp/result/ starts empty and is the only directory merged back to the real output/ directory.",
        "- You may read and modify sandbox input/ and output/ copies, but those changes are temporary.",
        "- Always save final generated files under result/.",
        "- After execution, result/ is merged into real output/. Name conflicts append _new repeatedly until unique.",
        "- The whole temp/ directory is deleted after each run.",
        f"- blocked dependency install commands: {install_patterns}",
        f"- blocked dangerous system commands: {system_patterns}",
        "- Do not install packages yourself; request dependencies with request_dependency_install.",
    ]
    return "\n".join(sections)


def _record_blocked_install_requests(
    install_packages: list[str],
    db_path: Path | None,
    session_id: str,
    error_message: str,
) -> str:
    """当代码里出现安装命令时，拒绝执行并记录待用户批准的依赖申请。"""
    requests = []
    for package_name in install_packages:
        module_name = _package_to_module(package_name)
        if db_path and session_id:
            database = LocalDatabase(db_path)
            database.initialize()
            database.add_dependency_request(session_id, module_name, package_name, error_message)
        requests.append(f"- missing_module: {module_name}, suggested_package: {package_name}")
    return (
        f"Sandbox policy rejected the code: {error_message}\n\n"
        "DEPENDENCY_INSTALL_REQUEST\n"
        + "\n".join(requests)
        + "\nInstall only after user approval. In the CLI, run: deps-show, then deps-install <module|number>."
    )


def _extract_missing_module(stderr: str) -> str | None:
    """从 ModuleNotFoundError 的 stderr 中提取缺失模块名。"""
    match = re.search(r"No module named ['\"]([^'\"]+)['\"]", stderr)
    if not match:
        return None
    return match.group(1).split(".")[0]


def _extract_install_packages(code: str) -> list[str]:
    """从被拒绝的安装命令中提取用户试图安装的包名。"""
    packages: list[str] = []
    for match in re.finditer(
        r"(?:pip|python\s+-m\s+pip|uv\s+pip)\s+install\s+([A-Za-z0-9_.\-\s]+)",
        code,
        re.IGNORECASE,
    ):
        packages.extend(_clean_package_tokens(match.group(1).split()))
    for match in re.finditer(
        r"(?:conda|mamba)\s+install\s+(?:-y\s+)?([A-Za-z0-9_.\-\s]+)",
        code,
        re.IGNORECASE,
    ):
        packages.extend(_clean_package_tokens(match.group(1).split()))
    return list(dict.fromkeys(packages))


def _clean_package_tokens(tokens: list[str]) -> list[str]:
    """清理安装命令中的包名 token，跳过选项参数。"""
    packages: list[str] = []
    for token in tokens:
        package_name = token.strip().strip("\"'")
        if package_name.startswith("-"):
            continue
        if re.match(r"^[A-Za-z0-9_.-]+$", package_name):
            packages.append(package_name)
    return packages


def _package_to_module(package_name: str) -> str:
    """把 pip 包名粗略转换成模块名，用于记录依赖申请。"""
    return package_name.replace("-", "_")


def _stringify_timeout_output(value: str | bytes | None) -> str:
    """兼容 TimeoutExpired 中 stdout/stderr 可能是 bytes 的情况。"""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
