from __future__ import annotations

"""文件工具：限制 Agent 只能读写项目工作区内的文件。"""

from pathlib import Path

from langchain_core.tools import tool


def _resolve_inside_workspace(workspace: Path, user_path: str) -> Path:
    """把用户路径解析到工作区内；越界访问会被拒绝。"""
    candidate = Path(user_path)
    if not candidate.is_absolute():
        candidate = workspace / candidate
    resolved = candidate.resolve()
    if workspace not in resolved.parents and resolved != workspace:
        raise ValueError(f"Path escapes workspace: {user_path}")
    return resolved


def _resolve_output_path(workspace: Path, user_path: str) -> Path:
    """解析生成文件路径，并强制要求写入 output/。"""
    target = _resolve_inside_workspace(workspace, user_path)
    output_dir = (workspace / "output").resolve()
    if output_dir not in target.parents and target != output_dir:
        raise ValueError(f"Generated files must be written under output/: {user_path}")
    return target


def build_file_tools(workspace: Path):
    """构造目录列表、文本读取和文本写入三个文件工具。"""
    workspace = workspace.resolve()

    @tool
    def list_directory(path: str = ".") -> str:
        """List files and directories under a workspace-relative path. Use "." for the project root, not "/"."""
        target = _resolve_inside_workspace(workspace, path)
        if not target.exists():
            return f"Path does not exist: {path}"
        if not target.is_dir():
            return f"Not a directory: {path}"
        entries = []
        for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            kind = "dir" if item.is_dir() else "file"
            entries.append(f"{kind}\t{item.relative_to(workspace)}")
        return "\n".join(entries) or "(empty)"

    @tool
    def read_text_file(path: str, max_chars: int = 12000) -> str:
        """Read a UTF-8 text file from the workspace."""
        target = _resolve_inside_workspace(workspace, path)
        if not target.exists():
            return f"File does not exist: {path}"
        if not target.is_file():
            return f"Not a file: {path}"
        text = target.read_text(encoding="utf-8")
        # 限制单次返回长度，避免大文件把上下文窗口塞满。
        if len(text) > max_chars:
            return text[:max_chars] + f"\n... truncated, total chars={len(text)}"
        return text

    @tool
    def write_text_file(path: str, content: str) -> str:
        """Write UTF-8 text content to output/. Generated files must be under output/."""
        target = _resolve_output_path(workspace, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} chars to {target.relative_to(workspace)}"

    return [list_directory, read_text_file, write_text_file]
