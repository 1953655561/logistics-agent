"""基线快照与回归比对：把「当前能跑出的关键指标」固化成 JSON。

用法：
    python scripts/baseline.py          # 生成 evals/report/baseline.json
    python scripts/baseline_check.py    # 与基线比对，退化则 exit 1

设计约束：
- 门禁阈值只有一份：`scripts/gate.py::checks()`，这里直接复用，不再抄一遍。
- 快照里只放"可复跑"的量：评测 4 维指标、手改单问题数、规则数、测试数、门禁 11 项。
- 基线是**本机生成**的（P95 之类的绝对量随机器变），所以 baseline.json 不进 git。
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORT = os.path.join(ROOT, "evals", "report")
BASELINE = os.path.join(REPORT, "baseline.json")

sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

HAND_DOC = os.path.join(ROOT, "examples", "realistic", "1",
                        "REAL-002-amount-mismatch-FIX.json")
CLEAN_DOC = os.path.join(ROOT, "examples", "realistic",
                         "REAL-002-amount-mismatch-FIX.json")


def _json(path: str, default=None):
    if not os.path.exists(path):
        return default
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


def _doc_issues(path: str) -> dict:
    from src.engine import audit
    if not os.path.exists(path):
        return {"path": path, "missing": True}
    with io.open(path, encoding="utf-8") as f:
        docs = json.load(f)
    report = audit(docs)
    return {
        "path": os.path.relpath(path, ROOT).replace("\\", "/"),
        "verdict": report["verdict"],
        "issue_count": report["issue_count"],
        "rules": sorted({i["rule_id"] for i in report["issues"]}),
    }


def _tests() -> dict:
    proc = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"],
                          cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    tail = (proc.stderr or "")[-2000:]
    total = 0
    for line in tail.splitlines():
        if line.startswith("Ran "):
            try:
                total = int(line.split()[1])
            except (IndexError, ValueError):
                total = 0
    return {"total": total, "ok": proc.returncode == 0}


def snapshot(with_tests: bool = True) -> dict:
    """收集一次完整快照。with_tests=False 时不跑 unittest（单测里用）。"""
    from evals.runner import evaluate
    import gate

    result = evaluate()
    perf = _json(os.path.join(REPORT, "perf.json"), {})
    redteam = _json(os.path.join(REPORT, "redteam.json"), {})
    hallucination = _json(os.path.join(REPORT, "hallucination.json"), {})
    agent = result.get("agent") or {}
    cite = result.get("citation") or {}
    concurrent = perf.get("concurrent") or {}

    return {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "eval": {
            "n": result["n"],
            "accuracy": round(result["accuracy"], 6),
            "recall": round(result["recall"], 6),
            "false_positive_case_rate": round(result["false_positive_case_rate"], 6),
            "citation_coverage": round(cite.get("coverage", 0.0), 6),
            "rules_total": result["rules_total"],
            "covered_accuracy": round(result["covered_accuracy"], 6),
        },
        "agent": {
            "per_case_cost": agent.get("per_case_cost"),
            "avg_steps": round(agent.get("avg_steps", 0.0), 3),
        },
        "perf": {"p95_ms": concurrent.get("p95_ms"), "errors": concurrent.get("errors")},
        "redteam": {"blocked": redteam.get("blocked"), "forbidden": redteam.get("forbidden")},
        "gate": [{"name": n, "ok": ok, "actual": a} for n, ok, a in
                 gate.checks(result, perf, redteam, hallucination)],
        "hand_doc": _doc_issues(HAND_DOC),
        "clean_doc": _doc_issues(CLEAN_DOC),
        "tests": _tests() if with_tests else {"total": None, "ok": None},
    }


def compare(base: dict, cur: dict) -> list[str]:
    """返回回归项（空列表 = 未退化）。只拦"退化"，不拦"变好"。"""
    bad: list[str] = []

    def lower_is_bad(key: str, label: str, eps: float = 1e-9):
        b = (base.get("eval") or {}).get(key)
        c = (cur.get("eval") or {}).get(key)
        if b is not None and c is not None and c < b - eps:
            bad.append(f"{label} 退化：{b:.4f} → {c:.4f}")

    def higher_is_bad(key: str, label: str, eps: float = 1e-9):
        b = (base.get("eval") or {}).get(key)
        c = (cur.get("eval") or {}).get(key)
        if b is not None and c is not None and c > b + eps:
            bad.append(f"{label} 上升：{b:.4f} → {c:.4f}")

    lower_is_bad("accuracy", "结论准确率")
    lower_is_bad("recall", "缺陷召回率")
    higher_is_bad("false_positive_case_rate", "误报用例率")
    lower_is_bad("citation_coverage", "引用覆盖率")

    # 手改单：问题数不能变少（变少意味着漏报）
    bh, ch = base.get("hand_doc") or {}, cur.get("hand_doc") or {}
    if bh.get("issue_count") is not None and ch.get("issue_count") is not None:
        if ch["issue_count"] < bh["issue_count"]:
            bad.append(f"手改单问题数下降：{bh['issue_count']} → {ch['issue_count']}（疑似漏报）")

    # 干净样例：规则集合不许变（变了说明引入了误报或改了解释口径）
    bc, cc = base.get("clean_doc") or {}, cur.get("clean_doc") or {}
    if bc.get("rules") is not None and cc.get("rules") is not None:
        if sorted(bc["rules"]) != sorted(cc["rules"]):
            bad.append(f"干净样例规则集合变化：{bc['rules']} → {cc['rules']}")

    # 门禁：当前必须全绿
    for item in cur.get("gate") or []:
        if not item.get("ok"):
            bad.append(f"门禁未过：{item.get('name')}（{item.get('actual')}）")

    # 测试：必须全绿，且数量不低于基线
    bt, ct = base.get("tests") or {}, cur.get("tests") or {}
    if ct.get("ok") is False:
        bad.append("单元测试未通过")
    if bt.get("total") and ct.get("total") and ct["total"] < bt["total"]:
        bad.append(f"测试数下降：{bt['total']} → {ct['total']}")

    return bad


def load(path: str = BASELINE) -> dict | None:
    return _json(path)


def write(data: dict, path: str = BASELINE) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path
