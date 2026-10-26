"""应用层用例：把 harness、状态机、审批、仓储串起来。

这里不出现任何框架，也不直接读写文件；全部通过端口注入。
"""
from __future__ import annotations

import os
from datetime import datetime

from ..harness.approval import build_request, needs_approval
from ..harness.loop import AuditLoop
from ..harness.tracing import JsonlTracer, summarize
from ..harness.state import can_transition
from ..tools.audit_tools import build_registry

TERMINAL = {"APPROVED", "FAILED"}


class CaseService:
    def __init__(self, repo, approver, llm=None, trace_dir: str | None = None,
                 tracer_factory=None, policy: dict | None = None, max_steps: int = 8,
                 pause_for_approval: bool = False):
        self.repo = repo
        self.approver = approver
        self.llm = llm
        self.trace_dir = trace_dir or os.path.join(os.getcwd(), "var", "traces")
        self.tracer_factory = tracer_factory
        self.policy = policy
        self.max_steps = max_steps
        self.pause_for_approval = pause_for_approval

    # ---------- 主流程 ----------
    def run(self, case_id: str, docs: dict) -> dict:
        rec = self.repo.load_case(case_id)
        if rec and rec["state"] in TERMINAL:
            raise ValueError(f"审核单 {case_id} 已结束（{rec['state']}），不可重跑")

        state = rec["state"] if rec else "DRAFT"
        payload = dict(rec["payload"]) if rec else {}
        payload["docs_digest"] = _digest(docs)
        if state == "RETURNED":
            state = self._transition(case_id, payload, "RETURNED", "REVIEWING", "补正后重审")
        elif state == "DRAFT":
            state = self._transition(case_id, payload, "DRAFT", "REVIEWING", "开始审核")

        tracer = self._tracer(case_id)
        try:
            result = AuditLoop(build_registry(docs), tracer, self.llm,
                               max_steps=self.max_steps).run(case_id)
        finally:
            trace_events = tracer.events()
            tracer.close()

        payload.update({
            "verdict": result.verdict,
            "issues": result.issues,
            "summary": result.summary,
            "citations": result.citations,
            "steps": [s.to_dict() for s in result.steps],
            "degraded": result.degraded,
            "trace": summarize(trace_events),
            "trace_path": getattr(tracer, "path", ""),
        })

        if needs_approval(result.verdict, result.issues, self.policy):
            self._transition(case_id, payload, "REVIEWING", "PENDING_APPROVAL", "转人工审批")
            if self.pause_for_approval:
                # 审核台场景：先挂起，等人工在界面上处理（resume 续跑）
                return self.repo.load_case(case_id)
            decision = self.approver.request(
                build_request(case_id, result.verdict, result.issues, result.summary))
            payload["approval"] = _decision_dict(decision)
            self.repo.append_event(case_id, {"kind": "approval", **payload["approval"]})
            dst = "APPROVED" if decision.approved else "RETURNED"
            self._transition(case_id, payload, "PENDING_APPROVAL", dst,
                             "审批通过" if decision.approved else "审批退回")
        else:
            self._transition(case_id, payload, "REVIEWING", "APPROVED", "自动通过")

        return self.repo.load_case(case_id)

    # ---------- 断点续跑 ----------
    def resume(self, case_id: str) -> dict:
        rec = self.repo.load_case(case_id)
        if not rec:
            raise ValueError(f"审核单不存在: {case_id}")
        if rec["state"] != "PENDING_APPROVAL":
            raise ValueError(f"审核单不在待审批状态（当前 {rec['state']}）")
        payload = dict(rec["payload"])
        decision = self.approver.request(
            build_request(case_id, payload.get("verdict", "REVIEW"),
                          payload.get("issues", []), payload.get("summary", "")))
        payload["approval"] = _decision_dict(decision)
        dst = "APPROVED" if decision.approved else "RETURNED"
        self._transition(case_id, payload, "PENDING_APPROVAL", dst,
                         "续跑：审批" + ("通过" if decision.approved else "退回"))
        return self.repo.load_case(case_id)

    # ---------- 内部 ----------
    def _tracer(self, case_id: str):
        if self.tracer_factory:
            return self.tracer_factory(case_id)
        path = os.path.join(self.trace_dir, f"{case_id}.jsonl")
        return JsonlTracer(path)

    def _transition(self, case_id: str, payload: dict, src: str, dst: str, reason: str) -> str:
        if not can_transition(src, dst):
            raise ValueError(f"非法状态流转：{src} → {dst}")
        self.repo.save_case({"case_id": case_id, "state": dst, "payload": payload})
        self.repo.append_event(case_id, {
            "kind": "transition", "from": src, "to": dst, "reason": reason,
            "ts": datetime.now().isoformat(timespec="seconds"),
        })
        return dst


def _decision_dict(decision) -> dict:
    return {"approved": decision.approved, "comment": decision.comment,
            "approver": decision.approver,
            "ts": datetime.now().isoformat(timespec="seconds")}


def _digest(docs: dict) -> dict:
    return {"docs": sorted(docs), "items": len((docs.get("declaration") or {}).get("items", []))}
