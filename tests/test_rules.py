"""单元测试：规则正确性与结论聚合。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.synth.generator import build_case, make_docs, m_amount_0975, m_cif_freight, \
    m_fob_no_freight, m_royalty  # noqa: E402
from src.common import name_match, norm_unit, party_match, rel_diff, within  # noqa: E402
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

    def test_name_match_near_miss_is_rejected(self):
        # 一词之差（玩具 -> 具）不应被 0.5 的 jaccard 放过
        self.assertFalse(name_match("塑料制玩具配件", "塑料制具配件"))

    def test_party_match_legal_suffix_and_typo(self):
        self.assertTrue(party_match("GLOBAL TOYS PTE LTD", "GLOBAL TOYS LIMITED"))
        self.assertFalse(party_match("GLOBAL TOYS PTE LTD", "GLOBAL TOS PTE LTD"))

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

    def test_near_miss_name_is_review(self):
        docs = make_docs()
        docs["bl"]["items"][0]["name"] = "塑料制具配件"
        reps = {r.rule_id: r.conclusion for r in run(docs)["rules"]}
        self.assertEqual(reps["L2-11"], "REVIEW")

    def test_party_mismatch_is_review(self):
        docs = make_docs()
        docs["contract"]["buyer"] = "宁波另一家贸易有限公司"
        docs["bl"]["shipper"] = "GLOBAL TOS PTE LTD"
        report = run(docs)
        reps = {r.rule_id: r.conclusion for r in report["rules"]}
        self.assertEqual(reps["L2-18"], "REVIEW")
        messages = [i["message"] for i in report["issues"] if i["rule_id"] == "L2-18"]
        self.assertTrue(any("买方" in m for m in messages))
        self.assertTrue(any("发货人" in m for m in messages))

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


class TestW63RuleFixes(unittest.TestCase):
    """v1.5 补洞回归：脏数据不得静默通过，规则口径要覆盖到发票/箱单。"""

    def test_invalid_date_is_reported_not_skipped(self):
        docs = make_docs()
        docs["invoice"]["date"] = "2026-0901"
        docs["packing_list"]["date"] = "2026-09s-01"
        report = run(docs)
        reps = {r.rule_id: r.conclusion for r in report["rules"]}
        self.assertEqual(reps["L1-02"], "FIX")
        messages = [i["message"] for i in report["issues"] if i["rule_id"] == "L1-02"]
        self.assertEqual(sum("格式非法" in m for m in messages), 2)

    def test_missing_date_is_not_a_format_error(self):
        docs = make_docs()
        docs["packing_list"]["date"] = ""
        reps = {r.rule_id: r.conclusion for r in run(docs)["rules"]}
        self.assertEqual(reps["L1-02"], "PASS")

    def test_unparseable_arrival_blocks_deadline_check(self):
        docs = make_docs()
        docs["bl"]["arrival_date"] = "2026-0v9-20"
        report = run(docs)
        reps = {r.rule_id: r.conclusion for r in report["rules"]}
        self.assertEqual(reps["L4-42"], "FIX")
        self.assertTrue(any("无法核定" in i["message"]
                            for i in report["issues"] if i["rule_id"] == "L4-42"))

    def test_overdue_still_review(self):
        docs = make_docs()
        docs["bl"]["arrival_date"] = "2026-09-01"
        docs["declaration"]["declare_date"] = "2026-10-15"
        self.assertEqual({r.rule_id: r.conclusion for r in run(docs)["rules"]}["L4-42"],
                         "REVIEW")

    def test_trade_mode_code_table_is_enforced(self):
        docs = make_docs()
        docs["declaration"]["trade_mode"] = "一般d贸易"
        docs["declaration"]["exemption_nature"] = "照章d征税"
        report = run(docs)
        self.assertEqual({r.rule_id: r.conclusion for r in report["rules"]}["L4-35"], "FIX")
        self.assertTrue(any("代码表" in i["message"]
                            for i in report["issues"] if i["rule_id"] == "L4-35"))

    def test_incoterm_code_and_cross_doc_consistency(self):
        docs = make_docs()
        docs["invoice"]["incoterm"] = "FOpB"
        report = run(docs)
        self.assertEqual({r.rule_id: r.conclusion for r in report["rules"]}["L2-19"], "FIX")
        self.assertTrue(any("代码非法" in i["message"]
                            for i in report["issues"] if i["rule_id"] == "L2-19"))
        docs = make_docs()
        docs["contract"]["incoterm"] = "CIF"
        docs["declaration"]["incoterm"] = "CIF"
        report = run(docs)
        self.assertTrue(any("不一致" in i["message"]
                            for i in report["issues"] if i["rule_id"] == "L2-19"))

    def test_hs_format_checked_on_every_doc(self):
        docs = make_docs()
        docs["invoice"]["items"][0]["hs_code"] = "9503008g900"
        docs["packing_list"]["items"][0]["hs_code"] = "9503008v900"
        report = run(docs)
        paths = [i["field_path"] for i in report["issues"] if i["rule_id"] == "L1-10"]
        self.assertIn("invoice.items[0].hs_code", paths)
        self.assertIn("packing_list.items[0].hs_code", paths)

    def test_units_validated_and_second_legal_unit_required(self):
        docs = make_docs()
        docs["invoice"]["items"][0]["unit"] = "个f"
        docs["invoice"]["items"][0]["legal_unit2"] = "千克d"
        paths = [i["field_path"] for i in run(docs)["issues"] if i["rule_id"] == "L1-04"]
        self.assertIn("invoice.items[0].unit", paths)
        self.assertIn("invoice.items[0].legal_unit2", paths)
        docs = make_docs()
        docs["declaration"]["items"][0]["legal_unit2"] = ""
        self.assertTrue(any("第二计量单位" in i["message"]
                            for i in run(docs)["issues"] if i["rule_id"] == "L1-04"))

    def test_invoice_contract_no_must_match(self):
        docs = make_docs()
        docs["invoice"]["contract_no"] = "C-2020-9999"
        report = run(docs)
        self.assertEqual({r.rule_id: r.conclusion for r in report["rules"]}["L2-21"], "FIX")
        self.assertIn("发票合同号与合同不一致",
                      [i["message"] for i in report["issues"] if i["rule_id"] == "L2-21"])

    def test_currency_code_checked_on_contract_too(self):
        docs = make_docs()
        docs["contract"]["currency"] = "US"
        messages = [i["message"] for i in run(docs)["issues"] if i["rule_id"] == "L1-03"]
        self.assertTrue(any("合同币制代码非法" in m for m in messages))

    def test_realistic_samples_keep_expected_verdicts(self):
        """真实感样例不得因新校验冒出多余结论。"""
        import json
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "examples", "realistic")
        with open(os.path.join(base, "REAL-001-standard-toys-PASS.json"), encoding="utf-8") as f:
            self.assertEqual(audit(json.load(f))["verdict"], "PASS")
        with open(os.path.join(base, "REAL-002-amount-mismatch-FIX.json"), encoding="utf-8") as f:
            rep = audit(json.load(f))
        self.assertEqual(rep["verdict"], "FIX")
        self.assertEqual(sorted({i["rule_id"] for i in rep["issues"]}), ["L2-13"])


class TestW64Rules(unittest.TestCase):
    """v1.6 规则扩展：合同金额、交易双方卖方链、要素跨单、四单口径。"""

    def _reps(self, docs):
        return {r.rule_id: r.conclusion for r in run(docs)["rules"]}

    def test_contract_amount_mismatch(self):
        docs = make_docs()
        docs["contract"]["total_amount"] = 1000.0     # 发票 48000，差 10 倍
        self.assertEqual(self._reps(docs)["L2-23"], "FIX")
        messages = [i["message"] for i in run(docs)["issues"] if i["rule_id"] == "L2-23"]
        self.assertTrue(any("合同总额与发票总额" in m for m in messages))

    def test_contract_amount_within_batch_tolerance(self):
        docs = make_docs()
        docs["contract"]["total_amount"] = round(docs["invoice"]["total_amount"] * 0.995, 2)
        self.assertEqual(self._reps(docs)["L2-23"], "PASS")

    def test_contract_amount_missing_is_skipped(self):
        docs = make_docs()
        docs["contract"].pop("total_amount")
        self.assertEqual(self._reps(docs)["L2-23"], "PASS")

    def test_contract_seller_vs_invoice_seller(self):
        docs = make_docs()
        docs["contract"]["seller"] = "GLOBAL TOS PTE LTD"
        report = run(docs)
        messages = [i["message"] for i in report["issues"] if i["rule_id"] == "L2-18"]
        self.assertIn("合同卖方与发票卖方不一致", messages)

    def test_cross_doc_elements_mismatch(self):
        docs = make_docs()
        docs["invoice"]["items"][0]["elements"]["brand_type"] = "无品g牌"
        docs["invoice"]["items"][0]["elements"]["use"] = "儿童玩h具"
        report = run(docs)
        self.assertEqual(self._reps(docs)["L2-24"], "FIX")
        paths = [i["field_path"] for i in report["issues"] if i["rule_id"] == "L2-24"]
        self.assertIn("declaration.items[0].elements.brand_type", paths)
        self.assertIn("declaration.items[0].elements.use", paths)

    def test_cross_doc_elements_missing_is_left_to_l3(self):
        docs = make_docs()
        docs["declaration"]["items"][0]["elements"].pop("brand_type")
        self.assertEqual(self._reps(docs)["L2-24"], "PASS")

    def test_qty_checks_bl(self):
        docs = make_docs()
        docs["bl"]["items"][0]["qty"] = 900
        self.assertEqual(self._reps(docs)["L2-12"], "FIX")
        paths = [i["field_path"] for i in run(docs)["issues"] if i["rule_id"] == "L2-12"]
        self.assertIn("bl.items[].qty", paths)

    def test_gross_checks_declaration(self):
        docs = make_docs()
        docs["declaration"]["gross_weight"] = round(docs["packing_list"]["gross_weight"] * 1.1, 2)
        self.assertEqual(self._reps(docs)["L2-15"], "FIX")

    def test_net_checks_bl(self):
        docs = make_docs()
        docs["bl"]["net_weight"] = round(docs["packing_list"]["net_weight"] * 1.1, 2)
        self.assertEqual(self._reps(docs)["L2-16"], "FIX")

    def test_english_name_mismatch_is_low_and_keeps_pass(self):
        docs = make_docs()
        docs["bl"]["items"][0]["name_en"] = "PVC PIPE FITTING"
        report = run(docs)
        self.assertEqual(report["verdict"], "PASS")
        low = [i for i in report["issues"] if i["rule_id"] == "L2-11"]
        self.assertEqual([i["severity"] for i in low], ["low"])

    def test_multi_item_english_names_are_paired_by_name(self):
        """多商品项时英文名要按中文名配对，不能都跟发票第 0 项比。"""
        from data.synth.scenarios import CASES
        case = next(c for c in CASES if c["id"] == "IMP-0016")
        built = build_case(case)
        report = run(built["docs"])
        self.assertEqual([i for i in report["issues"] if i["rule_id"] == "L2-11"], [])

    def test_bulk_line_math_is_not_flagged(self):
        """散装货 2% 溢短装属正常，报关单行勾稽要按 3% 放宽。"""
        from data.synth.scenarios import CASES
        case = next(c for c in CASES if c["id"] == "IMP-0008")
        report = run(build_case(case)["docs"])
        self.assertEqual(report["verdict"], "PASS")
        self.assertEqual([i for i in report["issues"] if i["rule_id"] == "L1-07"], [])

    def test_tool_result_is_not_truncated(self):
        """问题超过 20 条时，工具返回给审核单的清单必须完整（曾硬编码截断到 20）。"""
        from src.adapters.llm_mock import MockLLM
        from src.harness.loop import AuditLoop
        from src.harness.tracing import MemoryTracer
        from src.tools.audit_tools import build_registry
        docs = make_docs()
        for doc in ("invoice", "packing_list", "bl", "declaration"):
            docs[doc]["items"][0]["hs_code"] = "9503008g900"
            docs[doc]["items"][0]["unit"] = "个f"
        docs["invoice"]["date"] = "2026-0901"
        docs["packing_list"]["date"] = "2026-09s-01"
        docs["bl"]["arrival_date"] = "2026-0v9-20"
        docs["contract"]["currency"] = "US"
        docs["invoice"]["currency"] = "SDG"
        docs["declaration"]["trade_mode"] = "一般d贸易"
        docs["invoice"]["incoterm"] = "FOpB"
        docs["contract"]["total_amount"] = 1000.0
        docs["contract"]["seller"] = "GLOBAL TOS PTE LTD"
        docs["invoice"]["contract_no"] = "C-2020-9999"
        docs["invoice"]["items"][0]["elements"]["brand_type"] = "无品g牌"
        docs["invoice"]["items"][0]["elements"]["use"] = "儿童玩h具"
        docs["packing_list"]["marks"]["port"] = "SHANGHAI"
        docs["declaration"]["bl_no"] = "BL-2026-9999"
        expected = len(run(docs)["issues"])
        self.assertGreater(expected, 20, f"构造的用例只有 {expected} 条问题，不够验证截断")
        res = AuditLoop(build_registry(docs), MemoryTracer(), MockLLM()).run("T-BIG")
        self.assertEqual(len(res.issues), expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
