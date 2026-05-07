from __future__ import annotations

"""项目配置模块：集中读取 .env 和路径配置，供命令层、工具层和模型层共享。"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    """集中保存运行配置，避免各模块读取环境变量。"""

    api_key: str
    base_url: str
    model: str
    workspace: Path
    rag_persist_dir: Path
    rag_db_path: Path
    local_db_path: Path
    table_db_path: Path
    embedding_model: str
    embedding_device: str
    libreoffice_path: Path | None
    python_sandbox_timeout: int | None
    max_input_tokens: int | None


def project_root() -> Path:
    """根据 agent 包位置反推项目根目录。"""
    return Path(__file__).resolve().parents[1]


def get_settings() -> Settings:
    """读取环境变量并转换成绝对路径配置。"""
    root = project_root()
    # 项目运行数据路径固定在仓库内，避免 .env 改错后读写位置漂移。
    workspace = root
    rag_persist_dir = root / "data" / "rag"
    rag_db_path = root / "data" / "rag" / "rag.sqlite3"
    local_db_path = root / "data" / "agent" / "agent.sqlite3"
    table_db_path = root / "data" / "db" / "db.sqlite3"

    libreoffice_path_value = os.getenv("LIBREOFFICE_PATH", "").strip()
    libreoffice_path = Path(libreoffice_path_value) if libreoffice_path_value else None
    if libreoffice_path and not libreoffice_path.is_absolute():
        libreoffice_path = root / libreoffice_path

    embedding_model = _resolve_embedding_model(root, os.getenv("EMBEDDING_MODEL", ""))

    return Settings(
        api_key=os.getenv("API_KEY", ""),
        base_url=os.getenv("BASE_URL", "https://api.deepseek.com"),
        model=os.getenv("MODEL", "deepseek-chat"),
        workspace=workspace.resolve(),
        rag_persist_dir=rag_persist_dir.resolve(),
        rag_db_path=rag_db_path.resolve(),
        local_db_path=local_db_path.resolve(),
        table_db_path=table_db_path.resolve(),
        embedding_model=embedding_model,
        embedding_device=os.getenv("EMBEDDING_DEVICE", "cpu"),
        libreoffice_path=libreoffice_path.resolve() if libreoffice_path else None,
        python_sandbox_timeout=_parse_optional_int(os.getenv("PYTHON_SANDBOX_TIMEOUT", "30")),
        max_input_tokens=_parse_optional_int(os.getenv("MAX_INPUT_TOKENS", "128000")),
    )


def _resolve_embedding_model(root: Path, value: str) -> str:
    """解析 embedding 模型配置：优先本地目录，不存在时保留模型名用于联网下载。"""
    model = value.strip()
    if not model:
        return "sentence-transformers/all-MiniLM-L6-v2"

    model_path = Path(model)
    candidates = [model_path] if model_path.is_absolute() else [root / model_path]
    for candidate in candidates:
        if candidate.is_dir():
            return str(candidate.resolve())

    return model


def _parse_optional_int(value: str | None) -> int | None:
    """解析可为空的整数环境变量；空字符串表示不限制。"""
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return int(stripped)
