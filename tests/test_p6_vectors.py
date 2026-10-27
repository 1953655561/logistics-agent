"""P6：向量存储 provider + 异步端点 的测试。"""
import inspect
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.rag.corpus import load_corpus                       # noqa: E402
from src.rag.vectors import (HashEmbedding, SimEmbedding, VectorStore,  # noqa: E402
                             cosine, get_provider)


class TestEmbeddings(unittest.TestCase):
    def test_hash_embedding_is_normalized(self):
        vec = HashEmbedding().embed("发票总额与报关单总价不一致")
        self.assertEqual(len(vec), 64)
        self.assertAlmostEqual(math.sqrt(sum(v * v for v in vec)), 1.0, places=5)

    def test_empty_text_gives_zero_vector(self):
        self.assertEqual(set(HashEmbedding().embed("")), {0.0})

    def test_sim_provider_expands_synonyms(self):
        # 同义词展开会让"带字母"与"含非数字"的向量更接近
        sim = SimEmbedding()
        a = sim.embed("商品编号带字母")
        b = sim.embed("商品编号含非数字")
        c = sim.embed("唛头目的港")
        self.assertGreater(cosine(a, b), cosine(a, c))

    def test_get_provider_falls_back_to_hash(self):
        self.assertEqual(get_provider("nope").name, "hash")
        self.assertEqual(get_provider("sim").name, "sim")


class TestVectorStore(unittest.TestCase):
    def setUp(self):
        self.store = VectorStore(":memory:")
        self.chunks = load_corpus()
        self.store.upsert(self.chunks)

    def tearDown(self):
        self.store.close()

    def test_upsert_and_count(self):
        self.assertEqual(self.store.count(), len(self.chunks))

    def test_search_returns_scored_hits(self):
        hits = self.store.search("L2-13 金额一致", top_k=3)
        self.assertTrue(hits)
        self.assertEqual(len(hits), 3)
        self.assertIn("score", hits[0])
        self.assertEqual(hits[0]["rule_id"], "L2-13")

    def test_upsert_is_idempotent(self):
        self.store.upsert(self.chunks)
        self.assertEqual(self.store.count(), len(self.chunks))

    def test_provider_changes_ranking(self):
        hash_top = self.store.search("商品编号带字母", top_k=3)
        sim_store = VectorStore(":memory:", provider=SimEmbedding())
        sim_store.upsert(self.chunks)
        sim_top = sim_store.search("商品编号带字母", top_k=3)
        sim_store.close()
        self.assertNotEqual([h["chunk_id"] for h in hash_top],
                            [h["chunk_id"] for h in sim_top])


class TestAsyncEndpoints(unittest.TestCase):
    def test_api_endpoints_are_coroutines(self):
        from src.adapters.fastapi_api import create_app
        from tests.test_web_api import make_web
        import tempfile

        app = create_app(make_web(tempfile.mkdtemp()))
        paths = {getattr(r, "path", "") for r in app.routes}
        self.assertIn("/api/cases/{case_id}/ask", paths)
        self.assertIn("/api/extract", paths)
        for route in app.routes:
            endpoint = getattr(route, "endpoint", None)
            if endpoint is not None and getattr(route, "path", "").startswith("/api"):
                self.assertTrue(inspect.iscoroutinefunction(endpoint),
                                f"{route.path} 应改为 async 端点")


if __name__ == "__main__":
    unittest.main(verbosity=2)
