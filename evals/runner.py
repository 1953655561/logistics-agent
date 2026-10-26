"""评测执行器：跑 60 条用例 → 生成 Markdown 报告。

用法（仓库根目录）：
    python evals/runner.py
    python evals/runner.py --json      # 额外输出机器可读结果
"""
from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from data.synth.generator import build_case          # noqa: E402
from data.synth.scenarios import CASES               # noqa: E402
from src.engine import audit                         # noqa: E402
from src.harness.loop import AuditLoop               # noqa: E402
from src.harness.tracing import MemoryTracer         # noqa: E402
from src.tools.audit_tools import build_registry     # noqa: E402


def citation_check() -> dict:
    """跑一遍 Agent 循环，检查非 PASS 结论是否都带可定位引用。"""
    total = 0
    missing = []
    for case in CASES:
        built = build_case(case)
        if built["expected"]["verdict"] == "PASS":
            continue
        res = AuditLoop(build_registry(built["docs"]), MemoryTracer()).run(built["case_id"])
        total += 1
        no_cite = [i for i in res.issues
                   if i.get("severity") == "high" and not i.get("citation_chunk")]
        if no_cite:
            missing.append({"case": built["case_id"],
                            "rules": [i["rule_id"] for i in no_cite]})
    return {"total": total, "missing": missing,
            "coverage": 1 - len(missing) / total if total else 1.0}


def evaluate():
    rows, t0 = [], time.perf_counter()
    for case in CASES:
        built = build_case(case)
        report = audit(built["docs"])
        produced = {it["rule_id"] for it in report["issues"]}
        expected_rules = set(built["injected_defects"])
        hit = expected_rules & produced
        recall = (len(hit) / len(expected_rules)) if expected_rules else 1.0
        verdict_ok = report["verdict"] == built["expected"]["verdict"]
        # PASS 用例里出现的任何非低危问题都算误报
        false_positives = []
        if built["expected"]["verdict"] == "PASS":
            false_positives = [it["rule_id"] for it in report["issues"]
                               if it["severity"] != "low" and it["rule_id"] not in expected_rules]
        rows.append({
            "id": built["case_id"], "title": built["title"],
            "expected": built["expected"]["verdict"], "got": report["verdict"],
            "verdict_ok": verdict_ok, "recall": round(recall, 3),
            "requires": built.get("requires", []),
            "expected_rules": sorted(expected_rules), "produced": sorted(produced),
            "missed": sorted(expected_rules - produced),
            "false_positives": false_positives,
            "issue_count": report["issue_count"],
            "failed_rules": report["failed_rules"],
            "citations": sorted({it["citation"] for it in report["issues"] if it.get("citation")}),
        })
    elapsed = time.perf_counter() - t0
    n = len(rows)
    acc = sum(r["verdict_ok"] for r in rows) / n
    with_def = [r for r in rows if r["expected_rules"]]
    recall = (sum(r["recall"] for r in with_def) / len(with_def)) if with_def else 1.0
    fp = sum(len(r["false_positives"]) for r in rows)
    pass_cases = [r for r in rows if r["expected"] == "PASS"]
    fp_rate = (len([r for r in rows if r["false_positives"]]) / len(pass_cases)) if pass_cases else 0.0
    # 只统计"当前已实现规则可判"的用例（requires 为空的），另给覆盖情况
    covered = [r for r in rows if not r["requires"]]
    covered_acc = (sum(r["verdict_ok"] for r in covered) / len(covered)) if covered else 1.0
    from src.engine import RULES
    cite = citation_check()
    return {
        "cases": rows, "n": n, "accuracy": acc, "recall": recall,
        "covered_n": len(covered), "covered_accuracy": covered_acc,
        "rules_total": len(RULES), "citation": cite,
        "false_positives": fp, "false_positive_case_rate": fp_rate,
        "elapsed_s": elapsed,
    }


def render(result) -> str:
    rows = result["cases"]
    by_expected = {}
    for r in rows:
        by_expected.setdefault(r["expected"], []).append(r)
    lines = []
    lines.append("# 评测报告（自动生成）\n")
    lines.append(f"- 用例数：**{result['n']}**")
    lines.append(f"- 结论准确率：**{result['accuracy']:.1%}**")
    lines.append(f"- 已实现规则覆盖内准确率：**{result['covered_accuracy']:.1%}**"
                 f"（{result['covered_n']} 条可判用例）")
    lines.append(f"- 缺陷召回率：**{result['recall']:.1%}**")
    lines.append(f"- 误报用例率：**{result['false_positive_case_rate']:.1%}**"
                 f"（误报 {result['false_positives']} 处）")
    lines.append(f"- 已实现规则：{result['rules_total']} 条（L1 10 / L2 12 / L3 10 / L4 12）")
    lines.append(f"- 引用覆盖率（非 PASS 的高危问题）：**{result['citation']['coverage']:.1%}**"
                 f"（{result['citation']['total']} 条用例）")
    lines.append(f"- 耗时：{result['elapsed_s']:.2f}s")
    lines.append("\n> 注：60 条用例的期望值由规则推导 + 自拟内审 SOP 得出，未经报关员标注；"
                 "容差阈值属假设，详见 `docs/02` 第 5 节。\n")

    lines.append("## 分类别准确率\n")
    lines.append("| 期望结论 | 用例数 | 判定正确 | 准确率 |")
    lines.append("|---|---|---|---|")
    for k in ("PASS", "FIX", "REVIEW", "REJECT"):
        g = by_expected.get(k, [])
        if not g:
            continue
        ok = sum(r["verdict_ok"] for r in g)
        lines.append(f"| {k} | {len(g)} | {ok} | {ok/len(g):.0%} |")

    lines.append("\n## 逐条结果\n")
    lines.append("| 用例 | 标题 | 期望 | 实际 | 结论 | 召回 | 漏检规则 |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in rows:
        mark = "✅" if r["verdict_ok"] else "❌"
        missed = ",".join(r["missed"]) or "-"
        lines.append(f"| {r['id']} | {r['title']} | {r['expected']} | {r['got']} | {mark} "
                     f"| {r['recall']:.0%} | {missed} |")

    bad = [r for r in rows if not r["verdict_ok"]]
    if bad:
        lines.append("\n## 判定错误明细\n")
        for r in bad:
            lines.append(f"- **{r['id']}** {r['title']}：期望 `{r['expected']}`，实际 `{r['got']}`；"
                         f"产出规则 {r['produced'] or '无'}")
    fp_cases = [r for r in rows if r["false_positives"]]
    if fp_cases:
        lines.append("\n## 误报明细\n")
        for r in fp_cases:
            lines.append(f"- **{r['id']}**：多报 {r['false_positives']}")
    return "\n".join(lines)


def main():
    result = evaluate()
    out_dir = os.path.join(ROOT, "evals", "report")
    os.makedirs(out_dir, exist_ok=True)
    md = render(result)
    path = os.path.join(out_dir, "report.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    if "--json" in sys.argv:
        with open(os.path.join(out_dir, "result.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    print(md)
    print(f"\n报告已写入 {path}")


if __name__ == "__main__":
    main()
