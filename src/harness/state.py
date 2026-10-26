"""审核单状态机：非法流转直接拒绝。"""
from __future__ import annotations

from dataclasses import dataclass

STATES = ("DRAFT", "REVIEWING", "PENDING_APPROVAL", "APPROVED", "RETURNED", "FAILED")

TRANSITIONS = {
    "DRAFT": {"REVIEWING", "FAILED"},
    "REVIEWING": {"PENDING_APPROVAL", "APPROVED", "RETURNED", "FAILED"},
    "PENDING_APPROVAL": {"APPROVED", "RETURNED", "FAILED"},
    "APPROVED": set(),
    "RETURNED": {"REVIEWING"},     # 补正后重审
    "FAILED": set(),
}


class InvalidTransition(Exception):
    pass


def can_transition(src: str, dst: str) -> bool:
    return dst in TRANSITIONS.get(src, set())


@dataclass
class CaseRecord:
    case_id: str
    state: str = "DRAFT"
    payload: dict | None = None
    created_at: str = ""
    updated_at: str = ""
