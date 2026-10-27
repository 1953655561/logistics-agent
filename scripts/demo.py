"""一键演示：跑四种结论的代表用例，打印结论、问题、引用、步数与成本。

    python scripts/demo.py
    python scripts/demo.py --json
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from data.synth.generator import build_case                    # noqa: E402
from data.synth.scenarios import CASES                         # noqa: E402
from src.adapters.llm_mock import MockLLM                      # noqa: E402
from src.agents.reviewer import ReviewAgent                    # noqa: E402
from src.harness.cost import CostMeter                         # noqa: E402
from src.harness.loop import AuditLoop                         # noqa: E402
from src.harness.tracing import MemoryTracer                   # noqa: E402
from src.tools.audit_tools import build_registry               # noqa: E402

DEMO_CASES = ["IMP-0001", "IMP-0019", "IMP-0025", "IMP-0048"]
LABEL = {"PASS": "可申报", "FIX": "可补正", "REVIEW": "需复核", "REJECT": "不可申报"}


def _run(case_id: str) -> dict:
    case = next(c for c in CASES if c["id"] == case_id)
    built = build_case(case)
    meter = CostMeter()
    res = AuditLoop(build_registry(built["docs"]), MemoryTracer(), MockLLM(),
                    reviewer=ReviewAgent(), cost_meter=meter).run(case_id)
    return {
        "case_id": case_id,
        "title": built["title"],
        "expected": built["expected"]["verdict"],
        "verdict": res.verdict,
        "label": LABEL.get(res.verdict, res.verdict),
        "summary": res.summary,
        "issues": [
            {"rule_id": i.get("rule_id"), "severity": i.get("severity"),
             "field": i.get("field_path"), "message": i.get("message"),
             "citation": i.get("citation_text") or i.get("citation", "")}
            for i in res.issues
        ],
        "review": res.review,
        "steps": [{"name": s.name, "tool": s.tool, "ms": round(s.ms, 2),
                   "ok": s.ok} for s in res.steps],
        "cost": res.cost,
        "usage": res.usage,
        "degraded": res.degraded,
    }


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    as_json = "--json" in (argv or sys.argv[1:])
    rows = [_run(cid) for cid in DEMO_CASES]
    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0

    print("=" * 72)
    print("关务智能审核 Agent · 一键演示（离线 mock，结论可复现）")
    print("=" * 72)
    for r in rows:
        print(f"\n[{r['case_id']}] {r['title']}")
        print(f"  结论：{r['verdict']}（{r['label']}）   期望：{r['expected']}"
              f"   {'✅' if r['verdict'] == r['expected'] else '❌'}")
        print(f"  摘要：{r['summary']}")
        if r["issues"]:
            print("  问题：")
            for i in r["issues"]:
                print(f"    - [{i['rule_id']}] {i['severity']} {i['message']}")
                if i["citation"]:
                    cite = i["citation"]
                    if not cite.startswith("依据"):
                        cite = "依据：" + cite
                    print(f"      {cite}")
        review = r.get("review") or {}
        if review:
            print(f"  复核：{review.get('recommendation', '-')} — {review.get('reason', '')}")
        print(f"  成本：¥{r['cost']:.6f}   步数：{len(r['steps'])}"
              f"   {'⚠ 有降级' if r['degraded'] else ''}")
        print("  轨迹：" + " → ".join(
            f"{s['name']}({s['tool'] or '-'},{s['ms']}ms)" for s in r["steps"]))

    print("\n" + "=" * 72)
    print("下一步：`make demo` 打开 Web 审核台；`make eval` 看完整评测。")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
