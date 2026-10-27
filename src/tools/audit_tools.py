"""审核用工具集：Agent 通过它们读取单证、跑规则、检索条款。"""
from __future__ import annotations

import json

from ..common import get as get_path
from ..engine import audit
from ..rag.retriever import default_retriever
from ..harness.tools import Tool, ToolRegistry


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
        # 不在这里截断：审核单的问题清单要完整落库（曾硬编码 issues[:20]，
        # 导致问题 >20 条的票在 Web/CLI 上被静默截掉后 9 条）。
        # 上下文预算由调用方控制（harness/loop.py 的 _summarize 只取前 5 条进 LLM）。
        by_rule: dict[str, int] = {}
        for it in issues:
            by_rule[it["rule_id"]] = by_rule.get(it["rule_id"], 0) + 1
        return {"verdict": report["verdict"], "issue_count": len(issues),
                "by_rule": dict(sorted(by_rule.items())), "issues": issues}

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
        hits = default_retriever().search(query, top_k=top_k)
        out = []
        for h in hits:
            item = {k: h.get(k) for k in ("chunk_id", "doc", "section", "text", "score")}
            if h.get("rule_id"):
                item["rule_id"] = h["rule_id"]
            out.append(item)
        return {"hits": out}

    reg.register(Tool(
        name="rule.search",
        description="混合检索规则库与要素目录，返回带定位信息的条款片段（chunk_id 可回查原文）",
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
