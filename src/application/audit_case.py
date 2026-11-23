"""应用层用例：把 harness、状态机、审批、仓储串起来。

这里不出现任何框架，也不直接读写文件；全部通过端口注入。

W4.5 增补：
- 输入先过护栏（控制字符、超长字段、注入、伪造引用）；
- 可选独立复核 Agent；
- 记录单票成本；可选令牌桶限流；
- `submit()` 以 case_id 做幂等：重复提交返回已有审核单，不重复建单/计费。
"""
from __future__ import annotations

import os
from datetime import datetime

from ..harness.approval import build_request, needs_approval
from ..harness.cost import CostMeter
from ..harness.guardrails import sanitize_docs
from ..harness.loop import AuditLoop
from ..harness.tracing import JsonlTracer, summarize
from ..harness.state import can_transition
from ..tools.audit_tools import build_registry

TERMINAL = {"APPROVED", "FAILED"}
IN_FLIGHT = {"REVIEWING", "PENDING_APPROVAL"}


class CaseService:
    def __init__(self, repo, approver, llm=None, trace_dir: str | None = None,
                 tracer_factory=None, policy: dict | None = None, max_steps: int = 8,
                 pause_for_approval: bool = False, reviewer=None,
                 cost_meter: CostMeter | None = None, rate_limiter=None,
                 memory=None, mode: str = "scripted", planner=None,
                 skill=None):
        self.repo = repo
        self.approver = approver
        self.llm = llm
        self.trace_dir = trace_dir or os.path.join(os.getcwd(), "var", "traces")
        self.tracer_factory = tracer_factory
        self.policy = policy
        self.max_steps = max_steps
        self.pause_for_approval = pause_for_approval
        self.reviewer = reviewer
        self.cost_meter = cost_meter or CostMeter()
        self.rate_limiter = rate_limiter
        # 记忆：只产出 history_hints（提示），不参与结论
        self.memory = memory
        self.mode = mode
        self.planner = planner
        # 技能只影响说明文本的写法（拼进 _summarize 的系统提示），不参与判定
        self.skill = skill

    # ---------- 幂等提交（推荐入口） ----------
    def submit(self, case_id: str, docs: dict) -> dict:
        """重复提交同一 case_id：返回已有审核单，不重跑、不重复计费。"""
        rec = self.repo.load_case(case_id)
        if rec and (rec["state"] in TERMINAL or rec["state"] in IN_FLIGHT):
            payload = dict(rec.get("payload") or {})
            clean, _ = sanitize_docs(docs)
            payload["idempotency"] = {
                "hit": True,
                "state": rec["state"],
                "digest_matches": payload.get("docs_digest") == _digest(clean),
                "ts": datetime.now().isoformat(timespec="seconds"),
            }
            self.repo.save_case({"case_id": case_id, "state": rec["state"],
                                 "payload": payload})
            self.repo.append_event(case_id, {"kind": "idempotent.hit",
                                             **payload["idempotency"]})
            return self.repo.load_case(case_id)
        return self.run(case_id, docs)

    # ---------- 主流程 ----------
    def run(self, case_id: str, docs: dict) -> dict:
        rec = self.repo.load_case(case_id)
        if rec and rec["state"] in TERMINAL:
            raise ValueError(f"审核单 {case_id} 已结束（{rec['state']}），不可重跑")

        docs, guard_findings = sanitize_docs(docs)
        state = rec["state"] if rec else "DRAFT"
        payload = dict(rec["payload"]) if rec else {}
        payload["docs_digest"] = _digest(docs)
        payload["guardrail"] = guard_findings
        if state == "RETURNED":
            state = self._transition(case_id, payload, "RETURNED", "REVIEWING", "补正后重审")
        elif state == "DRAFT":
            state = self._transition(case_id, payload, "DRAFT", "REVIEWING", "开始审核")

        tracer = self._tracer(case_id)
        # 历史提示：只读记忆，产出提示字段；不参与规则、不改结论
        hints = []
        if self.memory is not None:
            try:
                hints = self.memory.hints(docs)
            except Exception as exc:
                self.tracer_emit_safe(tracer, case_id, "memory.skip", str(exc))
            payload["history_hints"] = hints
            if hints:
                self.tracer_emit_safe(tracer, case_id, "memory.hints", len(hints))
        try:
            result = AuditLoop(
                build_registry(docs), tracer, self.llm, max_steps=self.max_steps,
                reviewer=self.reviewer, guard_findings=guard_findings,
                cost_meter=self.cost_meter, rate_limiter=self.rate_limiter,
                mode=self.mode, planner=self.planner, memory={},
                skill=self.skill,
            ).run(case_id)
        finally:
            trace_events = tracer.events()
            tracer.close()

        # 审核结束写记忆（供下一次提示），失败不影响主流程
        if self.memory is not None:
            try:
                self.memory.remember(case_id, docs, result.issues)
            except Exception:
                pass

        payload.update({
            "verdict": result.verdict,
            "issues": result.issues,
            "summary": result.summary,
            "citations": result.citations,
            "steps": [s.to_dict() for s in result.steps],
            "degraded": result.degraded,
            "review": result.review,
            "guard": result.guard,
            "usage": result.usage,
            "cost": result.cost,
            "rate_limited": result.rate_limited,
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

    # ---------- Web 审核台：人工决策 ----------
    def decide(self, case_id: str, approved: bool, comment: str = "",
               approver: str = "web") -> dict:
        """审核台直接给出审批决定（不再经 ApproverPort 交互）。"""
        rec = self.repo.load_case(case_id)
        if not rec:
            raise ValueError(f"审核单不存在: {case_id}")
        if rec["state"] != "PENDING_APPROVAL":
            raise ValueError(f"审核单不在待审批状态（当前 {rec['state']}）")
        if not approved and not str(comment).strip():
            raise ValueError("退回必须填写理由")
        payload = dict(rec["payload"])
        payload["approval"] = {
            "approved": bool(approved),
            "comment": str(comment),
            "approver": approver,
            "ts": datetime.now().isoformat(timespec="seconds"),
        }
        self.repo.append_event(case_id, {"kind": "approval", **payload["approval"]})
        dst = "APPROVED" if approved else "RETURNED"
        self._transition(case_id, payload, "PENDING_APPROVAL", dst,
                         "审核台：" + ("通过" if approved else "退回"))
        return self.repo.load_case(case_id)

    # ---------- 内部 ----------
    @staticmethod
    def tracer_emit_safe(tracer, case_id: str, kind: str, detail) -> None:
        """trace 只是旁路观测，写失败不能拖垮审核主流程。"""
        try:
            tracer.emit({"kind": kind, "case_id": case_id, "detail": detail})
        except Exception:
            pass

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
