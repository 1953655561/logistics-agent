"""审核用工具集：Agent 通过它们读取单证、跑规则、检索条款。"""
from __future__ import annotations

import json

from ..common import get as get_path
from ..engine import audit
from ..registry import RULES
from ..harness.tools import Tool, ToolRegistry

_RULE_META = {r["id"]: r for r in RULES}


def build_registry(docs: dict) -> ToolRegistry:
    reg = ToolRegistry()

    def doc_get(doc: str, path: str):
        if doc not in docs:
            raise ValueError(f"单证不存在: {doc}")
        return get_path(docs[doc], path)

    reg.register(Tool(
        name="doc.get",
        description="按路径读取某份单证的字段，例如 doc=declaration, path=items[0].hs_code",
        schema={
            "type": "object",
            "properties": {
                "doc": {"type": "string", "enum": ["contract", "invoice", "packing_list", "bl", "declaration"]},
                "path": {"type": "string"},
            },
            "required": ["doc", "path"],
            "additionalProperties": False,
        },
        fn=doc_get,
    ))

    def doc_summary():
        present = sorted(docs)
        items = get_path(docs, "declaration.items", []) or []
        return {
            "docs": present,
            "missing": [d for d in ("contract", "invoice", "packing_list", "bl", "declaration")
                        if d not in docs],
            "item_count": len(items),
            "total_amount": get_path(docs, "invoice.total_amount"),
            "currency": get_path(docs, "invoice.currency"),
        }

    reg.register(Tool(
        name="doc.summary",
        description="单证齐套性与关键字段概览",
        schema={"type": "object", "properties": {}, "additionalProperties": False},
        fn=doc_summary,
    ))

    def rules_audit(layer: str = ""):
        report = audit(docs)
        issues = [i for i in report["issues"] if (not layer or i["layer"] == layer)]
        return {"verdict": report["verdict"], "issue_count": len(issues),
                "issues": issues[:20]}

    reg.register(Tool(
        name="rules.audit",
        description="执行 L1/L2/L4 确定性规则审核，可选按层过滤",
        schema={
            "type": "object",
            "properties": {"layer": {"type": "string", "enum": ["", "L1", "L2", "L3", "L4"]}},
            "additionalProperties": False,
        },
        fn=rules_audit,
    ))

    def rule_search(query: str, top_k: int = 3):
        q = (query or "").strip().upper()
        hits = []
        for rid, meta in _RULE_META.items():
            hay = f"{rid} {meta['title']} {meta['source']}".upper()
            if q and q in hay:
                hits.append({"rule_id": rid, "title": meta["title"], "source": meta["source"]})
        if not hits and q:
            for rid, meta in _RULE_META.items():
                if any(tok and tok in (meta["title"] + meta["source"]).upper()
                       for tok in [q]):
                    hits.append({"rule_id": rid, "title": meta["title"], "source": meta["source"]})
        return {"hits": hits[:top_k]}

    reg.register(Tool(
        name="rule.search",
        description="按规则编号或关键词检索条款来源，用于给结论补充引用",
        schema={
            "type": "object",
            "properties": {"query": {"type": "string"},
                           "top_k": {"type": "integer", "minimum": 1, "maximum": 10}},
            "required": ["query"],
            "additionalProperties": False,
        },
        fn=rule_search,
    ))

    def case_draft(verdict: str, summary: str):
        return {"verdict": verdict, "summary": summary,
                "issue_count": len(get_path(docs, "declaration.items", []) or [])}

    reg.register(Tool(
        name="case.draft",
        description="生成审核单草稿（不落库，由应用层持久化）",
        schema={
            "type": "object",
            "properties": {"verdict": {"type": "string", "enum": ["PASS", "FIX", "REVIEW", "REJECT"]},
                           "summary": {"type": "string"}},
            "required": ["verdict", "summary"],
            "additionalProperties": False,
        },
        fn=case_draft,
    ))
    return reg


def dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)
