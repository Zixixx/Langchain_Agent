from __future__ import annotations

"""RAG LangChain 工具：只向 Agent 暴露库/source 查看和检索能力。"""

from langchain_core.tools import tool

from agent.config import Settings
from agent.rag.knowledge_base import KnowledgeBase, get_knowledge_base
from agent.db.local_database import LocalDatabase


def build_rag_tools(settings: Settings):
    """构造 Agent 可用的只读 RAG 工具。"""

    def kb(rag_id: str) -> KnowledgeBase:
        """复用进程内缓存的知识库对象，避免每次工具调用都重新加载模型。"""
        return get_knowledge_base(settings, rag_id=rag_id)

    def db() -> LocalDatabase:
        """连接 rag.sqlite3，读取 RAG 库和文档 source 元数据。"""
        database = LocalDatabase(settings.rag_db_path)
        database.initialize_rag()
        return database

    @tool
    def rag_knowledge_base_schema() -> str:
        """Return RAG library names and document source names. Use this before choosing rag_id/source."""
        try:
            libraries = db().list_rag_libraries()
            if not libraries:
                return "No RAG libraries."
            lines = ["RAG knowledge bases:"]
            for library in libraries:
                rag_id = library["rag_id"]
                lines.append(
                    f"- rag_id={rag_id} | documents={library['document_count']} "
                    f"| chunks={library['chunk_count']}"
                )
                documents = db().list_documents(rag_id=rag_id)
                if not documents:
                    lines.append("  sources: (empty)")
                    continue
                lines.append("  sources:")
                for document in documents:
                    lines.append(
                        f"  - {document['source']} | title={document['title']} "
                        f"| chunks={document['chunk_count']}"
                    )
            return "\n".join(lines)
        except Exception as exc:
            return f"rag_knowledge_base_schema failed: {exc}"

    @tool
    def rag_search(query: str, rag_id: str = "", k: int = 4) -> str:
        """Search one RAG library by rag_id. If rag_id is empty, search every RAG library."""
        try:
            if rag_id:
                return kb(rag_id).answer_context(query, k=k)
            blocks = []
            for row in db().list_rag_libraries():
                context = kb(row["rag_id"]).answer_context(query, k=k)
                blocks.append(f"RAG library: {row['rag_id']}\n{context}")
            return "\n\n".join(blocks) if blocks else "No RAG libraries."
        except Exception as exc:
            return f"rag_search failed: {exc}"

    return [rag_knowledge_base_schema, rag_search]
