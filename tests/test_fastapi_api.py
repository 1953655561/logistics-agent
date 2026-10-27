"""FastAPI 适配器测试：路由、DTO、审批、静态托管。"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from fastapi.testclient import TestClient                   # noqa: E402
    from src.adapters.fastapi_api import create_app             # noqa: E402
    HAS_FASTAPI = True
except ImportError:          # 未安装 fastapi/httpx，跳过适配器测试
    TestClient = None        # type: ignore[assignment]
    create_app = None        # type: ignore[assignment]
    HAS_FASTAPI = False

from tests.test_web_api import make_web                         # noqa: E402
from data.synth.generator import build_case                     # noqa: E402
from data.synth.scenarios import CASES                          # noqa: E402


@unittest.skipUnless(HAS_FASTAPI, "需要 fastapi/httpx")
class TestFastApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.web = make_web(self.tmp)
        self.client = TestClient(create_app(self.web))

    def test_health_and_catalog(self):
        body = self.client.get("/api/health").json()
        self.assertEqual(body["status"], "ok")
        self.assertIn("model", body)                     # response_model 不能把新字段滤掉
        self.assertTrue(body["model"]["offline"])
        self.assertEqual(len(self.client.get("/api/scenarios").json()), 60)
        self.assertEqual(len(self.client.get("/api/rules").json()), 46)

    def test_audit_and_detail(self):
        res = self.client.post("/api/cases/IMP-0016/audit", json={})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["state"], "APPROVED")
        self.assertEqual(body["verdict"], "PASS")
        self.assertIn("review", body)

        detail = self.client.get("/api/cases/IMP-0016").json()
        self.assertEqual(detail["title"], "50 项临界")
        self.assertIn("steps", detail)
        self.assertEqual(self.client.get("/api/cases/IMP-0016/docs").status_code, 200)
        self.assertTrue(self.client.get("/api/cases/IMP-0016/trace").json())

    def test_import_endpoint(self):
        docs = build_case(next(c for c in CASES if c["id"] == "IMP-0019"))["docs"]
        res = self.client.post("/api/cases/import", json={
            "case_id": "IMPORT-API-1", "docs": docs})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["case_id"], "IMPORT-API-1")
        self.assertEqual(body["verdict"], "FIX")
        docs_res = self.client.get("/api/cases/IMPORT-API-1/docs")
        self.assertEqual(docs_res.status_code, 200)
        self.assertEqual(docs_res.json()["docs"]["invoice"]["total_amount"],
                         docs["invoice"]["total_amount"])
        bad = self.client.post("/api/cases/import", json={"docs": {}})
        self.assertEqual(bad.status_code, 400)

    def test_approval_flow(self):
        res = self.client.post("/api/cases/IMP-0025/audit", json={})
        self.assertEqual(res.json()["state"], "PENDING_APPROVAL")
        bad = self.client.post("/api/cases/IMP-0025/approve",
                               json={"approved": False, "comment": ""})
        self.assertEqual(bad.status_code, 400)
        ok = self.client.post("/api/cases/IMP-0025/approve",
                              json={"approved": True, "comment": "确认"})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["state"], "APPROVED")

    def test_unknown_case_is_404(self):
        self.assertEqual(self.client.get("/api/cases/NOPE").status_code, 404)
        self.assertEqual(self.client.post("/api/cases/NOPE/audit", json={}).status_code, 404)

    def test_invalid_body_is_422(self):
        res = self.client.post("/api/cases/IMP-0016/approve", json={"comment": "x"})
        self.assertEqual(res.status_code, 422)

    def test_openapi_contains_models(self):
        schema = self.client.get("/openapi.json").json()
        self.assertIn("CaseDetail", schema["components"]["schemas"])
        self.assertIn("ReviewOut", schema["components"]["schemas"])
        self.assertIn("/api/cases/{case_id}/audit", schema["paths"])

    def test_static_mount(self):
        dist = os.path.join(self.tmp, "dist")
        os.makedirs(dist, exist_ok=True)
        with open(os.path.join(dist, "index.html"), "w", encoding="utf-8") as f:
            f.write("<!doctype html><title>审核台</title>")
        client = TestClient(create_app(self.web, static_dir=dist))
        res = client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("审核台", res.text)
        # API 路由在静态托管下仍然可用
        self.assertEqual(client.get("/api/health").json()["status"], "ok")


if __name__ == "__main__":
    unittest.main(verbosity=2)
