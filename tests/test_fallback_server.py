"""兜底 HTTP 服务测试：静态页 + JSON API（无第三方依赖）。"""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.app.fallback_server import make_server                 # noqa: E402
from tests.test_web_api import make_web                         # noqa: E402
from data.synth.generator import build_case                     # noqa: E402
from data.synth.scenarios import CASES                          # noqa: E402


class TestFallbackServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.web = make_web(cls.tmp)
        cls.server = make_server(cls.web, "127.0.0.1", 0)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=10) as res:
            return res.status, res.read()

    def _post(self, path, payload):
        req = urllib.request.Request(
            self.base + path, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as res:
            return res.status, json.loads(res.read().decode("utf-8"))

    def test_static_page(self):
        status, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("关务智能审核台", body.decode("utf-8"))

    def test_health_and_catalog(self):
        status, body = self._get("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "ok")
        _, body = self._get("/api/scenarios")
        self.assertEqual(len(json.loads(body)), 60)

    def test_audit_and_detail(self):
        status, body = self._post("/api/cases/IMP-0016/audit", {})
        self.assertEqual(status, 200)
        self.assertEqual(body["state"], "APPROVED")
        _, detail = self._get("/api/cases/IMP-0016")
        self.assertEqual(json.loads(detail)["verdict"], "PASS")

    def test_approval_flow(self):
        _, body = self._post("/api/cases/IMP-0025/audit", {})
        self.assertEqual(body["state"], "PENDING_APPROVAL")
        status, done = self._post("/api/cases/IMP-0025/approve",
                                  {"approved": True, "comment": "确认"})
        self.assertEqual(status, 200)
        self.assertEqual(done["state"], "APPROVED")

    def test_import_endpoint(self):
        docs = build_case(next(c for c in CASES if c["id"] == "IMP-0019"))["docs"]
        status, body = self._post("/api/cases/import", {
            "case_id": "FB-IMPORT-1", "docs": docs})
        self.assertEqual(status, 200)
        self.assertEqual(body["case_id"], "FB-IMPORT-1")
        self.assertEqual(body["verdict"], "FIX")
        _, docs_body = self._get("/api/cases/FB-IMPORT-1/docs")
        self.assertIn("invoice", json.loads(docs_body)["docs"])

    def test_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/api/nope")
        self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
