"""向量检索对比：同一批 query、两个 embedding provider，看纯向量检索的召回差异。

注意口径：这里**不含 BM25 混合**，只测向量这一路。它回答的是
"换 embedding 会不会更好 / 好在哪"，而不是端到端召回。

    python evals/vectors.py
"""
from __future__ import annotations

import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from evals.retrieval import QUERIES                         # noqa: E402
from src.rag.corpus import load_corpus                      # noqa: E402
from src.rag.vectors import PROVIDERS, VectorStore          # noqa: E402

REPORT = os.path.join(ROOT, "evals", "report")


def evaluate(provider_name: str, chunks: list[dict], top_k: int = 3) -> dict:
    store = VectorStore(":memory:", provider=PROVIDERS[provider_name]())
    store.upsert(chunks)
    rows = []
    for query, expected in QUERIES:
        hits = store.search(query, top_k=top_k)
        ids = [h["chunk_id"] for h in hits]
        rank = ids.index(expected) + 1 if expected in ids else 0
        rows.append({"query": query, "expected": expected, "rank": rank, "top": ids})
    store.close()
    n = len(rows) or 1
    return {
        "provider": provider_name,
        "n": len(rows),
        "recall@1": round(sum(1 for r in rows if r["rank"] == 1) / n, 4),
        "recall@3": round(sum(1 for r in rows if r["rank"]) / n, 4),
        "mrr": round(sum((1.0 / r["rank"]) if r["rank"] else 0.0 for r in rows) / n, 4),
        "rows": rows,
    }


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    chunks = load_corpus()
    results = {name: evaluate(name, chunks) for name in PROVIDERS}

    lines = ["# 向量检索 provider 对比\n",
             f"- 语料：**{len(chunks)}** chunk；检索集：**{len(QUERIES)}** 条 query",
             "- 口径：**纯向量检索**（不含 BM25 混合），用于对比 provider 差异\n",
             "| provider | recall@1 | recall@3 | MRR |", "|---|---|---|---|"]
    for name, r in results.items():
        lines.append(f"| {name} | {r['recall@1']:.1%} | {r['recall@3']:.1%} | {r['mrr']:.3f} |")

    lines += ["", "## 逐条（hash vs sim）\n",
              "| query | 期望 | hash | sim |", "|---|---|---|---|"]
    for i, (query, expected) in enumerate(QUERIES):
        h = results["hash"]["rows"][i]["rank"] or "—"
        s = results["sim"]["rows"][i]["rank"] or "—"
        lines.append(f"| {query} | {expected} | {h} | {s} |")

    lines += ["", "## 结论怎么写才诚实\n",
              "- 两个 provider 都不是真 embedding 模型：hash 是哈希词袋，sim 是同义词展开 + n-gram 加权；",
              "- 能说明的是「provider 可插拔、同一批 query 可量化对比」这条工程链路通了；",
              "- 不能说明的是「接了 OpenAI/本地 embedding 会更好」——那需要真模型和真账单，本仓库不做假设。",
              ""]
    md = "\n".join(lines)
    os.makedirs(REPORT, exist_ok=True)
    with io.open(os.path.join(REPORT, "vectors.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(md)
    with io.open(os.path.join(REPORT, "vectors.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({k: {kk: vv for kk, vv in v.items() if kk != "rows"}
                   for k, v in results.items()}, f, ensure_ascii=False, indent=2)
    print(md)
    print(f"\n报告已写入 {os.path.join(REPORT, 'vectors.md')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
