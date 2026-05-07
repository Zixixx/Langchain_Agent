from __future__ import annotations

"""RAG 命令处理：管理多个知识库，并导入、列出、删除和搜索文档。"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import typer

from agent.config import get_settings
from agent.db.local_database import LocalDatabase
from agent.tools.file_tools import (
    LEGACY_OFFICE_SUFFIXES,
    MODERN_OFFICE_SUFFIXES,
    _read_legacy_office_text_content,
    _read_modern_office_text,
    _read_pdf_text_content,
    _read_text_with_fallback,
)


RAG_PDF_SUFFIXES = {".pdf"}
RAG_OFFICE_SUFFIXES = LEGACY_OFFICE_SUFFIXES | MODERN_OFFICE_SUFFIXES


@dataclass(frozen=True)
class RagImportResult:
    """记录单个文件导入 RAG 后的结果，便于汇总输出。"""

    path: Path
    source: str
    chunk_count: int
    error: str | None = None


def generate_rag_id() -> str:
    """生成带时间戳和随机后缀的唯一 RAG 库 id。"""
    while True:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        rag_id = f"rag-{stamp}-{uuid4().hex[:6]}"
        if not rag_library_exists(rag_id):
            return rag_id


def rag_library_exists(rag_id: str) -> bool:
    """检查指定 RAG 库是否存在。"""
    return _rag_database().rag_library_exists(rag_id)


def create_rag_library(rag_id: str | None = None) -> str:
    """新建 RAG 库；未传 id 时自动生成。"""
    target = rag_id or generate_rag_id()
    db = _rag_database()
    if db.rag_library_exists(target):
        raise ValueError(f"RAG library already exists: {target}")
    db.create_rag_library(target)
    return target


def ensure_rag_library(rag_ref: str) -> tuple[str, str]:
    """为 rag-add 解析目标库；不存在时自动创建时间戳命名的新库。"""
    db = _rag_database()
    try:
        rag_id = resolve_rag_ref(rag_ref)
    except ValueError:
        rag_id = generate_rag_id()
        db.create_rag_library(rag_id)
        return rag_id, f"RAG library not found: {rag_ref}\nCreated RAG library: {rag_id}"
    return rag_id, ""


def resolve_rag_ref(ref: str) -> str:
    """把 RAG 库编号或 id 解析为 rag_id；数字会先尝试编号，再尝试同名 id。"""
    rows = rag_library_rows()
    ids = [row["rag_id"] for row in rows]
    if ref.isdigit():
        index = int(ref)
        if 1 <= index <= len(ids):
            return ids[index - 1]
        if ref in ids:
            return ref
        raise ValueError(f"RAG library number or id does not exist: {ref}")
    if ref not in ids:
        raise ValueError(f"RAG library does not exist: {ref}")
    return ref


def rag_library_rows() -> list[dict]:
    """读取所有 RAG 库。"""
    return _rag_database().list_rag_libraries()


def rag_libraries_text() -> str:
    """格式化所有 RAG 库列表。"""
    rows = rag_library_rows()
    if not rows:
        return "No RAG libraries."
    lines = ["RAG libraries:"]
    for index, row in enumerate(rows, start=1):
        lines.append(
            f"{index}. id={row['rag_id']} | documents={row['document_count']} "
            f"| chunks={row['chunk_count']} | updated_at={row['updated_at']}"
        )
    return "\n".join(lines)


def supported_text_files(path: Path) -> list[Path]:
    """把文件或目录解析为可导入 RAG 的文件列表。"""
    if path.is_file():
        return [path] if is_supported_rag_file(path) else []
    if path.is_dir():
        return [item for item in sorted(path.rglob("*")) if item.is_file() and is_supported_rag_file(item)]
    raise ValueError(f"Path does not exist: {path}")


def is_supported_rag_file(path: Path) -> bool:
    """判断文件是否可导入 RAG；PDF/Office 走专用读取器，普通文本才做编码检测。"""
    suffix = path.suffix.lower()
    if suffix in RAG_PDF_SUFFIXES or suffix in RAG_OFFICE_SUFFIXES:
        return True
    if _looks_binary(path):
        return False
    try:
        _read_text_with_fallback(path)
        return True
    except UnicodeDecodeError:
        return False
    except OSError:
        return False


def _looks_binary(path: Path, sample_size: int = 8192) -> bool:
    """读取少量字节做二进制判断，避免目录导入时把未知二进制文件当文本处理。"""
    data = path.read_bytes()[:sample_size]
    if not data:
        return False
    if b"\x00" in data:
        return True
    control_bytes = sum(1 for byte in data if byte < 32 and byte not in {9, 10, 13})
    return control_bytes / len(data) > 0.30


def read_rag_document(path: Path) -> tuple[str, str]:
    """按文件类型提取可写入 RAG 的文本，返回文本和来源说明。"""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _read_pdf_text_content(path), "pypdf"
    if suffix in LEGACY_OFFICE_SUFFIXES:
        settings = get_settings()
        return _read_legacy_office_text_content(path, settings.libreoffice_path), "office"
    if suffix in MODERN_OFFICE_SUFFIXES:
        return _read_modern_office_text(path), "office-openxml"
    if _looks_binary(path):
        raise ValueError(f"Unsupported binary RAG file type: {path}")
    return _read_text_with_fallback(path)


def rag_documents_text(rag_id: str | None = None) -> str:
    """从 rag.sqlite3 读取 RAG 文档元数据并格式化展示。"""
    db = _rag_database()
    if rag_id:
        rows = db.list_documents(rag_id=rag_id)
        if not rows:
            return f"No RAG documents in library: {rag_id}"
        lines = [f"RAG documents for library: {rag_id}"]
        for index, row in enumerate(rows, start=1):
            lines.append(_format_document_row(index, row))
        return "\n".join(lines)

    rows = db.list_documents()
    if not rows:
        return "No RAG documents."
    lines = ["RAG documents in all libraries:"]
    for index, row in enumerate(rows, start=1):
        lines.append(_format_document_row(index, row, include_rag=True))
    return "\n".join(lines)


def _format_document_row(index: int, row: dict, include_rag: bool = False) -> str:
    """格式化一条 RAG 文档记录。"""
    prefix = f"{index}. "
    rag_part = f"rag_id={row['rag_id']} | " if include_rag else ""
    return (
        f"{prefix}{rag_part}source={row['source']} | title={row['title']} "
        f"| chunks={row['chunk_count']} | updated_at={row['updated_at']}"
    )


def import_rag_path(kb, path: Path, if_exists: str = "replace") -> list[RagImportResult]:
    """按 replace/append/fail 策略把文件或目录导入 KnowledgeBase。"""
    if if_exists not in {"fail", "replace", "append"}:
        raise ValueError("if_exists must be one of: fail, replace, append")

    files = supported_text_files(path)
    results: list[RagImportResult] = []
    for file_path in files:
        source = kb.source_for_path(file_path)
        exists = kb.source_exists(source)
        if exists and if_exists == "fail":
            results.append(RagImportResult(file_path, source, 0, error=f"RAG source already exists: {source}"))
            continue
        try:
            text, encoding = read_rag_document(file_path)
            if exists and if_exists == "replace":
                kb.delete_source(source)
            if exists and if_exists == "append":
                ids = kb.append_text(source=source, title=file_path.stem, text=text, encoding=encoding)
            else:
                ids = kb.add_text(source=source, title=file_path.stem, text=text, encoding=encoding)
        except Exception as exc:
            results.append(RagImportResult(file_path, source, 0, error=str(exc)))
            continue
        results.append(RagImportResult(file_path, source, len(ids)))
    return results


def _knowledge_base(rag_id: str):
    """懒加载并复用指定 RAG 库的 KnowledgeBase。"""
    from agent.rag.knowledge_base import get_knowledge_base

    return get_knowledge_base(get_settings(), rag_id=rag_id)


def new(rag_id: str | None = None) -> str:
    """实现 rag-new 命令。"""
    return f"Created RAG library: {create_rag_library(rag_id)}"


def add(path: Path, rag_ref: str, if_exists: str = "replace") -> str:
    """实现 rag-add 命令，导入文档并输出 chunk 统计。"""
    rag_id, message = ensure_rag_library(rag_ref)
    output = _add_to_library(path, rag_id, if_exists)
    return "\n".join(part for part in (message, output) if part)


def add_all(path: Path, if_exists: str = "replace") -> str:
    """把文档或目录导入所有已存在的 RAG 库。"""
    rows = rag_library_rows()
    if not rows:
        return "No RAG libraries. Create one first with: rag-new [rag_id]"
    messages = []
    for row in rows:
        messages.append(_add_to_library(path, row["rag_id"], if_exists))
    return "\n\n".join(messages)


def _add_to_library(path: Path, rag_id: str, if_exists: str) -> str:
    """导入文档到指定库并输出 chunk 统计。"""
    try:
        results = import_rag_path(_knowledge_base(rag_id), path, if_exists=if_exists)
    except (RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    if not results:
        return f"No supported RAG files found: {path}"

    total_chunks = sum(result.chunk_count for result in results)
    failed = sum(1 for result in results if result.error)
    lines = []
    for result in results:
        if result.error:
            lines.append(f"Failed {result.path}: {result.error}")
        else:
            lines.append(f"Added {result.chunk_count} chunks from {result.path} to RAG library '{rag_id}'")
    imported = len(results) - failed
    lines.append(f"Imported {imported} document(s), failed {failed}, {total_chunks} chunk(s) total.")
    return "\n".join(lines)


def list_libraries(rag_ref: str | None = None, all_flag: bool = False) -> str:
    """实现 rag-list 命令：展示 RAG 库统计信息。"""
    if not rag_ref:
        return rag_libraries_text()
    rag_id = resolve_rag_ref(rag_ref)
    for index, row in enumerate(rag_library_rows(), start=1):
        if row["rag_id"] == rag_id:
            return (
                "RAG library:\n"
                f"{index}. id={row['rag_id']} | documents={row['document_count']} "
                f"| chunks={row['chunk_count']} | updated_at={row['updated_at']}"
            )
    return f"RAG library does not exist: {rag_id}"


def show_documents(rag_ref: str | None = None, all_flag: bool = False) -> str:
    """实现 rag-show 命令：展示 RAG 文档具体信息。"""
    if all_flag:
        return rag_documents_text(None)
    if not rag_ref:
        raise ValueError("Usage: rag-show <rag_id|number> OR rag-show -a")
    return rag_documents_text(resolve_rag_ref(rag_ref))


def remove(source: str | None = None, rag_ref: str | None = None, all_flag: bool = False) -> str:
    """实现 rag-remove 命令：删除文档但保留库。"""
    if all_flag:
        if rag_ref:
            rag_id = resolve_rag_ref(rag_ref)
            deleted = _knowledge_base(rag_id).delete_all_sources()
            _clear_rag_cache()
            return f"Cleared RAG library '{rag_id}': {deleted} chunk(s)."
        total = 0
        for row in rag_library_rows():
            total += _knowledge_base(row["rag_id"]).delete_all_sources()
        _clear_rag_cache()
        return f"Cleared all RAG libraries: {total} chunk(s)."

    if not source:
        raise ValueError("Usage: rag-remove <source> [rag_id|number] OR rag-remove -a [rag_id|number]")
    if rag_ref:
        rag_id = resolve_rag_ref(rag_ref)
        if not _rag_database().document_exists(source, rag_id=rag_id):
            return f"RAG source does not exist in library '{rag_id}': {source}"
        deleted = _knowledge_base(rag_id).delete_source(source)
        _clear_rag_cache()
        return f"Deleted source '{source}' from RAG library '{rag_id}' ({deleted} chunk(s))."
    total = 0
    lines = []
    for row in rag_library_rows():
        if not _rag_database().document_exists(source, rag_id=row["rag_id"]):
            continue
        deleted = _knowledge_base(row["rag_id"]).delete_source(source)
        total += deleted
        lines.append(f"Deleted source '{source}' from RAG library '{row['rag_id']}' ({deleted} chunk(s)).")
    _clear_rag_cache()
    if not lines:
        lines.append(f"RAG source does not exist in any library: {source}")
    return "\n".join(lines)


def delete(rag_ref: str | None = None, all_flag: bool = False) -> str:
    """实现 rag-delete -a 命令：删除库本身。"""
    db = _rag_database()
    if all_flag:
        if rag_ref:
            rag_id = resolve_rag_ref(rag_ref)
            deleted_chunks = _knowledge_base(rag_id).delete_all_sources()
            db.delete_rag_library(rag_id)
            _clear_rag_cache()
            return f"Deleted RAG library '{rag_id}': {deleted_chunks} chunk(s)."
        total_chunks = 0
        for row in rag_library_rows():
            total_chunks += _knowledge_base(row["rag_id"]).delete_all_sources()
        db.delete_all_rag_libraries()
        _clear_rag_cache()
        return f"Deleted all RAG libraries: {total_chunks} chunk(s)."
    raise ValueError("Usage: rag-delete -a [rag_id|number]")


def delete_source(source: str, rag_ref: str | None = None) -> str:
    """删除 source；如果目标库删除后为空，则同时删除该库。"""
    if rag_ref:
        rag_id = resolve_rag_ref(rag_ref)
        _deleted, _deleted_library, message = _delete_source_and_empty_library(source, rag_id)
        _clear_rag_cache()
        return message

    matched = 0
    deleted_libraries = 0
    lines = []
    for row in list(rag_library_rows()):
        deleted, deleted_library, message = _delete_source_and_empty_library(source, row["rag_id"])
        matched += 1 if deleted > 0 else 0
        deleted_libraries += 1 if deleted_library else 0
        if deleted > 0:
            lines.append(message)
    if matched == 0:
        lines.append(f"RAG source does not exist in any library: {source}")
    elif deleted_libraries:
        lines.append(f"Deleted {deleted_libraries} empty RAG library/libraries after deleting source '{source}'.")
    _clear_rag_cache()
    return "\n".join(lines)


def _delete_source_and_empty_library(source: str, rag_id: str) -> tuple[int, bool, str]:
    """删除指定库中的 source，并在库为空时删除库记录。"""
    if not _rag_database().document_exists(source, rag_id=rag_id):
        return 0, False, f"RAG source does not exist in library '{rag_id}': {source}"

    deleted_chunks = _knowledge_base(rag_id).delete_source(source)
    lines = [f"Deleted source '{source}' from RAG library '{rag_id}' ({deleted_chunks} chunk(s))."]

    remaining = _rag_database().list_documents(rag_id=rag_id)
    if remaining:
        return 1, False, "\n".join(lines)

    removed_chunks = _rag_database().delete_rag_library(rag_id)
    lines.append(f"Deleted empty RAG library '{rag_id}' after removing source '{source}'.")
    return 1 + removed_chunks, True, "\n".join(lines)


def _clear_rag_cache() -> None:
    """RAG 写操作后清理进程内 KnowledgeBase 缓存，避免旧 collection 状态残留。"""
    from agent.rag.knowledge_base import clear_knowledge_base_cache

    clear_knowledge_base_cache()


def search(query: str, rag_ref: str | None = None, k: int = 4) -> str:
    """实现 rag-search 命令；未指定库时依次搜索全部库。"""
    if rag_ref:
        rag_id = resolve_rag_ref(rag_ref)
        return _search_results_text(rag_id, query, k)

    rows = rag_library_rows()
    if not rows:
        return "No RAG libraries."
    return "\n\n".join(_search_results_text(row["rag_id"], query, k) for row in rows)


def _search_results_text(rag_id: str, query: str, k: int) -> str:
    """格式化指定 RAG 库的搜索结果。"""
    docs = _knowledge_base(rag_id).search(query, k=k)
    if not docs:
        return f"RAG library: {rag_id}\n(no results)"
    lines = [f"RAG library: {rag_id}"]
    for idx, doc in enumerate(docs, start=1):
        lines.append(f"\n[{idx}] {doc.metadata.get('source', 'unknown')}")
        lines.append(doc.page_content[:800])
    return "\n".join(lines)


def _rag_database() -> LocalDatabase:
    """打开 rag.sqlite3 并确保 RAG 元数据表已初始化。"""
    db = LocalDatabase(get_settings().rag_db_path)
    db.initialize_rag()
    return db
