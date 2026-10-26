"""单元测试：规则正确性与结论聚合。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.synth.generator import build_case, make_docs, m_amount_0975, m_cif_freight, \
    m_fob_no_freight, m_royalty  # noqa: E402
from src.common import name_match, norm_unit, rel_diff, within  # noqa: E402
from src.engine import audit  # noqa: E402
from src.issue import worst  # noqa: E402


def run(docs):
    return audit(docs)


class TestCommon(unittest.TestCase):
    def test_rel_diff(self):
        # 分母取较大绝对值，故 100 vs 101 的差为 1/101
        self.assertAlmostEqual(rel_diff(100, 101), 1 / 101, places=6)
        self.assertEqual(rel_diff(0, 0), 0.0)

    def test_within_tolerance_boundary(self):
        self.assertTrue(within(1000, 990, 0.01))     # 正好 1%
        self.assertFalse(within(1000, 989, 0.01))

    def test_name_match_cross_language(self):
        self.assertTrue(name_match("塑料制玩具配件", "PLASTIC TOY PARTS"))
        self.assertFalse(name_match("塑料制玩具配件", "PVC管件"))

    def test_unit_normalize(self):
        self.assertEqual(norm_unit("千克"), "kg")
        self.assertEqual(norm_unit("件"), "pcs")
        self.assertEqual(norm_unit("PCS"), "pcs")


class TestVerdict(unittest.TestCase):
    def test_worst(self):
        self.assertEqual(worst("PASS", "FIX"), "FIX")
        self.assertEqual(worst("FIX", "REVIEW", "PASS"), "REVIEW")
        self.assertEqual(worst("REJECT", "REVIEW"), "REJECT")
        self.assertEqual(worst("PASS", "PASS"), "PASS")


class TestRules(unittest.TestCase):
    def test_baseline_passes(self):
        self.assertEqual(run(make_docs())["verdict"], "PASS")

    def test_amount_tolerance(self):
        docs = make_docs()
        # 总额容差 0.1%：0.05% 应通过
        docs["declaration"]["total_amount"] = round(docs["invoice"]["total_amount"] * 0.9995, 2)
        self.assertEqual(run(docs)["verdict"], "PASS")
        m_amount_0975(docs)
        self.assertEqual(run(docs)["verdict"], "FIX")

    def test_fob_requires_freight(self):
        docs = make_docs()          # 默认 FOB 且已申报运保费
        self.assertEqual(run(docs)["verdict"], "PASS")
        m_fob_no_freight(docs)
        reps = {r.rule_id: r.conclusion for r in run(docs)["rules"]}
        self.assertEqual(reps["L2-19"], "FIX")

    def test_cif_must_not_double_count(self):
        docs = make_docs()
        m_cif_freight(docs)
        reps = {r.rule_id: r.conclusion for r in run(docs)["rules"]}
        self.assertEqual(reps["L2-19"], "FIX")

    def test_royalty_not_declared(self):
        docs = make_docs()
        m_royalty(docs)
        reps = {r.rule_id: r.conclusion for r in run(docs)["rules"]}
        self.assertEqual(reps["L4-41"], "REVIEW")

    def test_declaration_deadline(self):
        docs = make_docs()
        docs["declaration"]["declare_date"] = "2026-10-20"   # 进境 30 天后
        reps = {r.rule_id: r.conclusion for r in run(docs)["rules"]}
        self.assertEqual(reps["L4-42"], "REVIEW")

    def test_prohibited_rejects(self):
        docs = make_docs()
        docs["declaration"]["items"][0]["name"] = "旧机电设备"
        self.assertEqual(run(docs)["verdict"], "REJECT")

    def test_missing_doc_is_review(self):
        docs = make_docs()
        docs.pop("bl")
        self.assertEqual(run(docs)["verdict"], "REVIEW")

    def test_rule_exception_does_not_crash(self):
        docs = make_docs()
        docs["declaration"]["items"] = [{"hs_code": None}]
        r = run(docs)
        self.assertIn(r["verdict"], {"FIX", "REVIEW", "REJECT"})


class TestScenarios(unittest.TestCase):
    def test_all_cases_build(self):
        from data.synth.scenarios import CASES
        for c in CASES:
            built = build_case(c)
            self.assertIn("docs", built)
            self.assertIn(built["expected"]["verdict"], {"PASS", "FIX", "REVIEW", "REJECT"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
