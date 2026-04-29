from __future__ import annotations

"""RAG LangChain 工具：供 Agent 在对话中增删查知识库。"""

from pathlib import Path

from langchain_core.tools import tool

from agent.config import Settings
from agent.rag.knowledge_base import KnowledgeBase


def build_rag_tools(settings: Settings):
    """构造 RAG 文档导入、删除和搜索工具。"""

    def kb() -> KnowledgeBase:
        """按当前配置创建知识库对象，确保读取最新持久化数据。"""
        return KnowledgeBase.from_settings(settings)

    @tool
    def rag_add_document(path: str) -> str:
        """Add a UTF-8 text/markdown document to the RAG knowledge base."""
        try:
            ids = kb().add_path(Path(path))
            return f"Added {len(ids)} chunks from {path}"
        except Exception as exc:
            return f"rag_add_document failed: {exc}"

    @tool
    def rag_delete_document(source: str) -> str:
        """Delete all RAG chunks for a source path."""
        try:
            deleted = kb().delete_source(source)
            return f"Deleted {deleted} chunks for source: {source}"
        except Exception as exc:
            return f"rag_delete_document failed: {exc}"

    @tool
    def rag_search(query: str, k: int = 4) -> str:
        """Search the knowledge base and return relevant document chunks."""
        try:
            return kb().answer_context(query, k=k)
        except Exception as exc:
            return f"rag_search failed: {exc}"

    return [rag_add_document, rag_delete_document, rag_search]
