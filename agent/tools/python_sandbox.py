from __future__ import annotations

"""Python 沙箱工具：静态检查代码后用子进程执行，并把错误回传给 Agent。"""

import ast
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from langchain_core.tools import tool

from agent.db.local_database import LocalDatabase


# 这些名字和模块会明显扩大沙箱权限，因此在 AST 阶段直接拒绝。
BLOCKED_NAMES = {"eval", "exec", "compile", "__import__", "open", "input"}

BLOCKED_MODULES = {
    "builtins",
    "ensurepip",
    "importlib",
    "os",
    "pip",
    "pkg_resources",
    "subprocess",
    "socket",
    "setuptools",
    "shutil",
    "ctypes",
    "multiprocessing",
    "threading",
    "pathlib",
    "pickle",
    "runpy",
    "venv",
}

BLOCKED_ATTRS = {
    "__dict__",
    "__globals__",
    "__subclasses__",
    "call",
    "check_call",
    "check_output",
    "executable",
    "system",
    "popen",
    "run",
    "run_module",
    "remove",
    "unlink",
    "rmdir",
    "rmtree",
    "rename",
    "replace",
    "chmod",
    "chown",
}

BLOCKED_TEXT_PATTERNS = {
    "__builtins__",
    "__import__",
    "pip install",
    "python -m pip",
    "conda install",
    "mamba install",
    "uv pip install",
}

BLOCKED_STRING_VALUES = {
    "__builtins__",
    "__dict__",
    "__globals__",
    "__import__",
    "__subclasses__",
    "compile",
    "eval",
    "exec",
    "open",
}

# 对常见写文件 API 做路径硬约束，确保生成物进入 output/。
OUTPUT_WRITE_METHODS = {
    "dump",
    "dumpfig",
    "save",
    "savefig",
    "savetxt",
    "to_csv",
    "to_excel",
    "to_feather",
    "to_json",
    "to_markdown",
    "to_parquet",
    "to_pickle",
    "write_bytes",
    "write_text",
}

OUTPUT_PATH_KEYWORDS = {"fname", "filepath_or_buffer", "path", "path_or_buf"}


class SandboxPolicyError(ValueError):
    """代码在进入子进程前没有通过基础安全策略。"""


def _check_code_safety(code: str) -> None:
    """用文本规则和 AST 规则检查代码是否允许进入沙箱执行。"""
    lowered_code = code.lower()
    for pattern in BLOCKED_TEXT_PATTERNS:
        if pattern in lowered_code:
            raise SandboxPolicyError(f"Blocked dependency installation command: {pattern}")

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise SandboxPolicyError(f"SyntaxError: {exc}") from exc

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name.split(".")[0] for alias in node.names]
            if isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module.split(".")[0])
            blocked = sorted(set(names) & BLOCKED_MODULES)
            if blocked:
                raise SandboxPolicyError(f"Blocked import: {', '.join(blocked)}")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_NAMES:
                raise SandboxPolicyError(f"Blocked function call: {node.func.id}")
            if isinstance(node.func, ast.Attribute) and node.func.attr in BLOCKED_ATTRS:
                raise SandboxPolicyError(f"Blocked attribute call: {node.func.attr}")
            _check_output_write_call(node)
        elif isinstance(node, ast.Attribute):
            if node.attr in BLOCKED_ATTRS:
                raise SandboxPolicyError(f"Blocked attribute access: {node.attr}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in BLOCKED_STRING_VALUES:
                raise SandboxPolicyError(f"Blocked dangerous string constant: {node.value}")


def build_python_tools(
    workspace: Path,
    timeout_seconds: int,
    db_path: Path | None = None,
    session_id: str = "",
):
    """构造 Python 沙箱工具，并绑定工作区、超时和当前记忆窗口。"""
    workspace = workspace.resolve()
    output_dir = workspace / "output"

    @tool
    def run_python_sandbox(code: str) -> str:
        """Run Python code in an isolated subprocess. Returns stdout, stderr, and exit code."""
        try:
            _check_code_safety(code)
        except SandboxPolicyError as exc:
            install_packages = _extract_install_packages(code)
            if install_packages:
                return _record_blocked_install_requests(install_packages, db_path, session_id, str(exc))
            return f"Sandbox policy rejected the code: {exc}"

        with tempfile.TemporaryDirectory(prefix="agent_sandbox_") as temp_dir:
            script_path = Path(temp_dir) / "snippet.py"
            script_path.write_text(code, encoding="utf-8")
            output_dir.mkdir(parents=True, exist_ok=True)
            try:
                # 子进程隔离执行，stdout/stderr 会回传给 LLM 用于自动修正。
                completed = subprocess.run(
                    [sys.executable, str(script_path)],
                    cwd=workspace,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                return f"Execution timed out after {timeout_seconds}s.\nstdout:\n{exc.stdout or ''}\nstderr:\n{exc.stderr or ''}"

        output = f"exit_code: {completed.returncode}\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        missing_module = _extract_missing_module(completed.stderr)
        if missing_module:
            output += (
                "\n\nDEPENDENCY_INSTALL_REQUEST\n"
                f"missing_module: {missing_module}\n"
                "The Agent must infer the correct pip/PyPI package name and call "
                "request_dependency_install(module_name, package_name)."
            )
        return output

    return [run_python_sandbox]


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
        + "\nInstall only after user approval. In the CLI, run: deps-list, then deps-install <module|number>."
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
    for match in re.finditer(r"(?:pip|python\s+-m\s+pip|uv\s+pip)\s+install\s+([A-Za-z0-9_.\-\s]+)", code, re.IGNORECASE):
        raw_packages = match.group(1).split()
        for raw_package in raw_packages:
            package_name = raw_package.strip().strip("\"'")
            if package_name.startswith("-"):
                continue
            if re.match(r"^[A-Za-z0-9_.-]+$", package_name):
                packages.append(package_name)
    for match in re.finditer(r"(?:conda|mamba)\s+install\s+(?:-y\s+)?([A-Za-z0-9_.\-\s]+)", code, re.IGNORECASE):
        raw_packages = match.group(1).split()
        for raw_package in raw_packages:
            package_name = raw_package.strip().strip("\"'")
            if package_name.startswith("-"):
                continue
            if re.match(r"^[A-Za-z0-9_.-]+$", package_name):
                packages.append(package_name)
    return list(dict.fromkeys(packages))


def _package_to_module(package_name: str) -> str:
    """把 pip 包名粗略转换成模块名，用于记录依赖申请。"""
    return package_name.replace("-", "_")


def _check_output_write_call(node: ast.Call) -> None:
    """检查保存文件类调用的目标路径是否满足 output/ 规则。"""
    if isinstance(node.func, ast.Attribute):
        method_name = node.func.attr
    elif isinstance(node.func, ast.Name):
        method_name = node.func.id
    else:
        return

    if method_name not in OUTPUT_WRITE_METHODS:
        return

    if node.args:
        _check_output_path_node(method_name, node.args[0])
    for keyword in node.keywords:
        if keyword.arg in OUTPUT_PATH_KEYWORDS:
            _check_output_path_node(method_name, keyword.value)


def _check_output_path_node(method_name: str, path_node: ast.AST) -> None:
    """静态检查写文件路径；复杂表达式会被拒绝以保持规则可验证。"""
    if isinstance(path_node, ast.Constant) and isinstance(path_node.value, str):
        if not _is_output_path_literal(path_node.value):
            raise SandboxPolicyError(f"Generated file writes must target output/: {method_name}({path_node.value!r})")
        return
    if isinstance(path_node, ast.Constant) and path_node.value is None:
        return
    raise SandboxPolicyError(f"Generated file writes must use a literal output/ path for static safety: {method_name}(...)")


def _is_output_path_literal(path_value: str) -> bool:
    """判断字符串字面量是否指向 output/ 目录。"""
    normalized = path_value.replace("\\", "/").lstrip("./")
    return normalized == "output" or normalized.startswith("output/")
