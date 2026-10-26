"""人工审批门：判断是否需要人参与，并承载审批人实现。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Decision:
    approved: bool
    comment: str = ""
    approver: str = "system"


@dataclass
class ApprovalRequest:
    case_id: str
    verdict: str
    summary: str
    issues: list[dict] = field(default_factory=list)
    suggested_action: str = ""

    def to_dict(self) -> dict:
        return {"case_id": self.case_id, "verdict": self.verdict,
                "summary": self.summary, "issues": self.issues,
                "suggested_action": self.suggested_action}


DEFAULT_POLICY = {
    "always_review": ["REJECT", "REVIEW"],   # 这两个结论必须人工确认
    "fix_with_high": True,                   # FIX 且含高危问题时也要人确认
}


def needs_approval(verdict: str, issues: list[dict], policy: dict | None = None) -> bool:
    p = {**DEFAULT_POLICY, **(policy or {})}
    if verdict in p["always_review"]:
        return True
    if p["fix_with_high"] and verdict == "FIX":
        return any(i.get("severity") == "high" for i in issues)
    return False


def build_request(case_id: str, verdict: str, issues: list[dict], summary: str = "") -> ApprovalRequest:
    action = {
        "REJECT": "退回货主，说明不得申报的理由",
        "REVIEW": "主管复核：确认问题是否成立，决定补正或退回",
        "FIX": "报关员确认补正建议后重新提交",
        "PASS": "无需动作",
    }.get(verdict, "人工确认")
    return ApprovalRequest(case_id=case_id, verdict=verdict, summary=summary,
                           issues=issues, suggested_action=action)


class AutoApprover:
    """非交互场景（评测/演示）：全部通过，但记录为 auto。"""

    def __init__(self, approve: bool = True):
        self._approve = approve

    def request(self, request: ApprovalRequest) -> Decision:
        return Decision(self._approve, "自动通过" if self._approve else "自动退回", "auto")


class ScriptedApprover:
    """测试用：按预设序列返回决定。"""

    def __init__(self, decisions: list[Decision]):
        self._decisions = list(decisions)
        self.requests: list[ApprovalRequest] = []

    def request(self, request: ApprovalRequest) -> Decision:
        self.requests.append(request)
        if not self._decisions:
            return Decision(False, "无预设决定，默认退回", "scripted")
        return self._decisions.pop(0)


class CliApprover:
    """命令行交互审批。"""

    def request(self, request: ApprovalRequest) -> Decision:
        print("\n=== 需要人工审批 ===")
        print(f"审核单: {request.case_id}   结论: {request.verdict}")
        for it in request.issues[:10]:
            print(f"  - [{it.get('rule_id')}] {it.get('message')}")
        if request.suggested_action:
            print(f"建议动作: {request.suggested_action}")
        ans = input("批准？(y/N) ").strip().lower()
        comment = input("审批意见: ").strip() if ans == "y" else input("退回理由: ").strip()
        return Decision(ans == "y", comment, "cli")
