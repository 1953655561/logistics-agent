"""WebApi 应用服务测试：列表、审核、审批、单证、trace、指标、原始文件上传。"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.synth.generator import build_case                     # noqa: E402
from data.synth.scenarios import CASES                          # noqa: E402
from src.adapters.llm_mock import MockLLM                       # noqa: E402
from src.adapters.sqlite_repo import SqliteRepo                 # noqa: E402
from src.agents.reviewer import ReviewAgent                     # noqa: E402
from src.application.audit_case import CaseService              # noqa: E402
from src.application.web_api import WebApi, WebApiError         # noqa: E402
from src.engine import RULES                                    # noqa: E402
from src.harness.approval import AutoApprover                   # noqa: E402
from src.harness.cost import CostMeter                          # noqa: E402
from src.harness.tracing import JsonlTracer                     # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "examples" / "raw"
XLSX = RAW / "合成发票-INV-2026-0901.xlsx"
PDF_DIR = RAW / "pdf"
PDF_FILES = [PDF_DIR / name for name in
             ("合同-HT-2026-0901.pdf", "装箱单-PL-2026-0901.pdf",
              "提单-SYN-2026-0901.pdf", "报关单-DEC-2026-0901.pdf")]

try:
    import openpyxl  # noqa: F401
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

try:
    import pypdf  # noqa: F401
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False


def _case(case_id: str) -> dict:
    return next(c for c in CASES if c["id"] == case_id)


def make_web(tmp: str) -> WebApi:
    repo = SqliteRepo(os.path.join(tmp, "web.db"))
    service = CaseService(
        repo, AutoApprover(), llm=MockLLM(),
        tracer_factory=lambda cid: JsonlTracer(os.path.join(tmp, f"{cid}.jsonl")),
        trace_dir=tmp, pause_for_approval=True,
        reviewer=ReviewAgent(), cost_meter=CostMeter(),
    )
    scenarios = [{k: c.get(k) for k in ("id", "title", "expected", "tags")}
                 for c in CASES]

    def build_docs(case_id: str) -> dict:
        return build_case(_case(case_id))["docs"]

    return WebApi(repo, service, trace_dir=tmp, scenarios=scenarios,
                  build_docs=build_docs, rules=RULES,
                  report_path=os.path.join(tmp, "result.json"),
                  docs_dir=os.path.join(tmp, "docs"))


class TestWebApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.web = make_web(self.tmp)

    def test_health_and_catalog(self):
        self.assertEqual(self.web.health()["scenarios"], 60)
        self.assertEqual(self.web.health()["rules"], 46)
        self.assertEqual(len(self.web.list_scenarios()), 60)
        self.assertEqual(len(self.web.list_rules()), 46)

    def test_health_exposes_model(self):
        """health 必须能看出"当前用什么模型"，而不是靠界面写死。"""
        model = self.web.health()["model"]
        self.assertIn("offline", model)
        self.assertIn("routes", model)
        self.assertTrue(model["offline"])                 # make_web 用的是 MockLLM
        self.assertEqual(model["llm"], "mock")

    def test_health_reports_online_router(self):
        from src.harness.router import ModelRouter
        from src.application.web_api import WebApi

        router = ModelRouter(api_key="sk-test")
        web = WebApi(self.web.repo, self.web.service, self.web.trace_dir,
                     scenarios=self.web.scenarios, build_docs=self.web.build_docs,
                     rules=self.web.rules, router=router)
        model = web.health()["model"]
        self.assertFalse(model["offline"])
        self.assertEqual(model["routes"]["review"], "strong")
        self.assertEqual(model["tiers"]["cheap"], "gpt-4o-mini")

    def test_list_empty(self):
        self.assertEqual(self.web.list_cases(), [])

    def test_audit_pass_and_detail(self):
        rec = self.web.audit("IMP-0016")
        self.assertEqual(rec["state"], "APPROVED")
        self.assertEqual(rec["verdict"], "PASS")
        self.assertEqual(rec["title"], "50 项临界")
        self.assertEqual(rec["issues"], [])
        self.assertTrue(rec["has_trace"])
        self.assertEqual(len(self.web.list_cases()), 1)

    def test_audit_review_then_approve(self):
        rec = self.web.audit("IMP-0025")
        self.assertEqual(rec["state"], "PENDING_APPROVAL")
        self.assertEqual(rec["verdict"], "REVIEW")
        done = self.web.decide("IMP-0025", True, "确认无误")
        self.assertEqual(done["state"], "APPROVED")
        self.assertTrue(done["approval"]["approved"])
        self.assertEqual(done["approval"]["approver"], "web")

    def test_return_requires_comment(self):
        self.web.audit("IMP-0025")
        with self.assertRaises(WebApiError):
            self.web.decide("IMP-0025", False, "")

    def test_audit_idempotent(self):
        first = self.web.audit("IMP-0016")
        second = self.web.audit("IMP-0016")
        self.assertTrue(second["idempotency"]["hit"])
        self.assertEqual(first["cost"], second["cost"])
        self.assertEqual(len(self.web.list_cases()), 1)

    def test_unknown_case(self):
        for fn in (self.web.get_case, self.web.get_docs, self.web.get_trace):
            with self.subTest(fn=fn.__name__):
                with self.assertRaises(WebApiError) as ctx:
                    fn("NOPE")
                self.assertEqual(ctx.exception.status, 404)

    def test_docs(self):
        docs = self.web.get_docs("IMP-0016")["docs"]
        self.assertEqual(set(docs), {"contract", "invoice", "packing_list",
                                     "bl", "declaration"})

    def test_trace_events(self):
        self.web.audit("IMP-0016")
        events = self.web.get_trace("IMP-0016")
        self.assertTrue(events)
        self.assertTrue(any(e.get("kind") == "run.start" for e in events))
        self.assertTrue(any(e.get("kind") == "run.end" for e in events))

    def test_metrics_missing(self):
        self.assertFalse(self.web.metrics()["available"])

    def test_metrics_available(self):
        payload = {
            "n": 60, "accuracy": 1.0, "recall": 1.0,
            "false_positive_case_rate": 0.0, "rules_total": 46,
            "citation": {"coverage": 1.0, "total": 41},
            "agent": {"avg_steps": 3.7, "avg_ms": 3.3, "p95_ms": 4.1,
                      "per_case_cost": 0.0002, "total_cost": 0.013},
            "cases": [{"id": "IMP-0001", "expected": "PASS",
                       "got": "PASS", "verdict_ok": True,
                       "recall": 1.0, "issue_count": 0}],
        }
        with open(os.path.join(self.tmp, "result.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        out = self.web.metrics()
        self.assertTrue(out["available"])
        self.assertEqual(out["n"], 60)
        self.assertEqual(out["agent"]["p95_ms"], 4.1)
        self.assertEqual(len(out["cases"]), 1)

    # ---------- 导入任意单证 ----------
    def _sample_docs(self, case_id="IMP-0019"):
        return build_case(_case(case_id))["docs"]

    def test_import_custom_docs(self):
        rec = self.web.import_case("CUSTOM-1", self._sample_docs())
        self.assertEqual(rec["state"], "PENDING_APPROVAL")
        self.assertEqual(rec["verdict"], "FIX")
        self.assertTrue(rec["title"].startswith("导入单证"))
        docs = self.web.get_docs("CUSTOM-1")["docs"]
        self.assertEqual(set(docs), {"contract", "invoice", "packing_list",
                                     "bl", "declaration"})
        self.assertTrue(os.path.exists(os.path.join(self.web.docs_dir,
                                                   "CUSTOM-1.json")))
        self.assertEqual(len(self.web.list_cases()), 1)

    def test_import_auto_id_and_unique(self):
        first = self.web.import_case("", self._sample_docs())
        self.assertTrue(first["case_id"].startswith("CUS-"))
        second = self.web.import_case("CUSTOM-2", self._sample_docs())
        third = self.web.import_case("CUSTOM-2", self._sample_docs())
        self.assertEqual(second["case_id"], "CUSTOM-2")
        self.assertEqual(third["case_id"], "CUSTOM-2-2")

    def test_import_invalid_docs(self):
        for docs in ({}, {"invoice": []}, {"declaration": {}}):
            with self.subTest(docs=docs):
                with self.assertRaises(WebApiError) as ctx:
                    self.web.import_case("BAD", docs)
                self.assertEqual(ctx.exception.status, 400)

    def test_import_missing_required_doc_still_audits(self):
        docs = self._sample_docs()
        docs.pop("bl")
        rec = self.web.import_case("CUSTOM-3", docs)
        self.assertEqual(rec["state"], "PENDING_APPROVAL")
        self.assertEqual(rec["verdict"], "REVIEW")
        self.assertIn("L1-06", {i["rule_id"] for i in rec["issues"]})

    # ---------- 原始文件上传 ----------
    @unittest.skipUnless(HAS_OPENPYXL and XLSX.exists(), "需要 openpyxl 与 Excel 样本")
    def test_ingest_excel_creates_case(self):
        content = XLSX.read_bytes()
        rec = self.web.ingest_files(
            [{"filename": "发票.xlsx", "content": content}], "CUSTOM-ING-1")
        self.assertEqual(rec["case_id"], "CUSTOM-ING-1")
        self.assertIn("invoice", rec["ingest"]["docs"])
        self.assertEqual(rec["ingest"]["missing_docs"],
                         ["contract", "packing_list", "bl", "declaration"])
        self.assertFalse(rec["ingest"]["needs_human"])
        entry = rec["ingest"]["files"][0]
        self.assertEqual(entry["doc_type"], "invoice")
        self.assertEqual(entry["route"], "table")
        self.assertEqual(entry["confidence"], 1.0)
        # 原始文件留档 + 解析记录可回查
        uploads = os.path.join(os.path.dirname(self.web.docs_dir), "uploads",
                               "CUSTOM-ING-1")
        self.assertTrue(os.listdir(uploads))
        self.assertTrue(self.web.get_ingest("CUSTOM-ING-1")["available"])

    @unittest.skipUnless(HAS_OPENPYXL and HAS_PYPDF and XLSX.exists()
                         and all(p.exists() for p in PDF_FILES),
                         "需要 openpyxl/pypdf 与样本")
    def test_ingest_full_case_from_files(self):
        files = [{"filename": "发票.xlsx", "content": XLSX.read_bytes()}]
        files += [{"filename": p.name, "content": p.read_bytes()} for p in PDF_FILES]
        rec = self.web.ingest_files(files)
        self.assertEqual(rec["verdict"], "FIX")
        self.assertEqual(rec["ingest"]["missing_docs"], [])
        self.assertEqual(rec["issue_count"], 1)
        self.assertEqual(set(rec["ingest"]["docs"]),
                         {"contract", "invoice", "packing_list", "bl", "declaration"})

    def test_ingest_rejects_unsupported_and_empty(self):
        with self.assertRaises(WebApiError) as ctx:
            self.web.ingest_files([{"filename": "旧单.xls", "content": b"x"}])
        self.assertIn(".xlsx", str(ctx.exception))
        with self.assertRaises(WebApiError):
            self.web.ingest_files([{"filename": "空.xlsx", "content": b""}])
        with self.assertRaises(WebApiError):
            self.web.ingest_files([{"filename": "a.exe", "content": b"x"}])
        with self.assertRaises(WebApiError):
            self.web.ingest_files([])

    @unittest.skipUnless(HAS_OPENPYXL and XLSX.exists(), "需要 openpyxl 与 Excel 样本")
    def test_ingest_sanitizes_filename(self):
        rec = self.web.ingest_files(
            [{"filename": "../../evil/发票.xlsx", "content": XLSX.read_bytes()}],
            "CUSTOM-ING-2")
        uploads = os.path.join(os.path.dirname(self.web.docs_dir), "uploads",
                               "CUSTOM-ING-2")
        names = os.listdir(uploads)
        self.assertEqual(len(names), 1)
        self.assertTrue(names[0].endswith(".xlsx"))
        self.assertNotIn("..", names[0])
        self.assertEqual(rec["case_id"], "CUSTOM-ING-2")


if __name__ == "__main__":
    unittest.main(verbosity=2)
