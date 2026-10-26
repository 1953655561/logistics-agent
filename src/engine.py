"""审核引擎：跑规则 → 聚合结论 → 输出报告。"""
from __future__ import annotations

from .issue import RANK, worst
from .registry import RULES, run_all
import src.rules  # noqa: F401  触发规则注册

SOURCE = {r["id"]: r["source"] for r in RULES}
TITLES = {r["id"]: r["title"] for r in RULES}


def audit(ctx: dict) -> dict:
    results = run_all(ctx)
    conclusions = [r.conclusion for r in results]
    verdict = worst(*conclusions) if conclusions else "PASS"
    issues = []
    for r in results:
        for i in r.issues:
            d = i.to_dict()
            d["layer"] = r.layer
            d["citation"] = r.source
            issues.append(d)
    issues.sort(key=lambda x: (-RANK_ORDER.get(x["severity"], 0), x["rule_id"]))
    by_layer = {}
    for r in results:
        by_layer.setdefault(r.layer, []).append(
            {"rule_id": r.rule_id, "title": r.title, "conclusion": r.conclusion,
             "issue_count": len(r.issues), "error": r.error})
    return {
        "verdict": verdict,
        "issue_count": len(issues),
        "issues": issues,
        "rules": results,
        "by_layer": by_layer,
        "failed_rules": [r.rule_id for r in results if r.error],
    }


RANK_ORDER = {"high": 3, "mid": 2, "low": 1}


def explain(report: dict) -> str:
    """人读结论（Web/CLI 共用）。"""
    lines = [f"审核结论：{report['verdict']}（问题 {report['issue_count']} 处）"]
    for it in report["issues"]:
        lines.append(f"  - [{it['rule_id']}] {it['message']}  ← {it.get('citation', '')}")
    return "\n".join(lines)
