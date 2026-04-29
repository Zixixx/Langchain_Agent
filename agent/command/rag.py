from __future__ import annotations

"""RAG 命令处理：导入文档、列出 source、删除 source 和相似度搜索。"""

from dataclasses import dataclass
from pathlib import Path

import typer

from agent.config import get_settings
from agent.db.local_database import LocalDatabase


@dataclass(frozen=True)
class RagImportResult:
    """记录单个文件导入 RAG 后的结果，便于汇总输出。"""

    path: Path
    source: str
    chunk_count: int
    skipped: bool = False


def supported_text_files(path: Path) -> list[Path]:
    """把文件或目录解析为可用 UTF-8 读取的文本文件列表。"""
    if path.is_file():
        return [path] if is_utf8_text_file(path) else []
    if path.is_dir():
        return [item for item in sorted(path.rglob("*")) if item.is_file() and is_utf8_text_file(item)]
    raise ValueError(f"Path does not exist: {path}")


def is_utf8_text_file(path: Path) -> bool:
    """快速尝试读取文件，判断它是否适合作为文本导入 RAG。"""
    try:
        with path.open("r", encoding="utf-8") as handle:
            handle.read(4096)
        return True
    except UnicodeDecodeError:
        return False
    except OSError:
        return False


def rag_documents_text(database: LocalDatabase) -> str:
    """从 agent.sqlite3 读取 RAG 文档元数据并格式化展示。"""
    database.initialize()
    rows = database.list_documents()
    if not rows:
        return "No RAG documents."

    lines = ["RAG documents:"]
    for index, row in enumerate(rows, start=1):
        lines.append(
            f"{index}. source={row['source']} | title={row['title']} "
            f"| chunks={row['chunk_count']} | updated_at={row['updated_at']}"
        )
    return "\n".join(lines)


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
            raise ValueError(f"RAG source already exists: {source}")
        if exists and if_exists == "replace":
            kb.delete_source(source)
        if exists and if_exists == "append":
            results.append(RagImportResult(path=file_path, source=source, chunk_count=0, skipped=True))
            continue
        ids = kb.add_path(file_path)
        results.append(RagImportResult(path=file_path, source=source, chunk_count=len(ids)))
    return results


def add(path: Path, if_exists: str = "replace") -> None:
    """实现 rag-add 命令：导入文档并输出 chunk 统计。"""
    # RAG 依赖较重，只在真正执行 RAG 命令时导入 KnowledgeBase。
    from agent.rag.knowledge_base import KnowledgeBase

    kb = KnowledgeBase.from_settings(get_settings())
    try:
        results = import_rag_path(kb, path, if_exists=if_exists)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if not results:
        typer.echo(f"No supported UTF-8 text files found: {path}")
        return

    total_chunks = sum(result.chunk_count for result in results)
    skipped = sum(1 for result in results if result.skipped)
    for result in results:
        if result.skipped:
            typer.echo(f"Skipped existing source: {result.path}")
        else:
            typer.echo(f"Added {result.chunk_count} chunks from {result.path}")
    imported = len(results) - skipped
    typer.echo(f"Imported {imported} document(s), skipped {skipped}, {total_chunks} chunk(s) total.")


def list_documents() -> None:
    """实现 rag-list 命令：列出已导入的文档 source。"""
    db = LocalDatabase(get_settings().local_db_path)
    typer.echo(rag_documents_text(db))


def delete(source: str) -> None:
    """实现 rag-delete 命令：删除指定 source 的向量和元数据。"""
    from agent.rag.knowledge_base import KnowledgeBase

    kb = KnowledgeBase.from_settings(get_settings())
    deleted = kb.delete_source(source)
    typer.echo(f"Deleted {deleted} chunks for source: {source}")


def search(query: str, k: int = 4) -> None:
    """实现 rag-search 命令：打印最相似的若干 chunk。"""
    from agent.rag.knowledge_base import KnowledgeBase

    kb = KnowledgeBase.from_settings(get_settings())
    docs = kb.search(query, k=k)
    for idx, doc in enumerate(docs, start=1):
        typer.echo(f"\n[{idx}] {doc.metadata.get('source', 'unknown')}")
        typer.echo(doc.page_content[:800])
