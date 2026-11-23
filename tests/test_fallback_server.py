"""兜底 HTTP 服务测试：静态页 + JSON API + multipart 上传（无第三方依赖）。"""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.app.fallback_server import make_server                 # noqa: E402
from tests.test_web_api import make_web                         # noqa: E402
from data.synth.generator import build_case                     # noqa: E402
from data.synth.scenarios import CASES                          # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
XLSX = ROOT / "examples" / "raw" / "合成发票-INV-2026-0901.xlsx"

try:
    import openpyxl  # noqa: F401
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False


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

    @unittest.skipUnless(HAS_OPENPYXL and XLSX.exists(), "需要 openpyxl 与 Excel 样本")
    def test_ingest_multipart(self):
        boundary = "----DSHBoundary7MA4YWxk"
        head = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="case_id"\r\n\r\n'
            "FB-ING-1\r\n"
        ).encode("utf-8")
        file_head = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="files"; filename="发票.xlsx"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode("utf-8")
        body = head + file_head + XLSX.read_bytes() + \
            f"\r\n--{boundary}--\r\n".encode("utf-8")
        req = urllib.request.Request(
            self.base + "/api/ingest", data=body, method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=30) as res:
            self.assertEqual(res.status, 200)
            data = json.loads(res.read().decode("utf-8"))
        self.assertEqual(data["case_id"], "FB-ING-1")
        self.assertEqual(data["ingest"]["docs"], ["invoice"])
        _, meta = self._get("/api/cases/FB-ING-1/ingest")
        self.assertTrue(json.loads(meta)["available"])

    def test_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/api/nope")
        self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
