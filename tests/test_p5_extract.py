"""P5：文本抽取 POC 的测试。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.application.extract import extract_invoice           # noqa: E402

SAMPLE = """供应商：GLOBAL TOYS PTE LTD
买方：宁波合成进出口有限公司
发票号：INV-2026-0901
发票日期：2026-09-01
合同号：HT-2026-0901
币制：USD
商品：塑料制玩具配件 800 个 单价 12.5 金额 10000.00
总价：10000.00"""


class TestExtract(unittest.TestCase):
    def test_happy_path(self):
        out = extract_invoice(SAMPLE)
        inv = out["docs"]["invoice"]
        self.assertEqual(inv["invoice_no"], "INV-2026-0901")
        self.assertEqual(inv["contract_no"], "HT-2026-0901")
        self.assertEqual(inv["currency"], "USD")
        self.assertEqual(inv["total_amount"], 10000.0)
        self.assertEqual(inv["items"][0]["name"], "塑料制玩具配件")
        self.assertEqual(inv["items"][0]["qty"], 800.0)
        self.assertEqual(out["confidence"]["invoice.items[0].amount"], 1.0)
        self.assertEqual(out["method"], "rules")

    def test_missing_docs_are_reported(self):
        out = extract_invoice(SAMPLE)
        self.assertIn("declaration", out["missing_docs"])
        self.assertTrue(any(n.startswith("docs.") for n in out["needs_human"]))

    def test_item_math_mismatch_lowers_confidence(self):
        text = "商品：塑料制玩具配件 800 个 单价 12.5 金额 9000.00"
        out = extract_invoice(text)
        self.assertEqual(out["confidence"]["invoice.items[0].amount"], 0.5)

    def test_missing_field_gets_zero_confidence(self):
        out = extract_invoice("发票号：INV-2026-0001")
        self.assertEqual(out["confidence"]["invoice.currency"], 0.0)
        self.assertIn("invoice.currency", out["needs_human"])

    def test_empty_text_raises(self):
        with self.assertRaises(ValueError):
            extract_invoice("   ")

    def test_too_long_text_raises(self):
        with self.assertRaises(ValueError):
            extract_invoice("x" * 20001)

    def test_currency_is_uppercased(self):
        out = extract_invoice("币制：usd 总价：100")
        self.assertEqual(out["docs"]["invoice"]["currency"], "USD")


class TestExtractApi(unittest.TestCase):
    def _web(self, tmp):
        from tests.test_web_api import make_web
        return make_web(tmp)

    def test_extract_endpoint(self):
        import tempfile
        web = self._web(tempfile.mkdtemp())
        out = web.extract(SAMPLE)
        self.assertEqual(out["docs"]["invoice"]["invoice_no"], "INV-2026-0901")

    def test_extract_empty_is_400(self):
        import tempfile
        from src.application.web_api import WebApiError
        web = self._web(tempfile.mkdtemp())
        with self.assertRaises(WebApiError) as ctx:
            web.extract("")
        self.assertEqual(ctx.exception.status, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
