from __future__ import annotations

"""RAG 知识库封装，负责管理 Chroma 向量库和 SQLite 元数据。"""

import hashlib
from functools import lru_cache
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

try:
    from langchain_huggingface import HuggingFaceEmbeddings
except ImportError:
    from langchain_community.embeddings import HuggingFaceEmbeddings

from agent.config import Settings
from agent.db.local_database import LocalDatabase
from agent.tools.file_tools import _read_text_with_fallback


class KnowledgeBase:
    """把文本切块、embedding、向量存储和元数据记录包装成统一接口。"""

    def __init__(
        self,
        persist_dir: Path,
        rag_db_path: Path | None = None,
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
        embedding_device: str = "cpu",
        collection_name: str = "hybrid_agent_kb_default",
        rag_id: str = "default",
    ):
        """初始化 embedding 模型、Chroma 集合和文本切分器。"""
        self.persist_dir = persist_dir
        self.rag_id = rag_id
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.local_db = LocalDatabase(rag_db_path) if rag_db_path else None
        if self.local_db:
            self.local_db.initialize_rag()
        try:
            self.embeddings = HuggingFaceEmbeddings(
                model_name=embedding_model,
                model_kwargs={"device": embedding_device},
            )
        except Exception as exc:
            raise RuntimeError(
                f"Unable to load embedding model: {embedding_model}. "
                "If this is a local model, check that EMBEDDING_MODEL points to an existing directory. "
                "Otherwise ensure the machine can access HuggingFace or configure a valid model name."
            ) from exc
        self.store = Chroma(
            collection_name=collection_name,
            embedding_function=self.embeddings,
            persist_directory=str(self.persist_dir),
        )
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=700,
            chunk_overlap=120,
            separators=["\n\n", "\n", "。", ".", " ", ""],
        )

    def add_text(self, source: str, title: str, text: str, encoding: str = "utf-8") -> list[str]:
        """把已经提取好的文本写入 RAG；PDF/Office 导入会先提取文本再调用这里。"""
        return self._add_text_chunks(source, title, text, encoding=encoding, append=False)

    def append_text(self, source: str, title: str, text: str, encoding: str = "utf-8") -> list[str]:
        """向已有 RAG source 追加文本和 chunk；source 不存在时等价于新增。"""
        return self._add_text_chunks(source, title, text, encoding=encoding, append=True)

    def _add_text_chunks(self, source: str, title: str, text: str, encoding: str, append: bool) -> list[str]:
        """把文本切块后写入 Chroma 和 SQLite；append=True 时保留旧 chunk。"""
        documents = [Document(page_content=text, metadata={"source": source, "encoding": encoding})]
        chunks = self.splitter.split_documents(documents)
        offset = self.local_db.count_chunks(source, rag_id=self.rag_id) if append and self.local_db else 0
        for index, chunk in enumerate(chunks):
            chunk.metadata["source"] = source
            chunk.metadata["chunk_index"] = offset + index
        ids = [
            _stable_doc_id(self.rag_id, source, chunk.page_content, offset + index)
            for index, chunk in enumerate(chunks)
        ]
        if chunks:
            self.store.add_documents(chunks, ids=ids)
            if self.local_db:
                full_text = "\n\n".join(doc.page_content for doc in documents)
                chunk_rows = [
                    (chunk_id, offset + index, chunk.page_content)
                    for index, (chunk_id, chunk) in enumerate(zip(ids, chunks))
                ]
                if append:
                    self.local_db.append_document_content(source, title, full_text, rag_id=self.rag_id)
                    self.local_db.append_chunks(source, chunk_rows, rag_id=self.rag_id)
                else:
                    self.local_db.save_document(source, title, full_text, rag_id=self.rag_id)
                    self.local_db.replace_chunks(source, chunk_rows, rag_id=self.rag_id)
        return ids

    def source_exists(self, source: str) -> bool:
        """检查某个 source 是否已经存在于知识库中。"""
        if self.local_db:
            return self.local_db.document_exists(source, rag_id=self.rag_id)
        return bool(self.store.get(where={"source": source}).get("ids", []))

    def source_for_path(self, path: Path) -> str:
        """把文件路径转换为 RAG source，当前只使用文件名和扩展名。"""
        return path.name

    def delete_source(self, source: str) -> int:
        """删除指定 source 的 Chroma 向量和 SQLite 元数据。"""
        matches = self.store.get(where={"source": source})
        ids = matches.get("ids", [])
        if ids:
            self.store.delete(ids=ids)
        if self.local_db:
            _document_count, metadata_chunk_count = self.local_db.delete_document(source, rag_id=self.rag_id)
            return max(len(ids), metadata_chunk_count)
        return len(ids)

    def delete_all_sources(self) -> int:
        """删除所有 RAG 向量和 SQLite 元数据，返回删除的向量 chunk 数量。"""
        matches = self.store.get()
        ids = matches.get("ids", [])
        if ids:
            self.store.delete(ids=ids)
        if self.local_db:
            self.local_db.delete_all_documents(rag_id=self.rag_id)
        return len(ids)

    def search(self, query: str, k: int = 4) -> list[Document]:
        """在 Chroma 中做相似度检索。"""
        return self.store.similarity_search(query, k=k)

    def answer_context(self, query: str, k: int = 4) -> str:
        """把检索结果拼成可放入 Agent 回答上下文的文本。"""
        docs = self.search(query, k=k)
        if not docs:
            return "No relevant documents found."
        blocks = []
        for idx, doc in enumerate(docs, start=1):
            source = doc.metadata.get("source", "unknown")
            blocks.append(f"[{idx}] source={source}\n{doc.page_content}")
        return "\n\n".join(blocks)


def get_knowledge_base(settings: Settings, rag_id: str = "default") -> KnowledgeBase:
    """返回进程内缓存的 KnowledgeBase，避免交互模式下反复加载 embedding 模型。"""
    return _cached_knowledge_base(
        str(settings.rag_persist_dir),
        str(settings.rag_db_path),
        settings.embedding_model,
        settings.embedding_device,
        rag_id,
    )


def clear_knowledge_base_cache() -> int:
    """清理已缓存的 KnowledgeBase 实例，并返回清理数量。"""
    info = _cached_knowledge_base.cache_info()
    _cached_knowledge_base.cache_clear()
    return info.currsize


@lru_cache(maxsize=4)
def _cached_knowledge_base(
    persist_dir: str,
    rag_db_path: str,
    embedding_model: str,
    embedding_device: str,
    rag_id: str,
) -> KnowledgeBase:
    """按关键配置缓存知识库实例，配置变化时会生成新的缓存项。"""
    return KnowledgeBase(
        Path(persist_dir),
        Path(rag_db_path),
        embedding_model,
        embedding_device,
        collection_name=_collection_name(rag_id),
        rag_id=rag_id,
    )


def _stable_doc_id(rag_id: str, source: str, content: str, index: int) -> str:
    """基于 RAG 库、source、chunk 序号和内容生成稳定 id，避免不同库之间冲突。"""
    digest = hashlib.sha1(f"{rag_id}:{source}:{index}:{content}".encode("utf-8")).hexdigest()
    return digest


def _collection_name(rag_id: str) -> str:
    """把用户 RAG id 转换为 Chroma collection 名。"""
    digest = hashlib.sha1(rag_id.encode("utf-8")).hexdigest()[:12]
    return f"hybrid_agent_kb_{digest}"
