"""真实感合成单证测试：文件存在、结构合法、结论符合期望。"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.application.web_api import validate_docs                 # noqa: E402
from src.engine import audit                                      # noqa: E402
from tests.test_web_api import make_web                           # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLES = os.path.join(ROOT, "examples", "realistic")


class TestRealisticExamples(unittest.TestCase):
    def _index(self):
        with open(os.path.join(EXAMPLES, "index.json"), encoding="utf-8") as f:
            return json.load(f)

    def _docs(self, filename):
        with open(os.path.join(EXAMPLES, filename), encoding="utf-8") as f:
            return json.load(f)

    def test_each_example_valid_and_expected(self):
        rows = self._index()
        self.assertEqual(len(rows), 5)
        for row in rows:
            with self.subTest(file=row["file"]):
                docs = self._docs(row["file"])
                self.assertEqual(validate_docs(docs), [])
                report = audit(docs)
                self.assertEqual(report["verdict"], row["expected"])

    def test_import_realistic_case(self):
        docs = self._docs("REAL-002-amount-mismatch-FIX.json")
        web = make_web(tempfile.mkdtemp())
        rec = web.import_case("REAL-IMPORT-1", docs)
        self.assertEqual(rec["verdict"], "FIX")
        self.assertEqual(rec["case_id"], "REAL-IMPORT-1")
        stored = web.get_docs("REAL-IMPORT-1")["docs"]
        self.assertEqual(set(stored), {"contract", "invoice", "packing_list",
                                       "bl", "declaration"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
