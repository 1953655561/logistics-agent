"""复核对照实验：60 条用例分别跑「单链路」与「双链路」。

双链路 = 主链路 + 独立复核 Agent（只看 verdict / issues / citations）。
报告指标：
- 复核异议率：复核未同意主链路的用例占比；
- 复核推翻率：最终结论被改变的用例占比；
- 过判观察：复核指出“主链路可能过判”的用例（重复上报 / 仅凭关键词判禁限）；
- 误报变化：PASS 用例里多报的中高危规则数。
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from data.synth.generator import build_case                  # noqa: E402
from data.synth.scenarios import CASES                       # noqa: E402
from src.agents.reviewer import ReviewAgent, reconcile       # noqa: E402
from src.harness.loop import AuditLoop                       # noqa: E402
from src.harness.tracing import MemoryTracer                 # noqa: E402
from src.tools.audit_tools import build_registry             # noqa: E402


def path_probes() -> list[dict]:
    """合成三条探针，验证复核的升级/降级/只提示三条路径都真的生效。"""
    agent = ReviewAgent()
    no_cite = [{"rule_id": "L2-13", "field_path": "declaration.total_amount",
                "severity": "high", "message": "金额不一致"}]
    cited_dup = [
        # 真重复：同一规则 + 同一字段 + 同一证据。v1.6 之前这里用的是两个不同字段，
        # 那其实是"逐字段各报一次"，已被判为不该算重复上报（见 reviewer._over_judge_checks）。
        {"rule_id": "L1-07", "field_path": "invoice.items[0].amount",
         "severity": "high", "message": "金额勾稽不符", "citation_chunk": "rules#L1-07",
         "evidence": {"calc": 10000.0, "declared": 10200.0}},
        {"rule_id": "L1-07", "field_path": "invoice.items[0].amount",
         "severity": "high", "message": "金额勾稽不符", "citation_chunk": "rules#L1-07",
         "evidence": {"calc": 10000.0, "declared": 10200.0}},
    ]
    rows = []
    for label, verdict, issues, expect in [
        ("证据缺口 · 升级", "PASS", no_cite, "REVIEW"),
        ("证据缺口 · 降级", "REJECT", no_cite, "REVIEW"),
        ("重复上报 · 只提示", "FIX", cited_dup, "FIX"),
    ]:
        review = agent.review(verdict, issues, [])
        final, changed = reconcile(verdict, review)
        rows.append({"label": label, "before": verdict, "after": final,
                     "changed": changed, "recommendation": review.recommendation,
                     "expect": expect, "ok": final == expect})
    return rows



def _run(built: dict, reviewer=None):
    return AuditLoop(build_registry(built["docs"]), MemoryTracer(),
                     reviewer=reviewer).run(built["case_id"])


def _false_positives(built: dict, issues: list[dict]) -> list[str]:
    if built["expected"]["verdict"] != "PASS":
        return []
    expected = set(built.get("injected_defects", []))
    return [i["rule_id"] for i in issues
            if i.get("severity") != "low" and i["rule_id"] not in expected]


def evaluate() -> dict:
    rows = []
    for case in CASES:
        built = build_case(case)
        single = _run(built)
        dual = _run(built, ReviewAgent())
        review = dual.review or {}
        rows.append({
            "id": built["case_id"], "title": built["title"],
            "expected": built["expected"]["verdict"],
            "single": single.verdict, "dual": dual.verdict,
            "changed": single.verdict != dual.verdict,
            "accurate_single": single.verdict == built["expected"]["verdict"],
            "accurate_dual": dual.verdict == built["expected"]["verdict"],
            "agree": review.get("agree", True),
            "recommendation": review.get("recommendation", "agree"),
            "doubts": review.get("doubts", []),
            "observations": review.get("observations", []),
            "reason": review.get("reason", ""),
            "fp_single": _false_positives(built, single.issues),
            "fp_dual": _false_positives(built, dual.issues),
            "review_steps": len(dual.steps),
        })
    n = len(rows) or 1
    dissent = [r for r in rows if not r["agree"]]
    changed = [r for r in rows if r["changed"]]
    over = [r for r in rows if r["observations"]]
    fp_single = sum(len(r["fp_single"]) for r in rows)
    fp_dual = sum(len(r["fp_dual"]) for r in rows)
    return {
        "rows": rows,
        "n": len(rows),
        "dissent_n": len(dissent), "dissent_rate": len(dissent) / n,
        "changed_n": len(changed), "changed_rate": len(changed) / n,
        "over_judged_n": len(over),
        "acc_single": sum(r["accurate_single"] for r in rows) / n,
        "acc_dual": sum(r["accurate_dual"] for r in rows) / n,
        "fp_single": fp_single, "fp_dual": fp_dual,
        "review_rate_single": sum(r["single"] == "REVIEW" for r in rows) / n,
        "review_rate_dual": sum(r["dual"] == "REVIEW" for r in rows) / n,
        "agree_n": len(rows) - len(dissent),
        "dissent": dissent, "changed": changed, "over": over,
        "probes": path_probes(),
    }


def render(result: dict) -> str:
    lines = ["# 复核对照报告（自动生成）\n"]
    lines.append("> 双链路 = 主链路 + 独立复核 Agent；复核只看 `verdict / issues / citations`，"
                 "不接触原始单证。离线 mock 模型，结论可复现。\n")
    lines.append("## 汇总\n")
    lines.append("| 指标 | 单链路 | 双链路 |")
    lines.append("|---|---|---|")
    lines.append(f"| 结论准确率 | {result['acc_single']:.1%} | {result['acc_dual']:.1%} |")
    lines.append(f"| PASS 用例误报（规则条数） | {result['fp_single']} | {result['fp_dual']} |")
    lines.append(f"| REVIEW 占比 | {result['review_rate_single']:.1%} | "
                 f"{result['review_rate_dual']:.1%} |")
    lines.append(f"| 复核异议（未完全同意） | — | {result['dissent_n']}/{result['n']}"
                 f"（{result['dissent_rate']:.1%}） |")
    lines.append(f"| 复核推翻（结论改变） | — | {result['changed_n']}/{result['n']}"
                 f"（{result['changed_rate']:.1%}） |")
    lines.append(f"| 过判观察（≥3 为验收线） | — | **{result['over_judged_n']}** |")
    lines.append("\n> 说明：复核的“推翻”包含两个方向——原结论 PASS/FIX 存疑时升为 REVIEW；"
                 "原结论 REJECT 存疑时降为 REVIEW（由人决定是否退回）。"
                 "过判观察只标记、不改问题列表，避免破坏可追溯性。\n")

    lines.append("## 复核异议明细\n")
    if result["dissent"]:
        lines.append("| 用例 | 标题 | 单链路 | 双链路 | 建议 | 意见 |")
        lines.append("|---|---|---|---|---|---|")
        for r in result["dissent"]:
            codes = "、".join(sorted({o["code"] for o in r["observations"]}
                                    | {d["code"] for d in r["doubts"]}))
            lines.append(f"| {r['id']} | {r['title']} | {r['single']} | {r['dual']} "
                         f"| {r['recommendation']} | {codes}：{r['reason']} |")
    else:
        lines.append("无（复核全部同意主链路）。")

    lines.append("\n## 过判观察（复核指出主链路可能过判）\n")
    if result["over"]:
        lines.append("| 用例 | 单链路 | 观察 | 说明 |")
        lines.append("|---|---|---|---|")
        for r in result["over"]:
            obs = "；".join(o.get("detail", o.get("code", "")) for o in r["observations"])
            lines.append(f"| {r['id']} | {r['single']} | "
                         f"{'、'.join(sorted({o['code'] for o in r['observations']}))} | {obs} |")
    else:
        lines.append("无。")

    lines.append("\n## 复核路径自检（合成探针）\n")
    lines.append("| 场景 | 主链路 | 复核建议 | 最终结论 | 是否推翻 | 期望 | 结果 |")
    lines.append("|---|---|---|---|---|---|---|")
    for p in result["probes"]:
        mark = "✅" if p["ok"] else "❌"
        lines.append(f"| {p['label']} | {p['before']} | {p['recommendation']} "
                     f"| {p['after']} | {'是' if p['changed'] else '否'} "
                     f"| {p['expect']} | {mark} |")
    lines.append("\n> 探针说明：60 条回归集上主链路证据完整，复核只提观察；"
                 "这三条合成探针专门验证“升级 / 降级 / 只提示”三条路径都真实生效。")

    lines.append("\n## 结论改变明细\n")
    if result["changed"]:
        lines.append("| 用例 | 单链路 | 双链路 | 复核意见 |")
        lines.append("|---|---|---|---|")
        for r in result["changed"]:
            lines.append(f"| {r['id']} | {r['single']} | {r['dual']} | {r['reason']} |")
    else:
        lines.append("无（本次 60 条回归集上复核只提意见、不改变结论）。")
    return "\n".join(lines)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    result = evaluate()
    md = render(result)
    out_dir = os.path.join(ROOT, "evals", "report")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "review.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    print(md)
    print(f"\n报告已写入 {path}")


if __name__ == "__main__":
    main()
