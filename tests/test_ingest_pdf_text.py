"""文字层 PDF 抽取 + 端到端管线测试。

需要 ``pypdf``（未安装时跳过，不阻塞核心测试）。
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ingest.pdf_text import detect_doc_type, extract  # noqa: E402
from src.ingest.pipeline import run  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PDF_DIR = ROOT / "examples" / "raw" / "pdf"
FILES = [
    PDF_DIR / "合同-HT-2026-0901.pdf",
    PDF_DIR / "发票-INV-2026-0901.pdf",
    PDF_DIR / "装箱单-PL-2026-0901.pdf",
    PDF_DIR / "提单-SYN-2026-0901.pdf",
    PDF_DIR / "报关单-DEC-2026-0901.pdf",
]
EXPECTED = ["contract", "invoice", "packing_list", "bl", "declaration"]

try:
    import pypdf  # noqa: F401
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False

READY = HAS_PYPDF and all(p.exists() for p in FILES)
SKIP_REASON = "需要 pypdf 与 examples/raw/pdf 五份样本"


@unittest.skipUnless(READY, SKIP_REASON)
class TestPdfText(unittest.TestCase):
    def test_doc_type_and_confidence(self):
        for path, expected in zip(FILES, EXPECTED):
            r = extract(path)
            self.assertEqual(r["doc_type"], expected, path.name)
            self.assertFalse(r["needs_human"], f"{path.name} missing={r['missing']}")
            self.assertEqual(r["confidence"], 1.0)

    def test_invoice_fields(self):
        f = extract(FILES[1])["fields"]
        self.assertEqual(f["invoice_no"], "INV-2026-0901")
        self.assertEqual(f["total_amount"], 10000.0)
        self.assertEqual(f["items"][0]["hs_code"], "9503008900")
        self.assertEqual(f["items"][0]["elements"]["material"], "塑料")

    def test_declaration_fields(self):
        f = extract(FILES[4])["fields"]
        self.assertEqual(f["decl_no"], "DEC-2026-0901")
        self.assertEqual(f["total_amount"], 9975.0)   # 故意与发票差 25
        self.assertEqual(f["cert_no"], "3C-2026-0001")
        self.assertEqual(f["transport_mode"], "水路运输")

    def test_packing_marks_and_bool(self):
        f = extract(FILES[2])["fields"]
        self.assertEqual(f["marks"], {"port": "NINGBO", "text": "N/M"})
        self.assertFalse(f["wood_packaging"])
        self.assertEqual(f["packages"], 40)

    def test_bl_dates(self):
        f = extract(FILES[3])["fields"]
        self.assertEqual(f["bl_no"], "SYN-2026-0901")
        self.assertEqual(f["arrival_date"], "2026-09-20")


@unittest.skipUnless(READY, SKIP_REASON)
class TestPipelineEndToEnd(unittest.TestCase):
    def test_five_pdfs_to_fix(self):
        out = run([str(p) for p in FILES])
        self.assertEqual(out["missing_docs"], [])
        self.assertEqual(out["verdict"], "FIX")
        self.assertEqual(out["issue_count"], 1)
        self.assertEqual(out["issues"][0]["rule_id"], "L2-13")


class TestDocTypeDetect(unittest.TestCase):
    def test_priority_declaration_before_contract(self):
        text = "中华人民共和国海关进口货物报关单\n合同号 HT-1\n提单号 BL-1"
        self.assertEqual(detect_doc_type(text), "declaration")

    def test_invoice(self):
        self.assertEqual(detect_doc_type("商业发票 COMMERCIAL INVOICE"), "invoice")

    def test_unknown(self):
        self.assertIsNone(detect_doc_type("一些无关文本"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
