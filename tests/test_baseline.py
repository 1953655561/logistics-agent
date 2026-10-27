"""基线快照与回归比对测试。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import baseline_lib as bl  # noqa: E402


def snap(acc=1.0, recall=1.0, fp=0.0, cite=1.0, hand=29,
         rules=None, gate_all_ok=True, tests_ok=True, tests_total=179):
    return {
        "eval": {"accuracy": acc, "recall": recall,
                 "false_positive_case_rate": fp, "citation_coverage": cite},
        "hand_doc": {"issue_count": hand},
        "clean_doc": {"rules": rules if rules is not None else ["L2-13"]},
        "gate": [{"name": "x", "ok": gate_all_ok, "actual": "-"}],
        "tests": {"total": tests_total, "ok": tests_ok},
    }


class TestBaselineCompare(unittest.TestCase):
    def test_identical_snapshot_has_no_regression(self):
        self.assertEqual(bl.compare(snap(), snap()), [])

    def test_accuracy_drop_is_regression(self):
        bad = bl.compare(snap(), snap(acc=0.98))
        self.assertTrue(any("准确率" in x for x in bad))

    def test_recall_drop_is_regression(self):
        bad = bl.compare(snap(), snap(recall=0.97))
        self.assertTrue(any("召回" in x for x in bad))

    def test_false_positive_rise_is_regression(self):
        bad = bl.compare(snap(), snap(fp=0.05))
        self.assertTrue(any("误报" in x for x in bad))

    def test_citation_drop_is_regression(self):
        bad = bl.compare(snap(), snap(cite=0.9))
        self.assertTrue(any("引用" in x for x in bad))

    def test_fewer_hand_doc_issues_is_regression(self):
        bad = bl.compare(snap(), snap(hand=28))
        self.assertTrue(any("漏报" in x for x in bad))

    def test_clean_doc_rule_change_is_regression(self):
        bad = bl.compare(snap(), snap(rules=["L2-13", "L2-14"]))
        self.assertTrue(any("干净样例" in x for x in bad))

    def test_failed_gate_is_regression(self):
        bad = bl.compare(snap(), snap(gate_all_ok=False))
        self.assertTrue(any("门禁" in x for x in bad))

    def test_failing_tests_is_regression(self):
        bad = bl.compare(snap(), snap(tests_ok=False))
        self.assertTrue(any("测试" in x for x in bad))

    def test_fewer_tests_is_regression(self):
        bad = bl.compare(snap(), snap(tests_total=170))
        self.assertTrue(any("测试数" in x for x in bad))

    def test_improvement_is_not_regression(self):
        """变好不该被判成退化（例如问题数增加、准确率仍是 100%）。"""
        self.assertEqual(bl.compare(snap(), snap(hand=35)), [])


class TestSnapshotShape(unittest.TestCase):
    def test_snapshot_keys(self):
        data = bl.snapshot(with_tests=False)
        for key in ("eval", "agent", "perf", "redteam", "gate",
                    "hand_doc", "clean_doc", "tests"):
            self.assertIn(key, data)
        self.assertEqual(len(data["gate"]), 11)
        self.assertGreater(data["hand_doc"]["issue_count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
