"""语料构建：把规则库文档与要素目录切成带定位信息的 chunk。"""
from __future__ import annotations

import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RULE_DOC = os.path.join(ROOT, "docs", "01-rule-library.md")
ELEMENTS = os.path.join(ROOT, "data", "rules", "elements.json")

_ROW = re.compile(r"^\|\s*\**\s*(L\d-\d{2})\s*\**\s*\|")


def _rule_chunks() -> list[dict]:
    chunks = []
    if not os.path.exists(RULE_DOC):
        return chunks
    with open(RULE_DOC, encoding="utf-8") as f:
        for line in f:
            m = _ROW.match(line.strip())
            if not m:
                continue
            cells = [c.strip().replace("**", "") for c in line.strip().strip("|").split("|")]
            if len(cells) < 5:
                continue
            rid, title, logic, conclusion, source = cells[0], cells[1], cells[2], cells[3], cells[4]
            layer = rid[:2]
            chunks.append({
                "chunk_id": f"rules#{rid}",
                "doc": "规则库",
                "section": f"{rid} {title}",
                "layer": layer,
                "rule_id": rid,
                "text": f"{rid} {title}：{logic}。违反结论 {conclusion}。来源：{source}。",
            })
    return chunks


def _element_chunks() -> list[dict]:
    chunks = []
    if not os.path.exists(ELEMENTS):
        return chunks
    with open(ELEMENTS, encoding="utf-8") as f:
        data = json.load(f)
    for hs, spec in data.items():
        if hs.startswith("_"):
            continue
        names = "、".join(e["name"] for e in spec.get("elements", []))
        chunks.append({
            "chunk_id": f"elements#{hs}",
            "doc": "规范申报目录",
            "section": f"申报要素 {hs} {spec.get('name', '')}",
            "hs": hs,
            "text": f"商品编号 {hs}（{spec.get('name', '')}）的规范申报要素：{names}。",
        })
    return chunks


def load_corpus() -> list[dict]:
    return _rule_chunks() + _element_chunks()
