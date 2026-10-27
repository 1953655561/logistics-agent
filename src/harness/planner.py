"""规划器：决定"为了验证某条问题，去回查哪些字段"。

用途：react 模式下做**证据补采**（verification pass）——不把整份单证塞进上下文，
只按问题去取需要的那几个字段，把结果挂在 issue 上供人核对。

两种实现：
- `DeterministicPlanner`：规则 → 字段的静态映射，离线/评测默认用这个（可复现、零成本）；
- `LLMPlanner`：让模型在**允许的候选字段**里挑（白名单 + 上限），失败自动退回确定性策略。

硬约束：规划器只决定"读什么"，不决定"结论是什么"，也不改 verdict。
"""
from __future__ import annotations

# 规则 → 需要回查的字段（doc, path）。刻意只放"能证伪该问题"的最小集合。
VERIFY_TARGETS: dict[str, list[tuple[str, str]]] = {
    "L1-02": [("invoice", "date"), ("packing_list", "date"), ("bl", "date"),
              ("bl", "arrival_date"), ("declaration", "declare_date")],
    "L1-03": [("declaration", "currency"), ("contract", "currency"),
              ("invoice", "currency")],
    "L1-04": [("declaration", "items[0].unit"), ("declaration", "items[0].legal_unit2"),
              ("invoice", "items[0].unit")],
    "L1-07": [("invoice", "items[0].amount"), ("declaration", "items[0].amount")],
    "L1-10": [("invoice", "items[0].hs_code"), ("packing_list", "items[0].hs_code")],
    "L2-11": [("invoice", "items[0].name"), ("packing_list", "items[0].name"),
              ("bl", "items[0].name"), ("declaration", "items[0].name")],
    "L2-13": [("declaration", "total_amount"), ("invoice", "total_amount")],
    "L2-14": [("declaration", "currency"), ("invoice", "currency")],
    "L2-18": [("bl", "consignee"), ("bl", "notify"), ("declaration", "consignee"),
              ("contract", "buyer"), ("invoice", "buyer")],
    "L2-19": [("invoice", "incoterm"), ("declaration", "incoterm"),
              ("contract", "incoterm"), ("declaration", "freight")],
    "L2-21": [("declaration", "contract_no"), ("invoice", "contract_no"),
              ("contract", "contract_no")],
    "L2-22": [("packing_list", "marks.port"), ("bl", "pod")],
    "L2-23": [("contract", "total_amount"), ("invoice", "total_amount")],
    "L2-24": [("invoice", "items[0].elements"), ("declaration", "items[0].elements")],
    "L4-35": [("declaration", "trade_mode"), ("declaration", "exemption_nature")],
    "L4-40": [("declaration", "bl_no"), ("bl", "bl_no")],
    "L4-42": [("bl", "arrival_date"), ("declaration", "declare_date")],
    "L4-44": [("declaration", "license_expiry"), ("declaration", "declare_date"),
              ("declaration", "license_qty")],
}

MAX_VERIFY_ISSUES = 4
MAX_VERIFY_CALLS = 8

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "targets": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"doc": {"type": "string"}, "path": {"type": "string"}},
                "required": ["doc", "path"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["targets"],
    "additionalProperties": False,
}


class DeterministicPlanner:
    name = "deterministic"

    def plan(self, issues: list, allowed: dict[str, list[tuple[str, str]]] | None = None,
             max_calls: int = MAX_VERIFY_CALLS) -> list[dict]:
        targets = allowed or VERIFY_TARGETS
        out: list[dict] = []
        for issue in issues[:MAX_VERIFY_ISSUES]:
            rid = str(issue.get("rule_id", ""))
            for doc, path in targets.get(rid, []):
                if len(out) >= max_calls:
                    return out
                if any(t["doc"] == doc and t["path"] == path for t in out):
                    continue
                out.append({"doc": doc, "path": path, "rule_id": rid})
        return out


class LLMPlanner:
    """让模型在候选字段里挑要回查的项；输出不是合法白名单就退回确定性策略。"""

    name = "llm"

    def __init__(self, llm, fallback: DeterministicPlanner | None = None):
        self.llm = llm
        self.fallback = fallback or DeterministicPlanner()

    def plan(self, issues: list, allowed: dict[str, list[tuple[str, str]]] | None = None,
             max_calls: int = MAX_VERIFY_CALLS) -> list[dict]:
        targets = allowed or VERIFY_TARGETS
        rid = str((issues[0] or {}).get("rule_id", "")) if issues else ""
        candidates = [{"doc": d, "path": p} for d, p in targets.get(rid, [])]
        if not candidates or self.llm is None:
            return self.fallback.plan(issues, targets, max_calls)
        try:
            out = self.llm.complete([
                {"role": "system", "content":
                 "你在为一票报关单做证据回查。只能从给定候选字段里选，选最能证伪该问题的。"},
                {"role": "user", "content":
                 f"问题规则 {rid}；候选字段 {candidates}；最多选 {max_calls} 个。"},
            ], schema=PLAN_SCHEMA, max_tokens=200)
            picked = (out or {}).get("data") or (out or {})
            targets_out = []
            allowed_pairs = {(c["doc"], c["path"]) for c in candidates}
            for item in (picked.get("targets") or []):
                doc, path = str(item.get("doc", "")), str(item.get("path", ""))
                if (doc, path) in allowed_pairs:          # 白名单校验
                    targets_out.append({"doc": doc, "path": path, "rule_id": rid})
            return targets_out[:max_calls] or self.fallback.plan(issues, targets, max_calls)
        except Exception:
            return self.fallback.plan(issues, targets, max_calls)


def build_planner(mode: str, llm=None):
    """scripted 模式不需要规划器；react 模式有真模型就用 LLM，否则用确定性。"""
    if mode != "react":
        return None
    if llm is not None and getattr(llm, "name", "") != "mock":
        return LLMPlanner(llm)
    return DeterministicPlanner()
