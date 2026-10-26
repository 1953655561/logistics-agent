"""审核结果模型：Issue、RuleResult、结论聚合。"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

# 结论强弱：数字越大越严重
RANK = {"PASS": 0, "FIX": 1, "REVIEW": 2, "REJECT": 3}


@dataclass
class Issue:
    rule_id: str
    field_path: str
    severity: str          # high | mid | low
    message: str
    evidence: dict = field(default_factory=dict)
    suggestion: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RuleResult:
    rule_id: str
    layer: str
    title: str
    conclusion: str        # PASS | FIX | REVIEW | REJECT
    issues: list[Issue] = field(default_factory=list)
    source: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["issues"] = [i.to_dict() for i in self.issues]
        return d


def worst(*conclusions: str) -> str:
    """取最严重的结论；全是 PASS 则 PASS。"""
    out = "PASS"
    for c in conclusions:
        if RANK.get(c, 0) > RANK.get(out, 0):
            out = c
    return out
