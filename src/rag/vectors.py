"""向量存储：sqlite 持久化 + 余弦检索 + embedding provider 可插拔。

定位：**自建向量表，不是向量数据库服务**（没有 pgvector/Milvus 依赖）。
这样做的用处是把「换 embedding」变成一次配置改动，并能用同一批 query 量化差异
（见 `evals/vectors.py` 的 provider 对比）。

只用标准库：sqlite3 + array + math。
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
from array import array

from .index import _bucket, expand_query
from .tokenize import tokenize

DIM = 64

SCHEMA = """
CREATE TABLE IF NOT EXISTS vectors (
    chunk_id TEXT PRIMARY KEY,
    vec      BLOB NOT NULL,
    text     TEXT NOT NULL,
    meta     TEXT NOT NULL
);
"""


class HashEmbedding:
    """与现有 hybrid 检索同源的哈希词袋向量（基线 provider）。"""

    name = "hash"

    def __init__(self, dim: int = DIM):
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = tokenize(text)
        if not tokens:
            return vec
        for tok in tokens:
            vec[_bucket(tok) % self.dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class SimEmbedding:
    """演示用的「另一种语义向量」：同义词展开 + 字符三元组加权。

    不是真模型，别在报告里说成 embedding 模型；它的价值是证明
    "provider 可插拔 + 可对比"这条路是通的。
    """

    name = "sim"

    def __init__(self, dim: int = DIM):
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        expanded = expand_query(text)
        tokens = tokenize(expanded)
        if not tokens:
            return vec
        for tok in tokens:
            # 二元组权重高、单字权重低，模拟"词更重要"的假设
            weight = 1.6 if len(tok) > 1 else 0.3
            vec[_bucket(tok) % self.dim] += weight
        # 原始 query 再补一次，避免展开后偏离原意
        for tok in tokenize(text):
            vec[_bucket(tok) % self.dim] += 0.2
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


PROVIDERS = {"hash": HashEmbedding, "sim": SimEmbedding}


def get_provider(name: str = "hash"):
    cls = PROVIDERS.get(name, HashEmbedding)
    return cls()


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


class VectorStore:
    def __init__(self, path: str = ":memory:", provider=None):
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        self.path = path
        self.provider = provider or get_provider("hash")
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    # ---------- 写入 ----------
    def upsert(self, chunks: list[dict]) -> int:
        rows = []
        for c in chunks:
            text = str(c.get("text", ""))
            vec = self.provider.embed(text)
            meta = {k: c.get(k) for k in ("section", "rule_id", "hs", "doc", "layer")
                    if c.get(k) is not None}
            rows.append((str(c.get("chunk_id", "")),
                         array("f", vec).tobytes(), text,
                         json.dumps(meta, ensure_ascii=False)))
        self._conn.executemany(
            "INSERT OR REPLACE INTO vectors (chunk_id, vec, text, meta) VALUES (?, ?, ?, ?)",
            rows)
        self._conn.commit()
        return len(rows)

    # ---------- 查询 ----------
    def search(self, query: str, top_k: int = 3) -> list[dict]:
        q = self.provider.embed(query)
        scored = []
        for chunk_id, blob, text, meta in self._conn.execute(
                "SELECT chunk_id, vec, text, meta FROM vectors"):
            vec = list(array("f", blob))
            score = cosine(q, vec)
            if score > 0:
                scored.append((score, chunk_id, text, json.loads(meta)))
        scored.sort(key=lambda x: (-x[0], x[1]))
        out = []
        for score, chunk_id, text, meta in scored[:top_k]:
            item = {"chunk_id": chunk_id, "text": text, "score": round(score, 4)}
            item.update(meta)
            out.append(item)
        return out

    def count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM vectors").fetchone()[0])

    def close(self) -> None:
        self._conn.close()
