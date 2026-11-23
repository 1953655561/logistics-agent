"""Excel 适配器测试：表头同义词、合并单元格、明细停止、置信度、端到端。

需要 ``openpyxl``（选依赖）；端到端与 pypdf 混跑的那条额外需要 ``pypdf``。
"""
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ingest.excel import extract, extract_workbook  # noqa: E402
from src.ingest.pipeline import run  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "examples" / "raw"
SAMPLE = RAW / "合成发票-INV-2026-0901.xlsx"
FIVE = RAW / "合成五单-2026-0901.xlsx"
PDF_DIR = RAW / "pdf"
PDF_FILES = [
    PDF_DIR / "合同-HT-2026-0901.pdf",
    PDF_DIR / "发票-INV-2026-0901.pdf",
    PDF_DIR / "装箱单-PL-2026-0901.pdf",
    PDF_DIR / "提单-SYN-2026-0901.pdf",
    PDF_DIR / "报关单-DEC-2026-0901.pdf",
]

try:
    from openpyxl import Workbook  # noqa: F401
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

try:
    import pypdf  # noqa: F401
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False

SKIP_XLSX = "需要 openpyxl 与 examples/raw 合成样本"


@unittest.skipUnless(HAS_OPENPYXL, "需要 openpyxl")
class _BookCase(unittest.TestCase):
    """给每个用例一个临时目录，用 openpyxl 造最小工作簿。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmp.cleanup()

    def book(self, name, sheets):
        """sheets: [(sheet 名, 行列表), ...]"""
        path = Path(self._tmp.name) / name
        wb = Workbook()
        wb.remove(wb.active)
        for title, rows in sheets:
            ws = wb.create_sheet(title)
            for row in rows:
                ws.append(row)
        wb.save(path)
        return path


@unittest.skipUnless(HAS_OPENPYXL and SAMPLE.exists(), SKIP_XLSX)
class TestInvoiceSample(unittest.TestCase):
    def test_fields_and_items(self):
        r = extract(SAMPLE)
        self.assertEqual(r["doc_type"], "invoice")
        self.assertEqual(r["missing"], [])
        self.assertEqual(r["confidence"], 1.0)
        self.assertFalse(r["needs_human"])

        f = r["fields"]
        self.assertEqual(f["invoice_no"], "INV-2026-0901")
        self.assertEqual(f["contract_no"], "HT-2026-0901")
        self.assertEqual(f["date"], "2026-09-01")
        self.assertEqual(f["seller"], "GLOBAL TOYS PTE LTD")
        self.assertEqual(f["currency"], "USD")
        self.assertEqual(f["incoterm"], "FOB")
        self.assertEqual(f["discount"], 0.0)
        self.assertEqual(f["commission"], 0.0)
        self.assertEqual(f["royalty"], 0.0)
        self.assertEqual(f["total_amount"], 10000.0)

        self.assertEqual(len(f["items"]), 1)
        item = f["items"][0]
        self.assertEqual(item["name"], "塑料制玩具配件")
        self.assertEqual(item["hs_code"], "9503008900")
        self.assertEqual(item["qty"], 800)
        self.assertEqual(item["unit"], "个")
        self.assertEqual(item["unit_price"], 12.5)
        self.assertEqual(item["amount"], 10000.0)

    def test_merged_cells_expanded(self):
        """标签/值跨列合并时仍能取到右上方的值（样本 A4:B4 → C4:D4）。"""
        sheets = extract_workbook(SAMPLE)
        self.assertEqual(len(sheets), 1)
        self.assertEqual(sheets[0]["sheet"], "商业发票")
        self.assertEqual(sheets[0]["fields"]["buyer"], "宁波合成进出口有限公司")


@unittest.skipUnless(HAS_OPENPYXL, "需要 openpyxl")
class TestLayoutIndependence(_BookCase):
    KV = [
        ["发票号 Invoice No.", "INV-TEST-1", "日期 Date", "2026-09-01"],
        ["币制 Currency", "USD", "成交方式 Incoterm", "FOB"],
        ["卖方 Seller", "SELLER LTD", "买方 Buyer", "BUYER LTD"],
    ]

    def _invoice(self, header, row, total=500):
        return self.book("发票.xlsx", [("商业发票", [
            ["商业发票 COMMERCIAL INVOICE"],
            *self.KV,
            [],
            header,
            row,
            ["发票总额 Total Amount", total],
        ])])

    def test_header_reorder_still_extracts(self):
        """列顺序打乱也按表头同义词取值，不按列号。"""
        header = ["金额 Amount", "数量 Qty", "品名 Description",
                  "单价 Unit Price", "单位 Unit", "HS 编码"]
        row = [500, 10, "测试商品", 50, "个", "9503008900"]
        f = extract(self._invoice(header, row))["fields"]
        self.assertEqual(f["invoice_no"], "INV-TEST-1")
        self.assertEqual(f["total_amount"], 500.0)
        item = f["items"][0]
        self.assertEqual(item["name"], "测试商品")
        self.assertEqual(item["hs_code"], "9503008900")
        self.assertEqual(item["qty"], 10)
        self.assertEqual(item["unit_price"], 50.0)
        self.assertEqual(item["amount"], 500.0)

    def test_items_stop_at_total_row(self):
        path = self.book("发票.xlsx", [("商业发票", [
            ["商业发票 COMMERCIAL INVOICE"],
            *self.KV,
            ["序号", "品名", "HS 编码", "数量", "单位", "单价", "金额"],
            [1, "商品甲", "9503008900", 1, "个", 100, 100],
            [2, "商品乙", "9503008900", 1, "个", 400, 400],
            ["合计 Total", None, None, None, None, None, 500],
            [3, "汇总后的行", "9503008900", 1, "个", 1, 1],
            ["发票总额 Total Amount", 500],
        ])])
        r = extract(path)
        self.assertEqual(r["items"], 2)
        self.assertEqual([i["name"] for i in r["fields"]["items"]],
                         ["商品甲", "商品乙"])

    def test_numeric_and_fullwidth_cleaning(self):
        path = self._invoice(
            ["序号", "品名", "HS 编码", "数量", "单位", "单价", "金额"],
            [1, "全角商品", "9503008900", "８００", "个", "１２.５", "￥10,000.00"],
            total="￥12,500.00")
        r = extract(path)
        self.assertEqual(r["fields"]["total_amount"], 12500.0)
        item = r["fields"]["items"][0]
        self.assertEqual(item["qty"], 800)
        self.assertEqual(item["unit_price"], 12.5)
        self.assertEqual(item["amount"], 10000.0)

    def test_dates_accept_datetime_and_serial(self):
        serial = (date(2026, 9, 20) - date(1899, 12, 30)).days
        path = self.book("提单.xlsx", [("提单", [
            ["提单 BILL OF LADING"],
            ["提单号", "BL-TEST-1", "日期", date(2026, 9, 3)],
            ["到港日", serial, "船名", "SYNTHETIC VESSEL"],
            ["收货人", "BUYER LTD"],
        ])])
        f = extract(path)["fields"]
        self.assertEqual(f["bl_no"], "BL-TEST-1")
        self.assertEqual(f["date"], "2026-09-03")
        self.assertEqual(f["arrival_date"], "2026-09-20")

    def test_multiple_sheets_in_one_workbook(self):
        path = self.book("两单.xlsx", [
            ("商业发票", [
                ["商业发票 COMMERCIAL INVOICE"],
                *self.KV,
                ["序号", "品名", "HS 编码", "数量", "单位", "单价", "金额"],
                [1, "测试商品", "9503008900", 10, "个", 50, 500],
                ["发票总额 Total Amount", 500],
            ]),
            ("装箱单", [
                ["装箱单 PACKING LIST"],
                ["装箱单号", "PL-TEST-1", "日期", "2026-09-01"],
                ["件数", 40, "包装种类", "纸箱"],
                ["毛重", 960.4, "净重", 920.0],
                ["体积", 12.5, "唛头", "NINGBO / N/M"],
                ["木包装", "否"],
            ]),
        ])
        results = extract_workbook(path)
        self.assertEqual([r["doc_type"] for r in results], ["invoice", "packing_list"])
        docs = run([str(path)])["docs"]
        self.assertIn("invoice", docs)
        self.assertIn("packing_list", docs)

    def test_hidden_template_does_not_override_invoice(self):
        """隐藏的空白模板 sheet 也判成发票，但不能覆盖置信度更高的正式 sheet。"""
        path = Path(self._tmp.name) / "含隐藏模板.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.title = "商业发票"
        for row in [
            ["商业发票 COMMERCIAL INVOICE"],
            *self.KV,
            ["序号", "品名", "HS 编码", "数量", "单位", "单价", "金额"],
            [1, "测试商品", "9503008900", 10, "个", 50, 500],
            ["发票总额 Total Amount", 500],
        ]:
            ws.append(row)
        hidden = wb.create_sheet("模板")
        hidden.append(["商业发票 COMMERCIAL INVOICE"])
        hidden.append(["发票号", None, "发票总额", None])
        hidden.sheet_state = "hidden"
        wb.save(path)

        invoice = run([str(path)])["docs"]["invoice"]
        self.assertEqual(invoice["invoice_no"], "INV-TEST-1")
        self.assertEqual(invoice["total_amount"], 500.0)

    def test_packing_list_marks_and_bool(self):
        path = self.book("装箱单.xlsx", [("装箱单", [
            ["装箱单 PACKING LIST"],
            ["装箱单号", "PL-TEST-1", "日期", "2026-09-01"],
            ["件数", 40, "包装种类", "纸箱"],
            ["毛重", 960.4, "净重", 920.0],
            ["体积", 12.5, "唛头", "NINGBO / N/M"],
            ["木包装", "否"],
        ])])
        f = extract(path)["fields"]
        self.assertEqual(f["packages"], 40)
        self.assertEqual(f["marks"], {"port": "NINGBO", "text": "N/M"})
        self.assertFalse(f["wood_packaging"])

    def test_declaration_not_misread_as_contract(self):
        """报关单里也有「合同号/提单号」标签，不能被误判成合同。"""
        path = self.book("报关单.xlsx", [("报关单", [
            ["中华人民共和国海关进口货物报关单"],
            ["报关单号", "DEC-TEST-1", "申报日期", "2026-09-25"],
            ["收发货人", "BUYER LTD", "运输方式", "水路运输"],
            ["合同号", "HT-TEST-1", "提单号", "BL-TEST-1"],
            ["总价", 9975.0, "币制", "USD"],
            ["序号", "品名", "HS 编码", "数量", "单位", "单价", "总价"],
            [1, "测试商品", "9503008900", 10, "个", 50, 500],
        ])])
        r = extract(path)
        self.assertEqual(r["doc_type"], "declaration")
        self.assertEqual(r["fields"]["decl_no"], "DEC-TEST-1")
        self.assertEqual(r["fields"]["contract_no"], "HT-TEST-1")
        self.assertEqual(r["fields"]["total_amount"], 9975.0)


@unittest.skipUnless(HAS_OPENPYXL, "需要 openpyxl")
class TestConfidence(_BookCase):
    def _invoice(self, total=25, invoice_no="INV-TEST-1"):
        rows = [["商业发票 COMMERCIAL INVOICE"]]
        if invoice_no:
            rows.append(["发票号", invoice_no, "日期", "2026-09-01"])
        rows += [
            ["卖方", "SELLER LTD", "买方", "BUYER LTD"],
            ["序号", "品名", "HS 编码", "数量", "单位", "单价", "金额"],
            [1, "测试商品", "9503008900", 10, "个", 2, 25],
        ]
        if total is not None:
            rows.append(["发票总额", total])
        return self.book("发票.xlsx", [("商业发票", rows)])

    def test_qty_price_mismatch_lowers_confidence(self):
        r = extract(self._invoice(total=25))
        self.assertTrue(r["needs_human"])
        self.assertLess(r["confidence"], 1.0)
        self.assertTrue(any("数量×单价" in c for c in r["checks"]))

    def test_missing_required_lowers_confidence(self):
        r = extract(self._invoice(total=None))
        self.assertIn("total_amount", r["missing"])
        self.assertTrue(r["needs_human"])
        self.assertLess(r["confidence"], 1.0)

    def test_unreadable_formula_lowers_confidence(self):
        rows = [
            ["商业发票 COMMERCIAL INVOICE"],
            ["发票号", "INV-TEST-1", "日期", "2026-09-01"],
            ["卖方", "SELLER LTD", "买方", "BUYER LTD"],
            ["序号", "品名", "HS 编码", "数量", "单位", "单价", "金额"],
            [1, "测试商品", "9503008900", 10, "个", 50, 500],
            ["发票总额", "=500*2"],
        ]
        path = self.book("发票.xlsx", [("商业发票", rows)])
        r = extract(path)
        self.assertIn("total_amount", r["missing"])
        self.assertTrue(any("公式" in c for c in r["checks"]))
        self.assertLess(r["confidence"], 1.0)

    def test_unknown_sheet_is_not_a_document(self):
        path = self.book("无关.xlsx", [("Sheet1", [["随便写点东西"], ["A", "B"]])])
        results = extract_workbook(path)
        self.assertEqual(results[0]["doc_type"], None)
        self.assertTrue(results[0]["needs_human"])


@unittest.skipUnless(HAS_OPENPYXL and SAMPLE.exists(), SKIP_XLSX)
class TestPipelineWithExcel(unittest.TestCase):
    @unittest.skipUnless(HAS_PYPDF and all(p.exists() for p in PDF_FILES),
                         "需要 pypdf 与 examples/raw/pdf 五份 PDF")
    def test_xlsx_invoice_with_four_pdfs(self):
        others = [p for p in PDF_FILES if "发票" not in p.name]
        out = run([str(SAMPLE)] + [str(p) for p in others])
        self.assertEqual(out["missing_docs"], [])
        self.assertEqual(out["verdict"], "FIX")
        self.assertEqual(out["issue_count"], 1)
        self.assertEqual(out["issues"][0]["rule_id"], "L2-13")

    @unittest.skipUnless(FIVE.exists(), "缺少 examples/raw/合成五单-2026-0901.xlsx")
    def test_five_sheet_workbook_end_to_end(self):
        out = run([str(FIVE)])
        self.assertEqual(out["missing_docs"], [])
        self.assertEqual(out["docs"].keys(), {"contract", "invoice", "packing_list",
                                              "bl", "declaration"})
        self.assertEqual(out["verdict"], "FIX")
        self.assertEqual(out["issue_count"], 1)
        self.assertEqual(out["issues"][0]["rule_id"], "L2-13")

    def test_xlsx_alone_reports_missing_docs(self):
        out = run([str(SAMPLE)])
        self.assertIn("invoice", out["docs"])
        self.assertEqual(sorted(out["missing_docs"]),
                         ["bl", "contract", "declaration", "packing_list"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
