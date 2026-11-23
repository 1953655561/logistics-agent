"""P3 可观测性测试：幻觉指标、影子评测、告警与门禁项数。

覆盖点（都不跑满 60 条，全部用小样本构造数据）：
1. `evals/hallucination.py::measure` 的两个指标（含 PASS 用例排除、分母为 0）；
2. `evals/shadow.py::summarize` 对未标注条目的处理（不计入 reviewed/打分）；
3. `scripts/alert.py` 在门禁失败时返回 1 并落盘告警；
4. `scripts/gate.py::checks` 现在返回 11 项。
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "evals"))

import alert          # noqa: E402
import gate           # noqa: E402
import hallucination  # noqa: E402
import shadow         # noqa: E402


def _records():
    """两条非 PASS + 一条 PASS；PASS 里的高危问题不进分母。"""
    return [
        {"case_id": "T-1", "expected_verdict": "FIX", "issues": [
            {"rule_id": "L2-13", "severity": "high",
             "citation_chunk": "rules#L2-13"},
            {"rule_id": "L2-11", "severity": "high"},
            {"rule_id": "L1-04", "severity": "low"},
        ]},
        {"case_id": "T-2", "expected_verdict": "PASS", "issues": [
            {"rule_id": "L2-15", "severity": "high"},
        ]},
        {"case_id": "T-3", "expected_verdict": "REVIEW", "issues": [
            {"rule_id": "L3-25", "severity": "high",
             "citation_chunk": "rules#L3-25"},
            {"rule_id": "L3-26", "severity": "high",
             "citation_chunk": "rules#GHOST"},
        ]},
    ]


KNOWN = {"rules#L2-13", "rules#L3-25"}


class TestHallucinationMetrics(unittest.TestCase):
    def test_uncited_rate_counts_only_high_issues_of_nonpass_cases(self):
        result = hallucination.measure(_records(), KNOWN)
        # 分母：T-1 的两条 high + T-3 的两条 high = 4（PASS 的 T-2 不算）
        self.assertEqual(result["high_issues"], 4)
        self.assertEqual(result["uncited_issues"], 1)
        self.assertAlmostEqual(result["uncited_rate"], 0.25, places=6)
        self.assertEqual(result["uncited_cases"],
                         [{"case_id": "T-1", "rules": ["L2-11"]}])

    def test_broken_citation_rate_uses_all_cases(self):
        result = hallucination.measure(_records(), KNOWN)
        # 带引用 3 条（L2-13、L3-25、GHOST），其中 1 条不可回查
        self.assertEqual(result["cited_issues"], 3)
        self.assertEqual(result["broken_issues"], 1)
        self.assertAlmostEqual(result["broken_citation_rate"], 1 / 3, places=6)
        self.assertAlmostEqual(result["citation_verifiability"], 2 / 3, places=6)
        self.assertEqual(result["broken_citations"][0]["chunk_id"], "rules#GHOST")
        self.assertEqual(result["broken_citations"][0]["rule_id"], "L3-26")

    def test_empty_sample_does_not_divide_by_zero(self):
        result = hallucination.measure([], KNOWN)
        self.assertEqual(result["uncited_rate"], 0.0)
        self.assertEqual(result["broken_citation_rate"], 0.0)
        self.assertEqual(result["citation_verifiability"], 1.0)


class TestShadowUnreviewed(unittest.TestCase):
    def test_all_unreviewed_items_are_listed_but_not_scored(self):
        golden = {"doc": "x.json", "items": [
            {"rule_id": "L2-13", "field_path": "declaration.total_amount",
             "label": "unreviewed", "note": ""},
            {"rule_id": "L2-11", "field_path": "bl.items[].name",
             "label": "unreviewed", "note": ""},
        ]}
        produced = [
            {"rule_id": "L2-13", "field_path": "declaration.total_amount"},
            {"rule_id": "L2-11", "field_path": "bl.items[].name"},
        ]
        result = shadow.summarize(golden, produced, "REVIEW")
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["reviewed"], 0)
        self.assertEqual(result["reviewed_rate"], 0.0)
        self.assertIsNone(result["precision"])
        self.assertIsNone(result["recall"])
        self.assertEqual(result["scored_items"], 0)
        self.assertEqual(result["matched"], 2)
        self.assertEqual(len(result["unreviewed_items"]), 2)
        self.assertEqual(result["labels"]["unreviewed"], 2)

    def test_only_correct_and_wrong_labels_score(self):
        golden = {"doc": "x.json", "items": [
            {"rule_id": "L2-13", "field_path": "a", "label": "correct"},
            {"rule_id": "L2-11", "field_path": "b", "label": "wrong"},
            {"rule_id": "L4-40", "field_path": "c", "label": "unsure"},
            {"rule_id": "L1-10", "field_path": "d", "label": "unreviewed"},
        ]}
        produced = [
            {"rule_id": "L2-13", "field_path": "a"},
            {"rule_id": "L2-11", "field_path": "b"},
            {"rule_id": "L2-99", "field_path": "e"},
        ]
        result = shadow.summarize(golden, produced, "FIX")
        self.assertEqual(result["reviewed"], 3)      # correct + wrong + unsure
        self.assertEqual(result["scored_items"], 2)  # unsure 不评分
        self.assertAlmostEqual(result["precision"], 0.5)   # TP=1 / (TP+FP=2)
        self.assertAlmostEqual(result["recall"], 1.0)      # 唯一的 correct 被报出
        self.assertEqual(result["unsure"], 1)
        self.assertEqual(result["labels"]["unreviewed"], 1)
        self.assertIn({"rule_id": "L2-99", "field_path": "e"}, result["extra"])
        self.assertIn({"rule_id": "L4-40", "field_path": "c"},
                      result["missing"])

    def test_duplicate_keys_are_matched_as_multiset(self):
        golden = {"doc": "x.json", "items": [
            {"rule_id": "L2-18", "field_path": "declaration.consignee",
             "label": "unreviewed"},
            {"rule_id": "L2-18", "field_path": "declaration.consignee",
             "label": "unreviewed"},
        ]}
        # 引擎只报出一条 → 另一条应出现在 missing，而不是算两次命中
        produced = [{"rule_id": "L2-18",
                     "field_path": "declaration.consignee"}]
        result = shadow.summarize(golden, produced, "REVIEW")
        self.assertEqual(result["matched"], 1)
        self.assertEqual(len(result["missing"]), 1)


def _passing_reports():
    return {
        "result.json": {
            "accuracy": 1.0, "recall": 1.0,
            "false_positive_case_rate": 0.0,
            "citation": {"coverage": 1.0},
            "agent": {"per_case_cost": 0.0002},
        },
        "perf.json": {"concurrent": {"p95_ms": 100, "errors": 0}},
        "redteam.json": {"blocked": 10, "forbidden": 0},
        "hallucination.json": {"uncited_rate": 0.0,
                               "broken_citation_rate": 0.0},
        "extraction.json": {"routes": [
            {"route": "Excel（发票）", "skipped": False, "field_accuracy": 1.0},
            {"route": "文字层 PDF（五单）", "skipped": False, "field_accuracy": 1.0},
        ]},
    }


def _write_reports(directory, reports):
    os.makedirs(directory, exist_ok=True)
    for name, payload in reports.items():
        with open(os.path.join(directory, name), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)


class TestGateHasTwelveChecks(unittest.TestCase):
    def _call(self, hall, extraction=None):
        reports = _passing_reports()
        if extraction is None:
            extraction = reports["extraction.json"]
        return gate.checks(reports["result.json"], reports["perf.json"],
                           reports["redteam.json"], hall, extraction)

    def test_returns_twelve_items(self):
        items = self._call({"uncited_rate": 0.0, "broken_citation_rate": 0.0})
        self.assertEqual(len(items), 12)
        self.assertTrue(all(ok for _, ok, _ in items))

    def test_hallucination_items_are_ninth_and_tenth(self):
        items = self._call({"uncited_rate": 0.5, "broken_citation_rate": 0.5})
        self.assertEqual(len(items), 12)
        self.assertFalse(items[9][1])
        self.assertFalse(items[10][1])
        self.assertIn("无引用断言", items[9][0])
        self.assertIn("不可回查", items[10][0])

    def test_missing_hallucination_report_fails_closed(self):
        items = self._call({})
        self.assertFalse(items[9][1])
        self.assertFalse(items[10][1])

    def test_extraction_item_fails_closed(self):
        items = self._call({"uncited_rate": 0.0, "broken_citation_rate": 0.0},
                           extraction={})
        self.assertFalse(items[11][1])
        self.assertIn("抽取字段准确率", items[11][0])


class TestAlert(unittest.TestCase):
    def test_failed_gate_writes_alert_and_returns_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports = _passing_reports()
            reports["result.json"]["accuracy"] = 0.5   # 人为制造门禁失败
            _write_reports(tmp, reports)
            out = io.StringIO()
            with redirect_stdout(out):
                code, failed, path = alert.run(
                    report_dir=tmp, alerts_dir=os.path.join(tmp, "alerts"),
                    webhook="", now=datetime(2026, 1, 2, 3, 4, 5))
            self.assertEqual(code, 1)
            self.assertTrue(failed)
            self.assertTrue(path and os.path.exists(path))
            self.assertTrue(path.endswith("20260102-030405.json"))
            self.assertIn("结论准确率", out.getvalue())
            with open(path, encoding="utf-8") as f:
                payload = json.load(f)
            names = [item["name"] for item in payload["failed"]]
            self.assertIn("结论准确率 ≥ 95%", names)
            self.assertEqual(payload["gate_total"], 12)

    def test_passing_gate_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_reports(tmp, _passing_reports())
            alerts_dir = os.path.join(tmp, "alerts")
            with redirect_stdout(io.StringIO()):
                code, failed, path = alert.run(
                    report_dir=tmp, alerts_dir=alerts_dir, webhook="")
            self.assertEqual(code, 0)
            self.assertEqual(failed, [])
            self.assertIsNone(path)
            self.assertFalse(os.path.exists(alerts_dir))

    def test_disabled_webhook_is_not_an_error(self):
        with redirect_stdout(io.StringIO()):
            self.assertFalse(alert.notify("", {"failed": []}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
