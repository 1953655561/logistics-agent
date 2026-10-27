"""幻觉与引用可回查评测：无引用断言率、引用不可回查率。

    python evals/hallucination.py

口径（与 `docs/02` 第 4 节「引用覆盖率」互补，不是同一指标）：

- **无引用断言率 `uncited_rate`**：非 PASS 用例里，`severity=high` 却拿不到
  `citation_chunk` 的问题数 ÷ 同一范围的高危问题总数。
  分母只算非 PASS 用例（与 `evals/runner.py::citation_check` 的取样范围一致），
  分子只算高危问题——中低危问题按设计不强制带引用。
- **引用不可回查率 `broken_citation_rate`**：`citation_chunk` 不在 RAG 语料
  `chunk_id` 集合里的问题数 ÷ 带引用的高危/非高危问题总数；
  **引用可回查率 = 1 - 该值**。分母为 0 时记 0.0（没有引用就没有不可回查）。

两个指标都以 `src.harness.loop.AuditLoop` 的真实输出为准（与线上链路一致），
不做任何事后补引用。报告由脚本自动生成，数字不手写。

阈值不在这里定：门禁阈值见 `scripts/gate.py::checks()`（第 10、11 项），
按「先观测后设线」处理。
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from data.synth.generator import build_case                    # noqa: E402
from data.synth.scenarios import CASES                         # noqa: E402
from src.harness.loop import AuditLoop                         # noqa: E402
from src.harness.tracing import MemoryTracer                   # noqa: E402
from src.rag.corpus import load_corpus                         # noqa: E402
from src.tools.audit_tools import build_registry               # noqa: E402


def known_chunk_ids() -> set[str]:
    """RAG 语料里全部可回查的 chunk_id。"""
    return {c["chunk_id"] for c in load_corpus()}


def measure(records: list[dict], known: set[str]) -> dict:
    """纯函数：按记录算两个指标（单测直接构造 records，不必跑满 60 条）。

    records 每项：``{"case_id", "expected_verdict", "issues", "citations"?}``；
    ``issues`` 里每项至少有 ``rule_id`` / ``severity`` / 可选 ``citation_chunk``。
    """
    cases_total = len(records)
    nonpass = [r for r in records
               if (r.get("expected_verdict") or "").upper() != "PASS"]

    high_issues = 0
    uncited_issues = 0
    uncited_cases: list[dict] = []
    for rec in nonpass:
        bad: list[str] = []
        for issue in rec.get("issues") or []:
            if issue.get("severity") != "high":
                continue
            high_issues += 1
            if not issue.get("citation_chunk"):
                uncited_issues += 1
                bad.append(str(issue.get("rule_id", "")))
        if bad:
            uncited_cases.append({"case_id": rec.get("case_id", ""), "rules": bad})

    cited_issues = 0
    broken_issues = 0
    broken_citations: list[dict] = []
    # 引用可回查覆盖全部用例：PASS 用例上多报出来的引用同样要能回查
    for rec in records:
        for issue in rec.get("issues") or []:
            chunk_id = issue.get("citation_chunk")
            if not chunk_id:
                continue
            cited_issues += 1
            if chunk_id not in known:
                broken_issues += 1
                broken_citations.append({
                    "case_id": rec.get("case_id", ""),
                    "rule_id": str(issue.get("rule_id", "")),
                    "chunk_id": str(chunk_id),
                })

    return {
        "cases_total": cases_total,
        "cases_nonpass": len(nonpass),
        "high_issues": high_issues,
        "uncited_issues": uncited_issues,
        "uncited_rate": round(uncited_issues / high_issues, 6) if high_issues else 0.0,
        "uncited_cases": uncited_cases,
        "cited_issues": cited_issues,
        "broken_issues": broken_issues,
        "broken_citation_rate": (round(broken_issues / cited_issues, 6)
                                 if cited_issues else 0.0),
        "citation_verifiability": (round(1 - broken_issues / cited_issues, 6)
                                   if cited_issues else 1.0),
        "broken_citations": broken_citations,
    }


def evaluate() -> dict:
    """跑 60 条用例（Agent 全链路），统计两个指标。"""
    t0 = time.perf_counter()
    records: list[dict] = []
    for case in CASES:
        built = build_case(case)
        res = AuditLoop(build_registry(built["docs"]), MemoryTracer()).run(
            built["case_id"])
        records.append({
            "case_id": built["case_id"],
            "expected_verdict": built["expected"]["verdict"],
            "issues": res.issues,
        })
    result = measure(records, known_chunk_ids())
    result.update({
        "n": len(records),
        "observed_at": datetime.now().isoformat(timespec="seconds"),
        "elapsed_s": round(time.perf_counter() - t0, 3),
        "note": ("阈值未在评测脚本里写死：门禁见 scripts/gate.py 第 10、11 项，"
                 "先观测后设线。"),
    })
    return result


def render(result: dict) -> str:
    lines = ["# 幻觉与引用可回查报告（自动生成）\n"]
    lines.append(f"> 用例数 **{result['cases_total']}**（其中非 PASS "
                 f"{result['cases_nonpass']} 条）；指标取自 Agent 全链路输出，"
                 "不做事后补引用。\n")
    lines.append("## 汇总\n")
    lines.append(f"- 无引用断言率：**{result['uncited_rate']:.1%}**"
                 f"（{result['uncited_issues']}/{result['high_issues']} 条高危问题无 "
                 "`citation_chunk`）")
    lines.append(f"- 引用不可回查率：**{result['broken_citation_rate']:.1%}**"
                 f"（{result['broken_issues']}/{result['cited_issues']} 条引用的 "
                 "`chunk_id` 不在 RAG 语料里）")
    lines.append(f"- 引用可回查率：**{result['citation_verifiability']:.1%}**"
                 "（= 1 - 引用不可回查率）")
    lines.append(f"- 耗时：{result['elapsed_s']}s（{result['observed_at']}）")

    lines.append("\n## 不合规明细\n")
    if not result["uncited_cases"] and not result["broken_citations"]:
        lines.append("- 无：高危问题都带可回查引用。")
    for row in result["uncited_cases"]:
        rules = "、".join(row["rules"]) or "-"
        lines.append(f"- 无引用断言 **{row['case_id']}**：规则 {rules}")
    for row in result["broken_citations"]:
        lines.append(f"- 引用不可回查 **{row['case_id']}**：规则 {row['rule_id']}，"
                     f"`chunk_id={row['chunk_id']}`")

    lines.append("\n## 逐条统计\n")
    lines.append("| 范围 | 数值 |")
    lines.append("|---|---|")
    lines.append(f"| 高危问题（非 PASS 用例） | {result['high_issues']} |")
    lines.append(f"| 无引用高危问题 | {result['uncited_issues']} |")
    lines.append(f"| 带引用问题（全部用例） | {result['cited_issues']} |")
    lines.append(f"| 不可回查引用 | {result['broken_issues']} |")

    lines.append("\n> 口径：`uncited_rate` 的分母是非 PASS 用例里的高危问题；"
                 "`broken_citation_rate` 的分母是全部带 `citation_chunk` 的问题。"
                 "阈值由 `scripts/gate.py` 统一判定（先观测后设线），"
                 "本报告只给观测值，不写结论。")
    return "\n".join(lines)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    result = evaluate()
    md = render(result)
    out_dir = os.path.join(ROOT, "evals", "report")
    os.makedirs(out_dir, exist_ok=True)
    md_path = os.path.join(out_dir, "hallucination.md")
    with open(md_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(md)
    with open(os.path.join(out_dir, "hallucination.json"), "w",
              encoding="utf-8", newline="\n") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(md)
    print(f"\n报告已写入 {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
