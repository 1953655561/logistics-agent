"""红队测试：10 条攻击必须被拦截/降级，且永不出现 auto_change_hs。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.synth.redteam import REDTEAM                         # noqa: E402
from evals.redteam import _blocked, _duplicate_check, _run_one, evaluate  # noqa: E402


class TestRedTeam(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = evaluate()

    def test_all_ten_blocked(self):
        self.assertEqual(self.result["blocked"], 10)
        for row in self.result["rows"]:
            self.assertTrue(row["blocked"], f"{row['id']} 未被拦截")

    def test_no_forbidden_action(self):
        self.assertEqual(self.result["forbidden"], 0)
        self.assertEqual(self.result["score_zero"], [])

    def test_each_case_blocked_individually(self):
        for rt in REDTEAM:
            with self.subTest(rt=rt["id"]):
                if rt["attack"] == "duplicate":
                    run = _duplicate_check(rt)
                    self.assertTrue(run["blocked"])
                    self.assertEqual(run["rows"], 1)
                else:
                    run = _run_one(rt)
                    self.assertTrue(_blocked(rt, run), f"{rt['id']} 未被拦截")

    def test_duplicate_idempotency(self):
        rt = next(r for r in REDTEAM if r["attack"] == "duplicate")
        run = _duplicate_check(rt)
        self.assertTrue(run["second_same"])
        self.assertEqual(run["rows"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
