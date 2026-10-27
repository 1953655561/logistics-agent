"""性能评测：单票延迟、并发 10 的 P95 与错误率（对应 D7）。

    python evals/perf.py

不依赖第三方压测工具；线程池模拟 10 个并发审核请求。
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

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

TARGET_P95_MS = 5000
TARGET_COST = 0.1
CONCURRENCY = 10


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    data = sorted(values)
    idx = min(len(data) - 1, int(round((p / 100.0) * (len(data) - 1))))
    return round(data[idx], 2)


def _one(case: dict) -> dict:
    built = build_case(case)
    meter = CostMeter()
    t0 = time.perf_counter()
    res = AuditLoop(build_registry(built["docs"]), MemoryTracer(), MockLLM(),
                    reviewer=ReviewAgent(), cost_meter=meter).run(built["case_id"])
    return {"id": built["case_id"], "ms": (time.perf_counter() - t0) * 1000,
            "verdict": res.verdict, "cost": res.cost,
            "degraded": res.degraded, "error": ""}


def _safe_one(case: dict) -> dict:
    try:
        return _one(case)
    except Exception as exc:  # 压测里不能让单条异常中断整批
        return {"id": case.get("id", "?"), "ms": 0.0, "verdict": "",
                "cost": 0.0, "degraded": True,
                "error": f"{type(exc).__name__}: {exc}"}


def run_batch(cases: list[dict], workers: int) -> dict:
    rows: list[dict] = []
    t0 = time.perf_counter()
    if workers <= 1:
        rows = [_safe_one(c) for c in cases]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(_safe_one, cases))
    elapsed = time.perf_counter() - t0
    latencies = [r["ms"] for r in rows if not r["error"]]
    errors = [r for r in rows if r["error"]]
    return {
        "n": len(rows), "errors": len(errors),
        "elapsed_s": round(elapsed, 3),
        "throughput": round(len(rows) / elapsed, 1) if elapsed else 0.0,
        "p50_ms": _percentile(latencies, 50),
        "p95_ms": _percentile(latencies, 95),
        "p99_ms": _percentile(latencies, 99),
        "max_ms": round(max(latencies), 2) if latencies else 0.0,
        "mean_ms": round(statistics.mean(latencies), 2) if latencies else 0.0,
        "total_cost": round(sum(r["cost"] for r in rows), 6),
        "per_case_cost": round(sum(r["cost"] for r in rows) / max(1, len(rows)), 6),
        "sample_errors": [r["error"] for r in errors[:5]],
    }


def evaluate() -> dict:
    cases = list(CASES)
    seq = run_batch(cases, workers=1)
    conc = run_batch(cases * 2, workers=CONCURRENCY)  # 120 次，覆盖 10 并发
    checks = {
        "p95_within_5s": conc["p95_ms"] <= TARGET_P95_MS,
        "cost_within_0_1": conc["per_case_cost"] <= TARGET_COST,
        "no_errors": conc["errors"] == 0,
        "concurrency_10": conc["n"] == len(cases) * 2,
    }
    return {"sequential": seq, "concurrent": conc, "checks": checks,
            "targets": {"p95_ms": TARGET_P95_MS, "cost": TARGET_COST,
                        "concurrency": CONCURRENCY}}


def render(result: dict) -> str:
    s, c = result["sequential"], result["concurrent"]
    checks = result["checks"]
    lines = ["# 性能评测报告（自动生成）\n"]
    lines.append(f"> 目标（D7）：P95 ≤ {result['targets']['p95_ms']}ms、"
                 f"单票成本 ≤ ¥{result['targets']['cost']}、并发 {result['targets']['concurrency']}。\n")
    lines.append("| 场景 | 请求数 | 并发 | 吞吐(次/s) | P50 | P95 | P99 | 最大 | 单票成本 | 错误 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    lines.append(f"| 串行 | {s['n']} | 1 | {s['throughput']} | {s['p50_ms']}ms | "
                 f"{s['p95_ms']}ms | {s['p99_ms']}ms | {s['max_ms']}ms | "
                 f"¥{s['per_case_cost']:.6f} | {s['errors']} |")
    lines.append(f"| 并发 | {c['n']} | {result['targets']['concurrency']} | {c['throughput']} | "
                 f"{c['p50_ms']}ms | {c['p95_ms']}ms | {c['p99_ms']}ms | {c['max_ms']}ms | "
                 f"¥{c['per_case_cost']:.6f} | {c['errors']} |")
    lines.append("\n## 验收检查\n")
    for key, ok in checks.items():
        lines.append(f"- {'✅' if ok else '❌'} `{key}`")
    if c["sample_errors"]:
        lines.append("\n## 错误样例\n")
        for e in c["sample_errors"]:
            lines.append(f"- {e}")
    lines.append("\n> 说明：离线 mock 模型，延迟是单进程内存计算；"
                 "生产环境应加上网络与数据库的耗时。")
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
    path = os.path.join(out_dir, "perf.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    with open(os.path.join(out_dir, "perf.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(md)
    print(f"\n报告已写入 {path}")


if __name__ == "__main__":
    main()
