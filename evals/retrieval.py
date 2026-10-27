"""检索评测：用 25 条 query→期望 chunk 的检索集，量化 RAG 的召回质量。

回答的是「RAG 召回率多少」这个问题——端到端 100% 不是检索指标。
指标：recall@1 / recall@3 / MRR（期望 chunk 不在 top3 记 0），并输出坏例表。

    python evals/retrieval.py            # 跑评测，写报告
    python evals/retrieval.py --json     # 额外打印机器可读结果
"""
from __future__ import annotations

import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.rag.retriever import Retriever          # noqa: E402

REPORT = os.path.join(ROOT, "evals", "report")

# 刻意用「业务口语」提问，不含规则编号——否则规则编号精确命中会把难度抹平
QUERIES: list[tuple[str, str]] = [
    ("发票和报关单总价对不上，按哪个改", "rules#L2-13"),
    ("四张单子币制不一样", "rules#L2-14"),
    ("品名少一个字算不算不一致", "rules#L2-11"),
    ("收货人和提单通知人对不上", "rules#L2-18"),
    ("唛头目的港和卸货港写法不同", "rules#L2-22"),
    ("发票上没有合同号", "rules#L2-21"),
    ("FOB 成交运费要不要申报", "rules#L2-19"),
    ("报关单原产国和发票不一致", "rules#L2-20"),
    ("合同金额和发票金额差很多", "rules#L2-23"),
    ("品牌类型发票和报关单写的不一样", "rules#L2-24"),
    ("商品编号位数不对或者带字母", "rules#L1-10"),
    ("缺少法定第二计量单位", "rules#L1-04"),
    ("申报日期早于提单日期", "rules#L1-02"),
    ("报关单币制代码写错", "rules#L1-03"),
    ("毛重比净重还小", "rules#L1-08"),
    ("托盘包装没填托盘数", "rules#L1-09"),
    ("随附单证缺了提单", "rules#L1-06"),
    ("一票超过五十项商品要拆单", "rules#L1-05"),
    ("单价乘数量对不上行金额", "rules#L1-07"),
    ("特许权使用费没算进完税价格", "rules#L4-41"),
    ("进境超过十四天才申报", "rules#L4-42"),
    ("木包装没有 IPPC 标识", "rules#L4-43"),
    ("许可证在申报日已经过期", "rules#L4-44"),
    ("玩具进口要不要 3C 认证", "rules#L4-33"),
    ("贸易方式和征免性质不匹配", "rules#L4-35"),
    ("9503008900 要报哪些申报要素", "elements#9503008900"),
    ("8471300000 的规范申报要素", "elements#8471300000"),
    ("1905310000 申报要填什么", "elements#1905310000"),
    ("8509400000 的要素清单", "elements#8509400000"),
    ("6109100021 需要报哪些要素", "elements#6109100021"),
]


def evaluate(retriever: Retriever, top_k: int = 3) -> dict:
    rows = []
    for query, expected in QUERIES:
        hits = retriever.search(query, top_k=top_k)
        ids = [h.get("chunk_id") for h in hits]
        rank = ids.index(expected) + 1 if expected in ids else 0
        rows.append({
            "query": query, "expected": expected, "rank": rank,
            "top": ids,
            "hit@1": rank == 1,
            "hit@3": rank >= 1,
            "rr": (1.0 / rank) if rank else 0.0,
        })
    n = len(rows) or 1
    return {
        "n": len(rows),
        "recall@1": round(sum(r["hit@1"] for r in rows) / n, 4),
        "recall@3": round(sum(r["hit@3"] for r in rows) / n, 4),
        "mrr": round(sum(r["rr"] for r in rows) / n, 4),
        "rows": rows,
    }


def render(result: dict) -> str:
    bad = [r for r in result["rows"] if not r["hit@3"]]
    lines = [
        "# 检索评测（RAG 召回）\n",
        f"- 检索集：**{result['n']}** 条口语化 query（不含规则编号，避免精确命中抹平难度）",
        f"- recall@1：**{result['recall@1']:.1%}**",
        f"- recall@3：**{result['recall@3']:.1%}**",
        f"- MRR：**{result['mrr']:.3f}**",
        "",
        "> 端到端「引用覆盖率 100%」说明的是引用能挂上，不是检索准；"
        "这两个指标才回答 RAG 召回得怎么样。\n",
        "## 逐条结果\n",
        "| # | query | 期望 | 命中位次 | top3 |",
        "|---|---|---|---|---|",
    ]
    for i, r in enumerate(result["rows"], 1):
        rank = str(r["rank"]) if r["rank"] else "未命中"
        lines.append(f"| {i} | {r['query']} | {r['expected']} | {rank} | "
                     f"{', '.join(x or '-' for x in r['top'])} |")
    if bad:
        lines.append("\n## 坏例（top3 未命中）\n")
        for r in bad:
            lines.append(f"- **{r['query']}** → 期望 `{r['expected']}`，实得 {r['top']}")
    return "\n".join(lines)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    result = evaluate(Retriever())
    md = render(result)
    os.makedirs(REPORT, exist_ok=True)
    with io.open(os.path.join(REPORT, "retrieval.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(md)
    with io.open(os.path.join(REPORT, "retrieval.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(md)
    print(f"\n报告已写入 {os.path.join(REPORT, 'retrieval.md')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
