"""W3 Harness 测试：工具层、状态机、审批、循环、端到端。"""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.synth.generator import build_case               # noqa: E402
from data.synth.scenarios import CASES                    # noqa: E402
from src.adapters.sqlite_repo import SqliteRepo           # noqa: E402
from src.application.audit_case import CaseService        # noqa: E402
from src.harness.approval import (AutoApprover, Decision,  # noqa: E402
                                  ScriptedApprover, needs_approval)
from src.harness.loop import AuditLoop                    # noqa: E402
from src.harness.state import can_transition              # noqa: E402
from src.harness.tools import Tool, ToolError, ToolRegistry  # noqa: E402
from src.harness.tracing import JsonlTracer, MemoryTracer, summarize  # noqa: E402
from src.tools.audit_tools import build_registry          # noqa: E402


def docs_of(case_id: str) -> dict:
    case = next(c for c in CASES if c["id"] == case_id)
    return build_case(case)["docs"]


class TestTools(unittest.TestCase):
    def setUp(self):
        self.reg = ToolRegistry()

    def test_argument_validation(self):
        self.reg.register(Tool("echo", "echo", {
            "type": "object",
            "properties": {"x": {"type": "string", "enum": ["a", "b"]},
                           "n": {"type": "integer", "minimum": 1}},
            "required": ["x"], "additionalProperties": False}, lambda x, n=1: (x, n)))
        self.assertTrue(self.reg.call("echo").ok is False)          # 缺必填
        self.assertFalse(self.reg.call("echo", x="c").ok)           # 枚举外
        self.assertFalse(self.reg.call("echo", x="a", n=0).ok)      # 小于最小值
        self.assertFalse(self.reg.call("echo", x="a", z=1).ok)      # 多余参数
        ok = self.reg.call("echo", x="a", n=2)
        self.assertTrue(ok.ok)
        self.assertEqual(ok.value, ("a", 2))

    def test_unknown_tool(self):
        self.assertFalse(self.reg.call("nope").ok)

    def test_retry_then_success(self):
        state = {"n": 0}

        def flaky():
            state["n"] += 1
            if state["n"] < 3:
                raise RuntimeError("transient")
            return "ok"

        self.reg.register(Tool("flaky", "flaky", {"type": "object", "properties": {}},
                               flaky, retries=2))
        res = self.reg.call("flaky")
        self.assertTrue(res.ok)
        self.assertEqual(res.attempts, 3)

    def test_timeout(self):
        self.reg.register(Tool("slow", "slow", {"type": "object", "properties": {}},
                               lambda: time.sleep(0.3), timeout_s=0.05, retries=0))
        res = self.reg.call("slow")
        self.assertFalse(res.ok)
        self.assertIn("超时", res.error)

    def test_duplicate_registration(self):
        self.reg.register(Tool("t", "", {"type": "object", "properties": {}}, lambda: 1))
        with self.assertRaises(ToolError):
            self.reg.register(Tool("t", "", {"type": "object", "properties": {}}, lambda: 1))


class TestState(unittest.TestCase):
    def test_transitions(self):
        self.assertTrue(can_transition("DRAFT", "REVIEWING"))
        self.assertTrue(can_transition("PENDING_APPROVAL", "APPROVED"))
        self.assertTrue(can_transition("RETURNED", "REVIEWING"))
        self.assertFalse(can_transition("APPROVED", "REVIEWING"))
        self.assertFalse(can_transition("DRAFT", "APPROVED"))


class TestApprovalPolicy(unittest.TestCase):
    def test_policy(self):
        high = [{"rule_id": "L2-13", "severity": "high"}]
        low = [{"rule_id": "L1-02", "severity": "low"}]
        self.assertFalse(needs_approval("PASS", [], None))
        self.assertFalse(needs_approval("FIX", low, None))
        self.assertTrue(needs_approval("FIX", high, None))
        self.assertTrue(needs_approval("REVIEW", low, None))
        self.assertTrue(needs_approval("REJECT", [], None))
        self.assertFalse(needs_approval("REVIEW", [], {"always_review": []}))

    def test_scripted_approver_records(self):
        ap = ScriptedApprover([Decision(True, "ok", "tester")])
        from src.harness.approval import build_request
        d = ap.request(build_request("C1", "REVIEW", []))
        self.assertTrue(d.approved)
        self.assertEqual(len(ap.requests), 1)


class TestRepoAndTrace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = SqliteRepo(os.path.join(self.tmp, "t.db"))

    def test_case_roundtrip(self):
        self.repo.save_case({"case_id": "C1", "state": "DRAFT", "payload": {"a": 1}})
        rec = self.repo.load_case("C1")
        self.assertEqual(rec["state"], "DRAFT")
        self.assertEqual(rec["payload"]["a"], 1)
        self.repo.save_case({"case_id": "C1", "state": "REVIEWING", "payload": {"a": 2}})
        self.assertEqual(self.repo.load_case("C1")["state"], "REVIEWING")
        self.assertEqual(len(self.repo.list_cases()), 1)

    def test_events(self):
        self.repo.append_event("C1", {"kind": "x", "v": 1})
        self.repo.append_event("C1", {"kind": "y", "v": 2})
        self.assertEqual([e["kind"] for e in self.repo.events("C1")], ["x", "y"])

    def test_jsonl_tracer(self):
        path = os.path.join(self.tmp, "trace.jsonl")
        tr = JsonlTracer(path)
        tr.emit({"kind": "step", "name": "a", "ok": True, "ms": 1.0})
        tr.emit({"kind": "step", "name": "b", "ok": False, "ms": 2.0})
        tr.close()
        with open(path, encoding="utf-8") as f:
            lines = [json.loads(x) for x in f]
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]["kind"], "step")
        self.assertEqual(summarize(lines)["failed"], 1)


class TestLoop(unittest.TestCase):
    def _loop(self, docs, **kw):
        return AuditLoop(build_registry(docs), MemoryTracer(), **kw)

    def test_pass_case_runs_within_budget(self):
        res = self._loop(docs_of("IMP-0001")).run("C1")
        self.assertEqual(res.verdict, "PASS")
        self.assertFalse(res.degraded)
        self.assertLessEqual(len(res.steps), 8)

    def test_missing_docs_goes_review(self):
        docs = docs_of("IMP-0001")
        docs.pop("bl")
        res = self._loop(docs).run("C1")
        self.assertEqual(res.verdict, "REVIEW")
        self.assertTrue(res.degraded)

    def test_budget_exceeded_degrades(self):
        res = self._loop(docs_of("IMP-0025"), max_steps=2).run("C1")
        self.assertTrue(res.degraded)
        self.assertEqual(res.verdict, "REVIEW")

    def test_llm_failure_keeps_verdict(self):
        class Boom:
            name = "boom"

            def complete(self, *a, **k):
                raise RuntimeError("no network")

        res = AuditLoop(build_registry(docs_of("IMP-0019")), MemoryTracer(), Boom()).run("C1")
        self.assertEqual(res.verdict, "FIX")
        self.assertTrue(res.degraded)
        self.assertIn("结论", res.summary)

    def test_citation_enrichment(self):
        res = self._loop(docs_of("IMP-0019")).run("C1")
        self.assertTrue(any(i.get("citation_text") for i in res.issues))


class TestService(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = SqliteRepo(os.path.join(self.tmp, "db.sqlite"))

    def _svc(self, approver, **kw):
        return CaseService(self.repo, approver, tracer_factory=lambda cid: MemoryTracer(),
                           trace_dir=self.tmp, **kw)

    def test_pass_auto_approves(self):
        rec = self._svc(AutoApprover()).run("PASS-1", docs_of("IMP-0001"))
        self.assertEqual(rec["state"], "APPROVED")
        self.assertNotIn("approval", rec["payload"])

    def test_review_pauses_then_resume_approves(self):
        svc = self._svc(AutoApprover(), pause_for_approval=True)
        rec = svc.run("REV-1", docs_of("IMP-0025"))
        self.assertEqual(rec["state"], "PENDING_APPROVAL")

        svc2 = self._svc(ScriptedApprover([Decision(True, "确认无误", "主管")]))
        done = svc2.resume("REV-1")
        self.assertEqual(done["state"], "APPROVED")
        self.assertEqual(done["payload"]["approval"]["approver"], "主管")

    def test_deny_returns(self):
        svc = self._svc(ScriptedApprover([Decision(False, "材料不全", "主管")]))
        rec = svc.run("REV-2", docs_of("IMP-0025"))
        self.assertEqual(rec["state"], "RETURNED")
        # 退回后可补正重审
        svc2 = self._svc(AutoApprover())
        again = svc2.run("REV-2", docs_of("IMP-0001"))
        self.assertEqual(again["state"], "APPROVED")

    def test_resume_wrong_state(self):
        svc = self._svc(AutoApprover())
        svc.run("REV-3", docs_of("IMP-0001"))
        with self.assertRaises(ValueError):
            svc.resume("REV-3")

    def test_cannot_rerun_finished(self):
        svc = self._svc(AutoApprover())
        svc.run("REV-4", docs_of("IMP-0001"))
        with self.assertRaises(ValueError):
            svc.run("REV-4", docs_of("IMP-0001"))

    def test_events_recorded(self):
        svc = self._svc(AutoApprover())
        svc.run("REV-5", docs_of("IMP-0019"))
        kinds = [e["kind"] for e in self.repo.events("REV-5")]
        self.assertIn("transition", kinds)
        self.assertGreaterEqual(len(kinds), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
