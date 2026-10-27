"""LLM-as-Judge 测试：评分口径、不一致路径、一致率验收线。"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.synth.generator import build_case, make_docs        # noqa: E402
from data.synth.scenarios import CASES                        # noqa: E402
from evals.judge import evaluate, judge_case, rubric          # noqa: E402
from src.engine import audit                                  # noqa: E402


def built_of(case_id):
    return build_case(next(c for c in CASES if c["id"] == case_id))


class FakeLLM:
    name = "scripted"

    def __init__(self, payload):
        self.payload = payload

    def complete(self, messages, *, schema=None, max_tokens=512):
        text = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
        return {"text": text, "model": "scripted", "usage": {}}


class TestJudge(unittest.TestCase):
    def test_perfect_case_scores_full(self):
        built = built_of("IMP-0001")
        out = rubric(built, audit(built["docs"]))
        self.assertEqual(out.score, 100.0)
        self.assertTrue(out.agree)

    def test_wrong_verdict_disagrees(self):
        built = built_of("IMP-0019")           # 期望 FIX
        report = {"verdict": "PASS", "issues": []}
        out = rubric(built, report)
        self.assertFalse(out.agree)
        self.assertLess(out.score, 100)
        self.assertTrue(any("不一致" in r for r in out.reasons))

    def test_missed_defect_reduces_recall(self):
        built = built_of("IMP-0059")           # 期望 REVIEW，4 个注入缺陷
        report = {"verdict": "REVIEW", "issues": []}
        out = rubric(built, report)
        self.assertTrue(out.agree)             # 结论对
        self.assertLess(out.score, 100)        # 但召回为 0
        self.assertTrue(any("注入缺陷 0/" in r for r in out.reasons))

    def test_false_positive_penalty(self):
        built = built_of("IMP-0001")
        report = {"verdict": "PASS",
                  "issues": [{"rule_id": "L2-12", "severity": "high",
                              "citation": "内审 SOP"}]}
        out = rubric(built, report)
        self.assertEqual(out.score, 90.0)
        self.assertTrue(any("误报" in r for r in out.reasons))

    def test_llm_judge_path(self):
        built = built_of("IMP-0001")
        out = judge_case(built, audit(built["docs"]),
                         FakeLLM({"score": 88, "reasons": ["LLM 复核通过"]}))
        self.assertEqual(out.method, "llm")
        self.assertEqual(out.score, 88.0)
        self.assertEqual(out.reasons, ["LLM 复核通过"])

    def test_llm_bad_json_falls_back(self):
        built = built_of("IMP-0001")
        out = judge_case(built, audit(built["docs"]), FakeLLM("oops"))
        self.assertEqual(out.method, "rubric")
        self.assertTrue(out.degraded)

    def test_agreement_meets_acceptance_line(self):
        self.assertGreaterEqual(evaluate()["agreement"], 0.8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
