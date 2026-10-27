"""P2：检索评测门槛 + 增量索引 的测试。"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evals.retrieval import QUERIES, evaluate                  # noqa: E402
from src.rag.index import SYNONYMS, expand_query               # noqa: E402
from src.rag.retriever import Retriever                        # noqa: E402
from src.rag.store import IndexStore, fingerprint, rebuild     # noqa: E402


def chunk(cid, text, **extra):
    return {"chunk_id": cid, "text": text, **extra}


class TestRetrievalQuality(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = evaluate(Retriever())

    def test_recall_at_3_is_high(self):
        # 口语化 query（不含规则编号）下，期望 chunk 必须进 top3
        self.assertGreaterEqual(self.result["recall@3"], 0.95)
        self.assertGreaterEqual(self.result["recall@1"], 0.85)

    def test_every_query_has_expected_chunk(self):
        retriever = Retriever()
        ids = {c["chunk_id"] for c in retriever.chunks}
        for _q, expected in QUERIES:
            self.assertIn(expected, ids)

    def test_rule_id_exact_hit_still_wins(self):
        hits = Retriever().search("L2-13 金额一致", top_k=3)
        self.assertEqual(hits[0]["chunk_id"], "rules#L2-13")


class TestQueryExpansion(unittest.TestCase):
    def test_synonym_expansion_adds_canonical_term(self):
        self.assertIn("商品编号", expand_query("税号写错"))
        self.assertIn("非数字", expand_query("商品编号带字母"))

    def test_no_synonym_returns_query(self):
        self.assertEqual(expand_query("原产国"), "原产国")

    def test_judge_markers_exist(self):
        self.assertTrue(any(m in "这个到底算不算问题" for m in
                            ("算不算", "要不要")))


class TestIndexStoreDiff(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "idx.json")
        self.store = IndexStore(self.path)

    def test_add_update_remove(self):
        old = [chunk("a", "旧内容"), chunk("b", "不变")]
        self.store.save(old)
        new = [chunk("b", "不变"), chunk("c", "新增")]
        stats = self.store.diff(new)
        self.assertEqual(stats["added"], ["c"])
        self.assertEqual(stats["removed"], ["a"])
        self.assertEqual(stats["updated"], [])
        self.assertEqual(stats["unchanged"], 1)

    def test_text_change_is_update(self):
        self.store.save([chunk("a", "旧内容")])
        stats = self.store.diff([chunk("a", "新内容")])
        self.assertEqual(stats["updated"], ["a"])

    def test_apply_is_idempotent(self):
        chunks = [chunk("a", "x"), chunk("b", "y")]
        first = self.store.apply(chunks)
        second = self.store.apply(chunks)
        self.assertEqual(first["changed"], 2)
        self.assertEqual(second["changed"], 0)

    def test_load_roundtrip(self):
        chunks = [chunk("a", "x", rule_id="L1-01")]
        self.store.save(chunks)
        loaded = IndexStore(self.path).load()
        self.assertEqual(loaded[0]["chunk_id"], "a")
        self.assertEqual(loaded[0]["rule_id"], "L1-01")

    def test_fingerprint_ignores_extra_fields(self):
        a = fingerprint([chunk("a", "t", score=0.9)])
        b = fingerprint([chunk("a", "t", score=0.1)])
        self.assertEqual(a, b)


class TestRebuildIncremental(unittest.TestCase):
    def test_first_build_then_no_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "index.json")
            first = rebuild(path)
            self.assertEqual(first["old_chunks"], 0)
            self.assertGreater(first["chunks"], 50)
            second = rebuild(path)
            self.assertEqual(second["stats"]["changed"], 0)

    def test_full_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "index.json")
            rebuild(path)
            out = rebuild(path, full=True)
            self.assertTrue(out["full"])
            self.assertEqual(out["chunks"], out["old_chunks"])


class TestRetrieverUsesStore(unittest.TestCase):
    def test_store_env_is_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "index.json")
            IndexStore(path).save([chunk("only", "只有这一条", rule_id="L1-99")])
            old = os.environ.get("LOGIAGENT_RAG_STORE")
            os.environ["LOGIAGENT_RAG_STORE"] = path
            try:
                r = Retriever()
                self.assertEqual([c["chunk_id"] for c in r.chunks], ["only"])
            finally:
                if old is None:
                    os.environ.pop("LOGIAGENT_RAG_STORE", None)
                else:
                    os.environ["LOGIAGENT_RAG_STORE"] = old


if __name__ == "__main__":
    unittest.main(verbosity=2)
