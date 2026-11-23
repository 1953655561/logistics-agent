"""OCR 端口与扫描件抽取测试。

零依赖用例用 ``MockOcr`` 注入文本；真实 OCR 用例需要 ``pypdf`` + OCR 引擎，
未安装时跳过，不阻塞核心测试。
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ingest.ocr import (  # noqa: E402
    MockOcr, OcrBlock, get_ocr, group_rows,
)
from src.ingest.ocr_pdf import (  # noqa: E402
    _lines_from_blocks, _locators, _table_items, extract_ocr,
)
from src.ingest.pipeline import run  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "examples" / "raw"
SCAN_PDF = RAW / "合成扫描件-多页.pdf"

try:
    import pypdf  # noqa: F401
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False

try:
    from PIL import Image  # noqa: F401
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import rapidocr_onnxruntime  # noqa: F401
    HAS_RAPIDOCR = True
except ImportError:
    HAS_RAPIDOCR = False

PDF_DIR = RAW / "pdf"
PDF_FILES = [
    PDF_DIR / "合同-HT-2026-0901.pdf",
    PDF_DIR / "发票-INV-2026-0901.pdf",
    PDF_DIR / "装箱单-PL-2026-0901.pdf",
    PDF_DIR / "提单-SYN-2026-0901.pdf",
    PDF_DIR / "报关单-DEC-2026-0901.pdf",
]

PACKING_TEXT = """装箱单 PACKING LIST
装箱单号 PL-TEST-1 日期 2026-09-01
件数 40 包装种类 纸箱
毛重 960.4 净重 920.0
体积 12.5 唛头 NINGBO / N/M
木包装 否"""

DECLARATION_TEXT = """中华人民共和国海关进口货物报关单
报关单号 DEC-TEST-1 申报日期 2026-09-25
收发货人 BUYER LTD 运输方式 水路运输
合同号 HT-TEST-1 提单号 BL-TEST-1
总价 9975.00 币制 USD"""


def block(text, x0, y0, x1, y1, confidence=0.95):
    return OcrBlock(text, (x0, y0, x1, y1), confidence, 1)


class TestOcrPort(unittest.TestCase):
    def test_mock_is_default_text_source(self):
        ocr = MockOcr(texts=["第一页", "第二页"], confidence=0.8)
        first = ocr.recognize(None, page=1)
        second = ocr.recognize(None, page=2)
        self.assertEqual(first.text, "第一页")
        self.assertEqual(second.text, "第二页")
        self.assertEqual(first.confidence, 0.8)

    def test_mock_without_text_is_not_trusted(self):
        result = MockOcr().recognize(None, page=1)
        self.assertEqual(result.text, "")
        self.assertEqual(result.confidence, 0.0)

    def test_get_ocr_by_env(self):
        with mock.patch.dict(os.environ, {"LOGIAGENT_OCR": "mock"}):
            self.assertEqual(get_ocr().name, "mock")
        with mock.patch.dict(os.environ, {"LOGIAGENT_OCR": "auto"}):
            self.assertIn(get_ocr().name, {"mock", "rapidocr"})
        with self.assertRaises(ValueError):
            get_ocr("不存在的引擎")


class TestGroupRows(unittest.TestCase):
    def test_reading_order(self):
        blocks = [
            block("值 B", 100, 0, 150, 20),
            block("标签 A", 0, 0, 80, 20),
            block("值 D", 100, 40, 150, 60),
            block("标签 C", 0, 40, 80, 60),
        ]
        rows = group_rows(blocks)
        self.assertEqual([[b.text for b in row] for row in rows],
                         [["标签 A", "值 B"], ["标签 C", "值 D"]])

    def test_lines_join_label_and_value(self):
        blocks = [block("装箱单号", 0, 0, 80, 20), block("PL-1", 100, 0, 160, 20)]
        self.assertEqual(_lines_from_blocks(blocks), "装箱单号 PL-1")


class TestTableBlocks(unittest.TestCase):
    HEADER = [
        block("序号", 0, 0, 40, 20), block("品名", 50, 0, 200, 20),
        block("HS编码", 210, 0, 340, 20), block("数量", 350, 0, 400, 20),
        block("单位", 410, 0, 450, 20), block("单价", 460, 0, 520, 20),
        block("金额", 530, 0, 620, 20),
    ]

    def row(self, y, name="测试商品", qty="10", unit="个",
            price="50", amount="500"):
        return [
            block("1", 0, y, 40, y + 20), block(name, 50, y, 200, y + 20),
            block("9503008900", 210, y, 340, y + 20),
            block(qty, 350, y, 400, y + 20), block(unit, 410, y, 450, y + 20),
            block(price, 460, y, 520, y + 20), block(amount, 530, y, 620, y + 20),
        ]

    def test_items_by_column_coordinates(self):
        blocks = self.HEADER + self.row(20) + [
            block("合计", 0, 40, 80, 60), block("500", 530, 40, 620, 60)]
        items, checks, totals = _table_items(blocks)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["name"], "测试商品")
        self.assertEqual(item["hs_code"], "9503008900")
        self.assertEqual(item["qty"], 10)
        self.assertEqual(item["unit"], "个")
        self.assertEqual(item["unit_price"], 50.0)
        self.assertEqual(item["amount"], 500.0)
        self.assertEqual(item["origin"], "CN")
        self.assertEqual(checks, [])
        self.assertEqual(totals["total_amount"], 500.0)

    def test_amount_mismatch_is_flagged(self):
        blocks = self.HEADER + self.row(20, amount="450")
        items, checks, _ = _table_items(blocks)
        self.assertEqual(len(items), 1)
        self.assertEqual(len(checks), 1)
        self.assertIn("数量×单价", checks[0])


class TestOcrPageResult(unittest.TestCase):
    def _image(self, directory):
        path = Path(directory) / "单页.png"
        Image.new("RGB", (60, 40), "white").save(path)
        return path

    @unittest.skipUnless(HAS_PIL, "需要 Pillow")
    def test_packing_list_from_ocr_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._image(tmp)
            results = extract_ocr(path, engine=MockOcr(PACKING_TEXT, 0.9))
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r["doc_type"], "packing_list")
        self.assertEqual(r["engine"], "mock")
        self.assertFalse(r["needs_human"])
        self.assertEqual(r["fields"]["pl_no"], "PL-TEST-1")
        self.assertEqual(r["fields"]["packages"], 40)
        self.assertEqual(r["fields"]["marks"], {"port": "NINGBO", "text": "N/M"})
        self.assertFalse(r["fields"]["wood_packaging"])
        self.assertAlmostEqual(r["confidence"], 0.9)

    @unittest.skipUnless(HAS_PIL, "需要 Pillow")
    def test_low_ocr_confidence_goes_to_human(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._image(tmp)
            results = extract_ocr(path, engine=MockOcr(PACKING_TEXT, 0.4))
        r = results[0]
        self.assertTrue(r["needs_human"])
        self.assertLess(r["confidence"], 0.6)
        self.assertTrue(any("OCR" in c for c in r["checks"]))

    def test_locators_point_back_to_page(self):
        locators = _locators("packing_list", [block("装箱单号 PL-1", 0, 0, 120, 20)], 2)
        self.assertEqual(locators["pl_no"]["page"], 2)
        self.assertEqual(locators["pl_no"]["bbox"], [0, 0, 120, 20])


class TestPipelineOcr(unittest.TestCase):
    @unittest.skipUnless(HAS_PIL, "需要 Pillow")
    def test_no_engine_degrades_explicitly(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "扫描件.png"
            Image.new("RGB", (60, 40), "white").save(path)
            with mock.patch.dict(os.environ, {"LOGIAGENT_OCR": "mock"}):
                out = run([str(path)])
        self.assertEqual(out["docs"], {})
        self.assertIn("invoice", out["missing_docs"])
        self.assertIn("OCR 引擎", out["details"][0]["status"])

    @unittest.skipUnless(HAS_PYPDF and SCAN_PDF.exists(), "需要 pypdf 与扫描件样本")
    def test_two_page_scan_with_mock_engine(self):
        engine = MockOcr(texts=[PACKING_TEXT, DECLARATION_TEXT], confidence=0.95)
        with mock.patch("src.ingest.ocr_pdf.get_ocr", return_value=engine):
            results = extract_ocr(SCAN_PDF)
        self.assertEqual([r["doc_type"] for r in results],
                         ["packing_list", "declaration"])
        self.assertEqual(results[1]["fields"]["decl_no"], "DEC-TEST-1")
        self.assertEqual(results[1]["fields"]["total_amount"], 9975.0)

    @unittest.skipUnless(HAS_PYPDF and SCAN_PDF.exists(), "需要 pypdf 与扫描件样本")
    def test_pipeline_merges_scan_pages(self):
        engine = MockOcr(texts=[PACKING_TEXT, DECLARATION_TEXT], confidence=0.95)
        with mock.patch("src.ingest.ocr_pdf.get_ocr", return_value=engine):
            out = run([str(SCAN_PDF)])
        self.assertIn("packing_list", out["docs"])
        self.assertIn("declaration", out["docs"])
        self.assertEqual(sorted(out["missing_docs"]),
                         ["bl", "contract", "invoice"])


class TestRealOcrScan(unittest.TestCase):
    """真实 OCR：装好 RapidOCR 时跑合成扫描件，否则 skip。"""

    READY = (HAS_PYPDF and HAS_RAPIDOCR and SCAN_PDF.exists()
             and all(p.exists() for p in PDF_FILES))

    @unittest.skipUnless(READY, "需要 RapidOCR、pypdf 与扫描件/PDF 样本")
    def test_two_page_scan_fields(self):
        results = extract_ocr(SCAN_PDF)
        self.assertEqual([r["doc_type"] for r in results],
                         ["packing_list", "declaration"])
        self.assertTrue(all(r["engine"] == "rapidocr" for r in results))

        packing = results[0]["fields"]
        self.assertEqual(packing["pl_no"], "PL-2026-0901")
        self.assertEqual(packing["packages"], 40)
        self.assertEqual(packing["gross_weight"], 960.4)

        declaration = results[1]["fields"]
        self.assertEqual(declaration["decl_no"], "DEC-2026-0901")
        self.assertEqual(declaration["total_amount"], 9975.0)
        self.assertEqual(declaration["freight"], 850.0)
        self.assertEqual(declaration["cert_no"], "3C-2026-0001")
        item = declaration["items"][0]
        self.assertEqual(item["qty"], 800)
        self.assertEqual(item["elements"]["material"], "塑料")
        self.assertEqual(item["legal_unit2"], "千克")

    @unittest.skipUnless(READY, "需要 RapidOCR、pypdf 与扫描件/PDF 样本")
    def test_scan_plus_pdfs_end_to_end(self):
        # 扫描件给装箱单 + 报关单；再补合同/发票/提单三份文字层 PDF → 五单齐套
        others = [p for p in PDF_FILES
                  if any(key in p.name for key in ("合同", "发票", "提单"))]
        paths = [str(SCAN_PDF)] + [str(p) for p in others]
        out = run(paths)
        self.assertEqual(out["missing_docs"], [])
        self.assertEqual(out["verdict"], "FIX")
        self.assertEqual(out["issue_count"], 1)
        self.assertEqual(out["issues"][0]["rule_id"], "L2-13")


if __name__ == "__main__":
    unittest.main(verbosity=2)
