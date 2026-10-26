"""检索引擎：BM25 + 特征哈希向量，混合打分，规则重排。

零依赖、可复现（哈希用 md5，不用内置 hash）。
"""
from __future__ import annotations

import hashlib
import math

from .tokenize import tokenize

DIM = 256
K1 = 1.5
B = 0.75


def _bucket(token: str) -> int:
    return int(hashlib.md5(token.encode("utf-8")).hexdigest()[:8], 16) % DIM


class Index:
    def __init__(self, chunks: list[dict]):
        self.chunks = chunks
        self.tokens = [tokenize(c["text"] + " " + c.get("section", "")) for c in chunks]
        self._build_bm25()
        self._build_vectors()

    # ---------- BM25 ----------
    def _build_bm25(self):
        n = len(self.tokens)
        self.df: dict[str, int] = {}
        for toks in self.tokens:
            for t in set(toks):
                self.df[t] = self.df.get(t, 0) + 1
        self.avgdl = (sum(len(t) for t in self.tokens) / n) if n else 0.0
        self.tf = []
        for toks in self.tokens:
            d: dict[str, int] = {}
            for t in toks:
                d[t] = d.get(t, 0) + 1
            self.tf.append(d)

    def _idf(self, token: str) -> float:
        n = len(self.tokens)
        df = self.df.get(token, 0)
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def bm25(self, query: str) -> list[float]:
        q = tokenize(query)
        scores = []
        for i, tf in enumerate(self.tf):
            dl = len(self.tokens[i])
            s = 0.0
            for t in q:
                f = tf.get(t, 0)
                if not f:
                    continue
                s += self._idf(t) * (f * (K1 + 1)) / (f + K1 * (1 - B + B * dl / (self.avgdl or 1)))
            scores.append(s)
        return scores

    # ---------- 特征哈希向量 ----------
    def _build_vectors(self):
        self.vectors = []
        for tf in self.tf:
            vec = [0.0] * DIM
            for token, f in tf.items():
                vec[_bucket(token)] += (1 + math.log(f)) * self._idf(token)
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            self.vectors.append([v / norm for v in vec])

    def _query_vector(self, query: str) -> list[float]:
        vec = [0.0] * DIM
        for token in tokenize(query):
            vec[_bucket(token)] += self._idf(token)
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def cosine(self, query: str) -> list[float]:
        qv = self._query_vector(query)
        out = []
        for dv in self.vectors:
            out.append(sum(a * b for a, b in zip(qv, dv)))
        return out

    # ---------- 混合 ----------
    def search(self, query: str, top_k: int = 3) -> list[dict]:
        if not self.chunks:
            return []
        bm = self.bm25(query)
        cs = self.cosine(query)
        bmax = max(bm) or 1.0
        scored = []
        q = query.upper()
        for i, chunk in enumerate(self.chunks):
            score = 0.65 * (bm[i] / bmax) + 0.35 * max(cs[i], 0.0)
            # 重排：精确命中规则编号优先级最高
            if chunk.get("rule_id") and chunk["rule_id"] in q:
                score += 1.0
            if chunk.get("hs") and chunk["hs"] in q:
                score += 0.8
            if score > 0:
                scored.append((score, i))
        scored.sort(key=lambda x: (-x[0], x[1]))
        out = []
        for score, i in scored[:top_k]:
            c = dict(self.chunks[i])
            c["score"] = round(score, 4)
            out.append(c)
        return out
