"""影子评测：用人工标注的 golden 文件校准当前引擎，但**只对已标注条目打分**。

    python evals/shadow.py

设计前提：人工标注是稀缺资源，`evals/golden/human-labelled.json` 里绝大多数
条目还停在 `unreviewed`。因此：

- `reviewed/total` 只统计 label 不再是 `unreviewed` 的条目（含 `unsure`）；
- precision / recall **只用 label 为 `correct` / `wrong` 的条目**，`unsure` 与
  `unreviewed` 一律不参与打分；
- 没有任何可打分条目时，precision / recall 输出 `null`，报告写「不参与打分」，
  绝不拿 0 当作结论；
- 未标注条目在报告里逐条列出，方便后续人工补齐。

标签语义：
- `correct`：该问题确实存在（引擎报对了）→ 引擎仍报出计 TP，报不出计 FN；
- `wrong`：该问题是误报（引擎报错了）→ 引擎仍报出计 FP；
- `unsure`：人工也拿不准，只计入 reviewed，不参与 precision / recall。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.engine import audit                                    # noqa: E402

GOLDEN = os.path.join(ROOT, "evals", "golden", "human-labelled.json")
LABELS = ("unreviewed", "correct", "wrong", "unsure")


def load_golden(path: str = GOLDEN) -> dict:
    if not os.path.exists(path):
        raise SystemExit(f"缺少 golden 文件 {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def engine_items(doc_path: str) -> tuple[dict, list[dict]]:
    """跑当前引擎，返回（审核报告, 问题清单）。"""
    if not os.path.exists(doc_path):
        raise SystemExit(f"缺少单证样例 {doc_path}")
    with open(doc_path, encoding="utf-8") as f:
        docs = json.load(f)
    report = audit(docs)
    return report, report["issues"]


def _match(golden_items: list[dict], produced: list[dict]) -> tuple[set[int], dict]:
    """按 (rule_id, field_path) 做多重集匹配，处理同一键重复报出的情况。"""
    pool: dict[tuple, int] = {}
    for item in produced:
        key = (item.get("rule_id"), item.get("field_path"))
        pool[key] = pool.get(key, 0) + 1

    found: set[int] = set()
    missing: list[dict] = []
    for idx, item in enumerate(golden_items):
        key = (item.get("rule_id"), item.get("field_path"))
        if pool.get(key, 0) > 0:
            pool[key] -= 1
            found.add(idx)
        else:
            missing.append(_brief(item))

    extra: list[dict] = []
    for key, left in pool.items():
        for _ in range(left):
            extra.append({"rule_id": key[0], "field_path": key[1]})
    return found, {"missing": missing, "extra": extra}


def _brief(item: dict) -> dict:
    return {"rule_id": item.get("rule_id", ""),
            "field_path": item.get("field_path", "")}


def summarize(golden: dict, produced: list[dict], verdict: str = "") -> dict:
    """纯函数：golden 与当前引擎结果比对，只对已标注条目算 precision/recall。"""
    items = golden.get("items") or []
    counts = {label: 0 for label in LABELS}
    for item in items:
        label = item.get("label") or "unreviewed"
        if label not in counts:
            label = "unreviewed"
        counts[label] += 1

    found, diff = _match(items, produced)

    labelled = [(i, item) for i, item in enumerate(items)
                if (item.get("label") or "unreviewed") != "unreviewed"]
    reviewed = len(labelled)

    tp = fp = fn = unsure = 0
    labelled_items: list[dict] = []
    for idx, item in labelled:
        label = item.get("label")
        hit = idx in found
        if label == "correct":
            tp += 1 if hit else 0
            fn += 0 if hit else 1
        elif label == "wrong":
            fp += 1 if hit else 0
        else:                                   # unsure：只记录，不评分
            unsure += 1
        labelled_items.append({**(_brief(item)), "label": label,
                               "found_by_engine": hit})

    scored = tp + fp + fn
    precision = round(tp / (tp + fp), 4) if (tp + fp) else None
    recall = round(tp / (tp + fn), 4) if (tp + fn) else None

    unreviewed_items = [{**(_brief(item)), "note": item.get("note", "")}
                        for item in items
                        if (item.get("label") or "unreviewed") == "unreviewed"]
    return {
        "doc": golden.get("doc", ""),
        "engine_verdict": verdict,
        "engine_issue_count": len(produced),
        "total": len(items),
        "reviewed": reviewed,
        "reviewed_rate": round(reviewed / len(items), 4) if items else 0.0,
        "labels": counts,
        "matched": len(found),
        "missing": diff["missing"],
        "extra": diff["extra"],
        "precision": precision,
        "recall": recall,
        "tp": tp, "fp": fp, "fn": fn, "unsure": unsure,
        "scored_items": scored,
        "labelled_items": labelled_items,
        "unreviewed_items": unreviewed_items,
        "note": ("precision/recall 仅基于 correct/wrong 标注；unsure 与 unreviewed "
                 "不参与打分。未标注时输出 null，不按 0 计。"),
    }


def evaluate() -> dict:
    golden = load_golden()
    doc_path = golden.get("doc", "")
    if doc_path and not os.path.isabs(doc_path):
        doc_path = os.path.join(ROOT, doc_path)
    report, produced = engine_items(doc_path)
    result = summarize(golden, produced, report.get("verdict", ""))
    result["observed_at"] = datetime.now().isoformat(timespec="seconds")
    return result


def render(result: dict) -> str:
    lines = ["# 影子评测报告（human-labelled，自动生成）\n"]
    lines.append(f"- 单证：`{result['doc']}`")
    lines.append(f"- 当前引擎：结论 **{result['engine_verdict']}**，"
                 f"问题 **{result['engine_issue_count']}** 条")
    lines.append(f"- 人工标注进度：**{result['reviewed']}/{result['total']}**"
                 f"（{result['reviewed_rate']:.0%}）")
    if result["precision"] is None and result["recall"] is None:
        lines.append("- precision / recall：**不参与打分**"
                     "（没有 label=correct/wrong 的条目）")
    else:
        p = "—" if result["precision"] is None else f"{result['precision']:.1%}"
        r = "—" if result["recall"] is None else f"{result['recall']:.1%}"
        lines.append(f"- precision：**{p}**，recall：**{r}**"
                     f"（TP={result['tp']} FP={result['fp']} FN={result['fn']}，"
                     f"共 {result['scored_items']} 条参与打分）")
    dist = "、".join(f"{k} {v}" for k, v in result["labels"].items())
    lines.append(f"- 标注分布：{dist}")
    lines.append(f"- 与当前引擎对账：命中 **{result['matched']}**/"
                 f"{result['total']}，golden 有而引擎没有 "
                 f"{len(result['missing'])} 条，引擎多报 {len(result['extra'])} 条")

    if result["missing"]:
        lines.append("\n## golden 有、当前引擎未报出\n")
        for item in result["missing"]:
            lines.append(f"- `{item['rule_id']}` {item['field_path']}")
    if result["extra"]:
        lines.append("\n## 当前引擎多报、golden 里没有\n")
        for item in result["extra"]:
            lines.append(f"- `{item['rule_id']}` {item['field_path']}")

    if result["labelled_items"]:
        lines.append("\n## 已标注条目（参与打分）\n")
        lines.append("| 规则 | 字段 | 标注 | 引擎是否报出 |")
        lines.append("|---|---|---|---|")
        for item in result["labelled_items"]:
            hit = "是" if item["found_by_engine"] else "否"
            lines.append(f"| {item['rule_id']} | {item['field_path']} "
                         f"| {item['label']} | {hit} |")

    lines.append("\n## 未标注条目（不参与打分，仅列出）\n")
    if not result["unreviewed_items"]:
        lines.append("- 无：全部条目都已标注。")
    else:
        lines.append("| 规则 | 字段 |")
        lines.append("|---|---|")
        for item in result["unreviewed_items"]:
            lines.append(f"| {item['rule_id']} | {item['field_path']} |")

    lines.append("\n> 说明：人工标注文件 `evals/golden/human-labelled.json` 里全部条目"
                 "初始为 `unreviewed`，本报告**不伪造**人工结论；标注补齐后重跑本脚本"
                 "即可得到 precision / recall。")
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
    md_path = os.path.join(out_dir, "shadow.md")
    with open(md_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(md)
    with open(os.path.join(out_dir, "shadow.json"), "w",
              encoding="utf-8", newline="\n") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(md)
    print(f"\n报告已写入 {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
