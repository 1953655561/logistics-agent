"""与基线比对，任何退化 exit 1（CI / 每阶段收尾都跑）。

    python scripts/baseline_check.py            # 用 evals/report/baseline.json
    python scripts/baseline_check.py --init     # 没有基线时先建一份
"""
from __future__ import annotations

import sys

import baseline_lib as bl


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    argv = sys.argv[1:] if argv is None else argv

    base = bl.load()
    if base is None:
        if "--init" in argv:
            data = bl.snapshot()
            bl.write(data)
            print("基线不存在，已生成：" + bl.BASELINE)
            return 0
        print("缺少基线，请先运行 `python scripts/baseline.py`")
        return 2

    cur = bl.snapshot()
    bad = bl.compare(base, cur)

    print(f"基线时间：{base.get('created_at')}")
    print(f"{'指标':<22}{'基线':>12}{'当前':>12}")
    print("-" * 48)
    be, ce = base["eval"], cur["eval"]
    for key in ("accuracy", "recall", "false_positive_case_rate", "citation_coverage"):
        print(f"{key:<22}{be[key]:>12.4f}{ce[key]:>12.4f}")
    print(f"{'hand_doc.issue_count':<22}{base['hand_doc']['issue_count']:>12}"
          f"{cur['hand_doc']['issue_count']:>12}")
    print(f"{'tests.total':<22}{base['tests']['total']:>12}{cur['tests']['total']:>12}")
    print()

    if bad:
        print("❌ 发现退化：")
        for item in bad:
            print("  - " + item)
        return 1
    print("✅ 未发现退化")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
