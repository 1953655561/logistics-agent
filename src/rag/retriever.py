"""检索器：对上层只暴露 search()，实现 ports.RetrieverPort。"""
from __future__ import annotations

from .corpus import load_corpus
from .index import Index


class Retriever:
    def __init__(self, chunks: list[dict] | None = None):
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
