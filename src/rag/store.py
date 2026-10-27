"""索引存储与增量更新：按 chunk 内容指纹做 diff，只重建真正变化的 chunk。

为什么要有它：规则库每改一条，原来的做法是整库重建（64 chunk 现在很快，
但真实规则库上千 chunk 时就会变成每次改一行等几十秒）。这里用内容哈希定位变化，
`python -m src.rag.reindex` 会告诉你"改了几条、跳过几条"。

存储格式：JSON（标准库可读、可 diff、可入库），字段与 corpus 的 chunk 一致，
额外存 `_fingerprint` 便于快速比对。
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import time

DEFAULT_STORE = os.path.join("var", "rag", "index.json")


def fingerprint(chunks: list[dict]) -> dict[str, str]:
    """chunk_id → 内容指纹（只看会影响检索的字段）。"""
    out = {}
    for c in chunks:
        key = str(c.get("chunk_id", ""))
        payload = json.dumps({k: c.get(k) for k in ("text", "section", "rule_id", "hs")},
                             ensure_ascii=False, sort_keys=True)
        out[key] = hashlib.md5(payload.encode("utf-8")).hexdigest()[:12]
    return out


class IndexStore:
    def __init__(self, path: str = DEFAULT_STORE):
        self.path = path
        self._chunks: list[dict] = []
        self._fp: dict[str, str] = {}

    # ---------- 读写 ----------
    def load(self) -> list[dict]:
        if not os.path.exists(self.path):
            self._chunks, self._fp = [], {}
            return []
        with io.open(self.path, encoding="utf-8") as f:
            data = json.load(f)
        self._chunks = list(data.get("chunks") or [])
        self._fp = dict(data.get("fingerprint") or fingerprint(self._chunks))
        return self._chunks

    def save(self, chunks: list[dict] | None = None) -> str:
        if chunks is not None:
            self._chunks = list(chunks)
        self._fp = fingerprint(self._chunks)
        os.makedirs(os.path.dirname(os.path.abspath(self.path)) or ".", exist_ok=True)
        with io.open(self.path, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"fingerprint": self._fp, "chunks": self._chunks},
                      f, ensure_ascii=False, indent=1)
        return self.path

    # ---------- diff ----------
    def diff(self, new_chunks: list[dict], old_chunks: list[dict] | None = None) -> dict:
        """返回 {added, updated, removed, unchanged, changed_ids}。"""
        old = self._chunks if old_chunks is None else list(old_chunks)
        old_fp = fingerprint(old)
        new_fp = fingerprint(new_chunks)
        added = sorted(set(new_fp) - set(old_fp))
        removed = sorted(set(old_fp) - set(new_fp))
        updated = sorted(k for k in set(new_fp) & set(old_fp) if new_fp[k] != old_fp[k])
        unchanged = len(set(new_fp) & set(old_fp)) - len(updated)
        return {"added": added, "updated": updated, "removed": removed,
                "unchanged": unchanged,
                "changed": len(added) + len(updated) + len(removed)}

    def apply(self, new_chunks: list[dict]) -> dict:
        """把新语料落盘；返回 diff 统计（调用方据此决定是否重建索引）。"""
        stats = self.diff(new_chunks)
        self.save(new_chunks)
        return stats


def rebuild(store_path: str = DEFAULT_STORE, full: bool = False) -> dict:
    """从语料重建：有变化才写盘；full=True 强制重写。"""
    from .corpus import load_corpus

    t0 = time.perf_counter()
    corpus = load_corpus()
    store = IndexStore(store_path)
    old = store.load()
    stats = store.diff(corpus, old) if old and not full else {
        "added": [c["chunk_id"] for c in corpus], "updated": [], "removed": [],
        "unchanged": 0, "changed": len(corpus)}
    if stats["changed"] or full or not old:
        store.save(corpus)
    return {"stats": stats, "chunks": len(corpus), "old_chunks": len(old),
            "full": bool(full), "ms": round((time.perf_counter() - t0) * 1000, 1),
            "path": store_path}
