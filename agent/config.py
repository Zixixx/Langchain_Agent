from __future__ import annotations

"""项目配置模块：集中读取 .env 和路径配置，供命令层、工具层和模型层共享。"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    """集中保存运行配置，避免各模块到处直接读取环境变量。"""

    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
    workspace: Path
    rag_persist_dir: Path
    local_db_path: Path
    csv_db_path: Path
    embedding_model: str
    embedding_device: str
    libreoffice_path: Path | None
    python_sandbox_timeout: int


def project_root() -> Path:
    """根据 agent 包位置反推项目根目录。"""
    return Path(__file__).resolve().parents[1]


def get_settings() -> Settings:
    """读取环境变量并转换成绝对路径配置。"""
    root = project_root()
    # 相对路径统一挂到项目根目录下，避免从不同工作目录启动时读写位置漂移。
    workspace = Path(os.getenv("AGENT_WORKSPACE", "."))
    if not workspace.is_absolute():
        workspace = root / workspace

    rag_persist_dir = Path(os.getenv("RAG_PERSIST_DIR", "data"))
    if not rag_persist_dir.is_absolute():
        rag_persist_dir = root / rag_persist_dir

    local_db_path = Path(os.getenv("LOCAL_DB_PATH", "data/agent.sqlite3"))
    if not local_db_path.is_absolute():
        local_db_path = root / local_db_path

    csv_db_path = Path(os.getenv("CSV_DB_PATH", "data/csv.sqlite3"))
    if not csv_db_path.is_absolute():
        csv_db_path = root / csv_db_path

    libreoffice_path_value = os.getenv("LIBREOFFICE_PATH", "").strip()
    libreoffice_path = Path(libreoffice_path_value) if libreoffice_path_value else None
    if libreoffice_path and not libreoffice_path.is_absolute():
        libreoffice_path = root / libreoffice_path

    embedding_model = _resolve_embedding_model(root, os.getenv("EMBEDDING_MODEL", ""))

    return Settings(
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        workspace=workspace.resolve(),
        rag_persist_dir=rag_persist_dir.resolve(),
        local_db_path=local_db_path.resolve(),
        csv_db_path=csv_db_path.resolve(),
        embedding_model=embedding_model,
        embedding_device=os.getenv("EMBEDDING_DEVICE", "cpu"),
        libreoffice_path=libreoffice_path.resolve() if libreoffice_path else None,
        python_sandbox_timeout=int(os.getenv("PYTHON_SANDBOX_TIMEOUT", "30")),
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
