"""原始文件类型检测测试：Excel / 文字层 PDF / 扫描 PDF / 图片。"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ingest.detect import (  # noqa: E402
    _classify, _detect_pdf_bytes, detect,
)

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "examples" / "raw"
XLSX = RAW / "合成发票-INV-2026-0901.xlsx"
TEXT_PDF = RAW / "合成报关单-DEC-2026-0901.pdf"
SCAN_PDF = RAW / "合成扫描件-多页.pdf"
IMG = RAW / "合成装箱单-PL-2026-0901.png"

FIXTURES_OK = all(p.exists() for p in (XLSX, TEXT_PDF, SCAN_PDF, IMG))


@unittest.skipUnless(FIXTURES_OK, "缺少 examples/raw 合成样本，先跑 scripts/gen_synthetic_rawdocs.py")
class TestDetect(unittest.TestCase):
    def test_excel(self):
        r = detect(XLSX)
        self.assertEqual(r.kind, "excel")
        self.assertEqual(r.route, "table")

    def test_image(self):
        r = detect(IMG)
        self.assertEqual(r.kind, "image")
        self.assertEqual(r.route, "ocr")

    def test_text_pdf(self):
        r = detect(TEXT_PDF)
        self.assertEqual(r.kind, "text_pdf")
        self.assertEqual(r.route, "text")
        self.assertTrue(r.has_text_layer)
        self.assertEqual(r.pages, 1)

    def test_scan_pdf(self):
        r = detect(SCAN_PDF)
        self.assertEqual(r.kind, "scan_pdf")
        self.assertEqual(r.route, "ocr")
        self.assertFalse(r.has_text_layer)
        self.assertEqual(r.pages, 2)

    def test_bytes_fallback_matches(self):
        """没装 pypdf 时，字节特征兜底也必须判对（系统 Python 就是这种情况）。"""
        text = _detect_pdf_bytes(TEXT_PDF)
        scan = _detect_pdf_bytes(SCAN_PDF)
        self.assertEqual(text.kind, "text_pdf")
        self.assertTrue(text.has_text_layer)
        self.assertEqual(scan.kind, "scan_pdf")
        self.assertFalse(scan.has_text_layer)
        self.assertEqual(scan.pages, 2)

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            detect(RAW / "不存在.pdf")

    def test_old_xls_is_unsupported(self):
        with tempfile.NamedTemporaryFile(suffix=".xls", delete=False) as f:
            path = f.name
        try:
            r = detect(path)
            self.assertEqual(r.kind, "unsupported")
            self.assertIn("xlsx", r.note)
        finally:
            os.unlink(path)


class TestClassify(unittest.TestCase):
    def test_all_text(self):
        self.assertEqual(_classify(2, [100, 50]), ("text_pdf", "text", True))

    def test_all_scan(self):
        self.assertEqual(_classify(2, [0, 3]), ("scan_pdf", "ocr", False))

    def test_mixed(self):
        self.assertEqual(_classify(2, [0, 500]), ("mixed_pdf", "ocr", True))

    def test_empty(self):
        self.assertEqual(_classify(0, []), ("empty_pdf", "unsupported", False))


if __name__ == "__main__":
    unittest.main(verbosity=2)
