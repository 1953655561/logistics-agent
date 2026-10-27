"""成本 / 限流 / 幂等测试。"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.synth.generator import build_case                    # noqa: E402
from data.synth.scenarios import CASES                         # noqa: E402
from src.adapters.llm_mock import MockLLM                      # noqa: E402
from src.adapters.sqlite_repo import SqliteRepo                # noqa: E402
from src.application.audit_case import CaseService             # noqa: E402
from src.harness.approval import AutoApprover                  # noqa: E402
from src.harness.cost import CostMeter, PriceTable, UsageLog   # noqa: E402
from src.harness.loop import AuditLoop                         # noqa: E402
from src.harness.ratelimit import TokenBucket                  # noqa: E402
from src.harness.tracing import MemoryTracer                   # noqa: E402
from src.tools.audit_tools import build_registry               # noqa: E402


def docs_of(case_id="IMP-0001"):
    return build_case(next(c for c in CASES if c["id"] == case_id))["docs"]


class TestPriceTable(unittest.TestCase):
    def test_cost_formula(self):
        price = PriceTable(input_per_1k=1.0, output_per_1k=2.0)
        self.assertEqual(price.cost({"input_tokens": 1000,
                                     "output_tokens": 500}), 2.0)

    def test_zero_and_bad_usage(self):
        price = PriceTable()
        self.assertEqual(price.cost(None), 0.0)
        self.assertEqual(price.cost({"input_tokens": "x"}), 0.0)

    def test_meter_accumulates(self):
        meter = CostMeter(PriceTable(input_per_1k=1.0, output_per_1k=1.0))
        meter.record({"input_tokens": 1000, "output_tokens": 0}, case_id="A")
        meter.record({"input_tokens": 0, "output_tokens": 1000}, case_id="B")
        self.assertEqual(meter.total, 2.0)
        self.assertEqual(meter.summary()["calls"], 2)
        self.assertEqual(meter.summary()["input_tokens"], 1000)

    def test_usage_log(self):
        log = UsageLog()
        log.add({"input_tokens": 10, "output_tokens": 5}, 0.5, model="m")
        log.add({"input_tokens": 1, "output_tokens": 2}, 0.25, model="m")
        self.assertEqual(log.calls, 2)
        self.assertEqual(log.input_tokens, 11)
        self.assertEqual(log.cost, 0.75)


class TestTokenBucket(unittest.TestCase):
    def test_exhaust_and_refill(self):
        now = [0.0]
        bucket = TokenBucket(rate_per_min=60, capacity=2,
                             clock=lambda: now[0])
        self.assertTrue(bucket.allow())
        self.assertTrue(bucket.allow())
        self.assertFalse(bucket.allow())
        now[0] = 2.0            # 2 秒补充 2 个令牌
        self.assertTrue(bucket.allow())

    def test_invalid_rate(self):
        with self.assertRaises(ValueError):
            TokenBucket(rate_per_min=0)


class TestLoopCostAndRateLimit(unittest.TestCase):
    def test_loop_records_cost_and_usage(self):
        meter = CostMeter()
        res = AuditLoop(build_registry(docs_of()), MemoryTracer(), MockLLM(),
                        cost_meter=meter).run("C1")
        self.assertGreater(res.cost, 0)
        self.assertEqual(res.usage["calls"], 1)
        self.assertEqual(meter.total, res.cost)

    def test_rate_limited_degrades_to_review(self):
        tracer = MemoryTracer()
        limiter = TokenBucket(rate_per_min=1, capacity=0, clock=lambda: 0.0)
        res = AuditLoop(build_registry(docs_of()), tracer, MockLLM(),
                        rate_limiter=limiter).run("C1")
        self.assertTrue(res.rate_limited)
        self.assertTrue(res.degraded)
        self.assertEqual(res.verdict, "REVIEW")
        kinds = {e.get("kind") for e in tracer.events()}
        self.assertIn("ratelimit.exceeded", kinds)

    def test_no_llm_means_zero_cost(self):
        res = AuditLoop(build_registry(docs_of()), MemoryTracer()).run("C1")
        self.assertEqual(res.cost, 0.0)


class TestIdempotency(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = SqliteRepo(os.path.join(self.tmp, "idem.db"))

    def _svc(self):
        return CaseService(self.repo, AutoApprover(), llm=MockLLM(),
                           tracer_factory=lambda cid: MemoryTracer(),
                           trace_dir=self.tmp)

    def test_duplicate_submit_returns_existing(self):
        svc = self._svc()
        first = svc.submit("DUP-1", docs_of())
        second = svc.submit("DUP-1", docs_of())
        self.assertEqual(first["payload"]["cost"], second["payload"]["cost"])
        self.assertTrue(second["payload"]["idempotency"]["hit"])
        self.assertEqual(len(self.repo.list_cases(limit=10)), 1)
        kinds = [e["kind"] for e in self.repo.events("DUP-1")]
        self.assertIn("idempotent.hit", kinds)

    def test_digest_mismatch_flagged(self):
        svc = self._svc()
        svc.submit("DUP-2", docs_of())
        changed = docs_of()
        changed.pop("bl")
        rec = svc.submit("DUP-2", changed)
        self.assertFalse(rec["payload"]["idempotency"]["digest_matches"])
        self.assertEqual(len(self.repo.list_cases(limit=10)), 1)

    def test_cost_recorded_in_payload(self):
        rec = self._svc().submit("DUP-3", docs_of())
        self.assertGreater(rec["payload"]["cost"], 0)
        self.assertEqual(rec["payload"]["usage"]["calls"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
