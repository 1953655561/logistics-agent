"""生成基线快照：python scripts/baseline.py"""
from __future__ import annotations

import sys

import baseline_lib as bl


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    data = bl.snapshot()
    path = bl.write(data)
    ev = data["eval"]
    print(f"基线已写入 {path}")
    print(f"  60 例：准确率 {ev['accuracy']:.1%} 召回 {ev['recall']:.1%} "
          f"误报 {ev['false_positive_case_rate']:.1%} 引用 {ev['citation_coverage']:.1%}")
    print(f"  手改单 {data['hand_doc']['issue_count']} 条；干净样例 "
          f"{data['clean_doc']['issue_count']} 条 {data['clean_doc']['rules']}")
    print(f"  测试 {data['tests']['total']} 条 ok={data['tests']['ok']}；"
          f"门禁 {sum(1 for g in data['gate'] if g['ok'])}/{len(data['gate'])}")
    return 0 if data["tests"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
