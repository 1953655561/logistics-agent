"""两种审核模式对比：scripted（默认）vs react（证据补采）。

用途：回答"为什么默认用确定性工作流"——同一批用例下比较结论一致性、
步数、成本与证据覆盖。报告自动生成，数字不手写。

    python evals/modes.py
"""
from __future__ import annotations

import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from data.synth.generator import build_case          # noqa: E402
from data.synth.scenarios import CASES               # noqa: E402
from src.adapters.llm_mock import MockLLM            # noqa: E402
from src.harness.loop import AuditLoop               # noqa: E402
from src.harness.planner import build_planner        # noqa: E402
from src.harness.tracing import MemoryTracer         # noqa: E402
from src.tools.audit_tools import build_registry     # noqa: E402

REPORT = os.path.join(ROOT, "evals", "report")


def run_mode(docs: dict, mode: str) -> dict:
    llm = MockLLM()
    res = AuditLoop(build_registry(docs), MemoryTracer(), llm,
                    mode=mode, planner=build_planner(mode, llm)).run("MODE")
    verified = sum(1 for i in res.issues if i.get("verification"))
    return {
        "verdict": res.verdict,
        "rules": sorted({i["rule_id"] for i in res.issues}),
        "issues": len(res.issues),
        "steps": len(res.steps),
        "cost": res.cost,
        "verified": verified,
        "citations": len(res.citations),
    }


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    rows = []
    for case in CASES:
        built = build_case(case)
        s = run_mode(built["docs"], "scripted")
        r = run_mode(built["docs"], "react")
        rows.append({"id": built["case_id"], "title": built["title"],
                     "expected": built["expected"]["verdict"],
                     "scripted": s, "react": r,
                     "same_verdict": s["verdict"] == r["verdict"],
                     "same_rules": s["rules"] == r["rules"]})

    n = len(rows) or 1
    agree = sum(r["same_verdict"] for r in rows)
    same_rules = sum(r["same_rules"] for r in rows)
    s_steps = sum(r["scripted"]["steps"] for r in rows) / n
    r_steps = sum(r["react"]["steps"] for r in rows) / n
    s_cost = sum(r["scripted"]["cost"] for r in rows) / n
    r_cost = sum(r["react"]["cost"] for r in rows) / n
    issues_total = sum(r["react"]["issues"] for r in rows) or 1
    verified_total = sum(r["react"]["verified"] for r in rows)

    summary = {
        "n": len(rows),
        "verdict_agreement": round(agree / n, 4),
        "ruleset_agreement": round(same_rules / n, 4),
        "scripted_avg_steps": round(s_steps, 2),
        "react_avg_steps": round(r_steps, 2),
        "scripted_avg_cost": round(s_cost, 6),
        "react_avg_cost": round(r_cost, 6),
        "react_verified_issues": verified_total,
        "react_issue_total": issues_total,
        "react_verified_rate": round(verified_total / issues_total, 4),
        "cases": rows,
    }

    lines = [
        "# 模式对比（scripted vs react）\n",
        f"- 用例数：**{summary['n']}**",
        f"- 结论一致率：**{summary['verdict_agreement']:.1%}**"
        f"（规则集合一致率 {summary['ruleset_agreement']:.1%}）",
        f"- 平均步数：scripted **{summary['scripted_avg_steps']:.1f}** → "
        f"react **{summary['react_avg_steps']:.1f}**",
        f"- 单票成本：scripted **¥{summary['scripted_avg_cost']:.6f}** → "
        f"react **¥{summary['react_avg_cost']:.6f}**（mock 模型）",
        f"- react 证据覆盖：**{summary['react_verified_rate']:.1%}**"
        f"（{summary['react_verified_issues']}/{summary['react_issue_total']} 条问题带回查证据）",
        "",
        "## 逐条结果\n",
        "| 用例 | 期望 | scripted | react | 结论一致 | 规则一致 | 步数 s/r |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['id']} | {r['expected']} | {r['scripted']['verdict']} | "
            f"{r['react']['verdict']} | {'✅' if r['same_verdict'] else '❌'} | "
            f"{'✅' if r['same_rules'] else '❌'} | "
            f"{r['scripted']['steps']}/{r['react']['steps']} |")

    bad = [r for r in rows if not r["same_verdict"] or not r["same_rules"]]
    if bad:
        lines.append("\n## 不一致明细\n")
        for r in bad:
            lines.append(f"- **{r['id']}**：scripted {r['scripted']['rules']} vs "
                         f"react {r['react']['rules']}")

    md = "\n".join(lines)
    os.makedirs(REPORT, exist_ok=True)
    with io.open(os.path.join(REPORT, "modes.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(md)
    with io.open(os.path.join(REPORT, "modes.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(md)
    print(f"\n报告已写入 {os.path.join(REPORT, 'modes.md')}")
    return 0 if (agree == n and same_rules == n) else 1


if __name__ == "__main__":
    raise SystemExit(main())
