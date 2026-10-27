"""检索器：对上层只暴露 search()，实现 ports.RetrieverPort。"""
from __future__ import annotations

import os

from .corpus import load_corpus
from .index import Index
from .store import IndexStore

# 可选：设置 LOGIAGENT_RAG_STORE 指向增量索引文件，检索就改用落盘索引（而非现读文档）
STORE_ENV = "LOGIAGENT_RAG_STORE"


def _chunks_from_store(path: str) -> list[dict] | None:
    if not path or not os.path.exists(path):
        return None
    chunks = IndexStore(path).load()
    return chunks or None


class Retriever:
    def __init__(self, chunks: list[dict] | None = None):
        if chunks is None:
            chunks = _chunks_from_store(os.environ.get(STORE_ENV, ""))
        self.chunks = chunks if chunks is not None else load_corpus()
        self.index = Index(self.chunks)

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        return self.index.search(query, top_k=top_k)

    def cite(self, chunk_id: str) -> dict | None:
        for c in self.chunks:
            if c["chunk_id"] == chunk_id:
                return c
        return None


_default: Retriever | None = None


def default_retriever() -> Retriever:
    global _default
    if _default is None:
        _default = Retriever()
    return _default
