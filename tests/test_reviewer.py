"""多 Agent 复核测试：同意 / 升级 / 降级 / 过判观察 / LLM 路径。"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.synth.generator import build_case                     # noqa: E402
from data.synth.scenarios import CASES                          # noqa: E402
from src.agents.reviewer import ReviewAgent, reconcile          # noqa: E402
from src.harness.loop import AuditLoop                          # noqa: E402
from src.harness.tracing import MemoryTracer                    # noqa: E402
from src.tools.audit_tools import build_registry                # noqa: E402


def docs_of(case_id: str) -> dict:
    return build_case(next(c for c in CASES if c["id"] == case_id))["docs"]


def high_issue(rule_id="L2-13", cited=True, **extra) -> dict:
    issue = {"rule_id": rule_id, "field_path": "declaration.total_amount",
             "severity": "high", "message": "金额不一致"}
    if cited:
        issue["citation_chunk"] = "rules#L2-13"
        issue["citation"] = "内审 SOP"
    issue.update(extra)
    return issue


class FakeLLM:
    name = "scripted"

    def __init__(self, payload):
        self.payload = payload

    def complete(self, messages, *, schema=None, max_tokens=512):
        text = self.payload if isinstance(self.payload, str) else json.dumps(
            self.payload, ensure_ascii=False)
        return {"text": text, "model": "scripted", "usage": {}}


class TestReviewAgent(unittest.TestCase):
    def test_agree_on_clean_result(self):
        r = ReviewAgent().review("PASS", [], [])
        self.assertTrue(r.agree)
        self.assertEqual(r.recommendation, "agree")
        self.assertEqual(r.doubts, [])

    def test_escalate_when_high_issue_has_no_citation(self):
        r = ReviewAgent().review("FIX", [high_issue(cited=False)], [])
        self.assertFalse(r.agree)
        self.assertIn("evidence_gap", {d["code"] for d in r.doubts})
        final, changed = reconcile("FIX", r)
        self.assertEqual(final, "REVIEW")
        self.assertTrue(changed)

    def test_reject_downgrades_to_review_on_doubt(self):
        r = ReviewAgent().review("REJECT", [high_issue(cited=False)], [])
        self.assertEqual(r.recommendation, "downgrade")
        final, changed = reconcile("REJECT", r)
        self.assertEqual(final, "REVIEW")
        self.assertTrue(changed)

    def test_unknown_rule_is_blocking(self):
        r = ReviewAgent().review("FIX", [high_issue(rule_id="L9-99")], [])
        self.assertIn("unknown_rule", {d["code"] for d in r.doubts})
        self.assertFalse(r.agree)

    def test_repeat_rule_is_advisory(self):
        # 真重复：同一规则 + 同一字段 + 同一证据
        issues = [high_issue(), high_issue()]
        r = ReviewAgent().review("FIX", issues, [])
        self.assertIn("repeat_rule", {o["code"] for o in r.observations})
        self.assertEqual(r.recommendation, "advisory")
        final, changed = reconcile("FIX", r)
        self.assertEqual(final, "FIX")
        self.assertFalse(changed)

    def test_same_rule_on_different_docs_is_not_repeat(self):
        """逐单证/逐字段各报一次不是重复上报（v1.6 之前会误判成过判）。"""
        issues = [high_issue(evidence={"invoice": "a", "found": "b"}),
                  high_issue(evidence={"invoice": "a", "found": "c"})]
        r = ReviewAgent().review("FIX", issues, [])
        self.assertNotIn("repeat_rule", {o["code"] for o in r.observations})

    def test_same_rule_different_field_is_not_repeat(self):
        issues = [high_issue(), high_issue(field_path="declaration.currency")]
        r = ReviewAgent().review("FIX", issues, [])
        self.assertNotIn("repeat_rule", {o["code"] for o in r.observations})

    def test_keyword_only_prohibition_is_advisory(self):
        issue = high_issue(rule_id="L4-36",
                           evidence={"match": "keyword", "keyword": "旧机电"})
        r = ReviewAgent().review("REJECT", [issue], [])
        self.assertIn("keyword_only_prohibition",
                      {o["code"] for o in r.observations})
        # 观察不改变结论（由人决定是否退回）
        final, changed = reconcile("REJECT", r)
        self.assertEqual(final, "REJECT")
        self.assertFalse(changed)

    def test_llm_disagreement_escalates(self):
        llm = FakeLLM({"agree": False, "doubts": ["引用不足"], "reason": "证据不足"})
        r = ReviewAgent(llm).review("FIX", [high_issue()], [])
        self.assertIn("llm_disagreement", {d["code"] for d in r.doubts})
        final, changed = reconcile("FIX", r)
        self.assertEqual(final, "REVIEW")
        self.assertTrue(changed)

    def test_llm_bad_json_degrades_without_crash(self):
        r = ReviewAgent(FakeLLM("not-json")).review("PASS", [], [])
        self.assertTrue(r.degraded)
        self.assertEqual(r.recommendation, "agree")

    def test_mock_llm_is_skipped(self):
        class Mock:
            name = "mock"

            def complete(self, *a, **k):
                raise AssertionError("mock 不应被调用")

        r = ReviewAgent(Mock()).review("PASS", [], [])
        self.assertEqual(r.source, "rules")


class TestDualChain(unittest.TestCase):
    def test_dual_chain_keeps_verdict_on_real_case(self):
        res = AuditLoop(build_registry(docs_of("IMP-0019")), MemoryTracer(),
                        reviewer=ReviewAgent()).run("IMP-0019")
        self.assertEqual(res.verdict, "FIX")
        self.assertTrue(res.review)

    def test_dual_chain_escalates_on_missing_citation(self):
        """构造一个没有引用的高危问题，验证“复核推翻”路径真的会改结论。"""
        # 主链路给 PASS，复核发现高危问题无引用 → 升为 REVIEW
        r = ReviewAgent().review("PASS", [high_issue(cited=False)], [])
        final, changed = reconcile("PASS", r)
        self.assertEqual((final, changed), ("REVIEW", True))

    def test_at_least_three_over_judged_cases(self):
        n = 0
        for case in CASES:
            built = build_case(case)
            res = AuditLoop(build_registry(built["docs"]), MemoryTracer(),
                            reviewer=ReviewAgent()).run(built["case_id"])
            if (res.review or {}).get("observations"):
                n += 1
        self.assertGreaterEqual(n, 3)

    def test_review_adds_a_step_within_budget(self):
        res = AuditLoop(build_registry(docs_of("IMP-0043")), MemoryTracer(),
                        reviewer=ReviewAgent()).run("IMP-0043")
        self.assertLessEqual(len(res.steps), 8)
        self.assertTrue(any(s.name == "独立复核" for s in res.steps))

    def test_three_reconcile_paths(self):
        from evals.review_compare import path_probes
        probes = path_probes()
        self.assertTrue(all(p["ok"] for p in probes))
        self.assertEqual(sum(p["changed"] for p in probes), 2)   # 升级 + 降级
        self.assertEqual(probes[-1]["recommendation"], "advisory")


if __name__ == "__main__":
    unittest.main(verbosity=2)
