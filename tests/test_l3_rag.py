"""L3 规则与 RAG 检索测试。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.synth.generator import build_case, make_docs, m_drop_material, m_set_tshirt  # noqa: E402
from data.synth.scenarios import CASES                       # noqa: E402
from src.engine import audit                                 # noqa: E402
from src.harness.tracing import MemoryTracer                 # noqa: E402
from src.rag.retriever import Retriever                      # noqa: E402
from src.tools.audit_tools import build_registry             # noqa: E402
from src.harness.loop import AuditLoop                       # noqa: E402


def verdicts(docs):
    return {r.rule_id: r.conclusion for r in audit(docs)["rules"]}


def docs_of(case_id):
    return build_case(next(c for c in CASES if c["id"] == case_id))["docs"]


class TestElements(unittest.TestCase):
    def test_defaults_filled(self):
        docs = make_docs()
        el = docs["declaration"]["items"][0]["elements"]
        self.assertEqual(el["brand_type"], "无品牌")
        self.assertEqual(el["material"], "塑料")
        self.assertIn("use", el)

    def test_unknown_hs_falls_back_to_generic(self):
        docs = make_docs()
        docs["declaration"]["items"][0]["hs_code"] = "9999999999"
        v = verdicts(docs)
        self.assertEqual(v["L3-23"], "PASS")


class TestL3Rules(unittest.TestCase):
    def test_material_missing(self):
        docs = make_docs()
        m_drop_material(docs)
        self.assertEqual(verdicts(docs)["L3-27"], "FIX")

    def test_material_single_char_is_valid(self):
        docs = make_docs()
        m_set_tshirt(docs)          # 棉：单字材质不应判无效
        self.assertEqual(verdicts(docs)["L3-27"], "PASS")

    def test_brand_type_missing(self):
        docs = docs_of("IMP-0037")
        self.assertEqual(verdicts(docs)["L3-24"], "FIX")

    def test_enum_value_invalid(self):
        docs = make_docs()
        docs["declaration"]["items"][0]["elements"]["brand_type"] = "随便写的"
        self.assertEqual(verdicts(docs)["L3-24"], "FIX")

    def test_composition_sum(self):
        docs = docs_of("IMP-0038")
        self.assertEqual(verdicts(docs)["L3-32"], "FIX")

    def test_chapter_conflict(self):
        docs = docs_of("IMP-0043")
        self.assertEqual(verdicts(docs)["L3-25"], "REVIEW")

    def test_name_matches_chapter(self):
        docs = make_docs()          # 塑料制玩具配件 → 95 章
        self.assertEqual(verdicts(docs)["L3-25"], "PASS")

    def test_contradiction(self):
        docs = docs_of("IMP-0044")
        self.assertEqual(verdicts(docs)["L3-26"], "REVIEW")

    def test_suggestion_never_changes_verdict(self):
        docs = make_docs()
        self.assertEqual(verdicts(docs)["L3-29"], "PASS")

    def test_process_missing(self):
        docs = docs_of("IMP-0040")
        self.assertEqual(verdicts(docs)["L3-31"], "FIX")


class TestRag(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = Retriever()

    def test_corpus_loaded(self):
        self.assertGreaterEqual(len(self.r.chunks), 40)

    def test_rule_id_exact_hit(self):
        hits = self.r.search("L2-19", top_k=3)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["rule_id"], "L2-19")

    def test_keyword_search(self):
        hits = self.r.search("金额 不一致", top_k=5)
        self.assertTrue(any(h.get("rule_id") == "L2-13" for h in hits))

    def test_element_chunk(self):
        hits = self.r.search("9503008900", top_k=3)
        self.assertTrue(any(h["chunk_id"] == "elements#9503008900" for h in hits))

    def test_cite_roundtrip(self):
        hits = self.r.search("L4-41", top_k=1)
        self.assertTrue(hits)
        c = self.r.cite(hits[0]["chunk_id"])
        self.assertIsNotNone(c)
        self.assertIn("完税价格", c["text"])

    def test_tool_returns_chunk_id(self):
        reg = build_registry(make_docs())
        res = reg.call("rule.search", query="L2-11")
        self.assertTrue(res.ok)
        self.assertTrue(res.value["hits"][0]["chunk_id"].startswith("rules#"))


class TestCitationChain(unittest.TestCase):
    def test_every_high_issue_has_citation(self):
        for cid in ("IMP-0019", "IMP-0025", "IMP-0043", "IMP-0059"):
            docs = docs_of(cid)
            res = AuditLoop(build_registry(docs), MemoryTracer()).run(cid)
            for it in res.issues:
                if it.get("severity") != "high":
                    continue
                self.assertTrue(it.get("citation_chunk"), f"{cid} {it['rule_id']} 缺引用")
                self.assertTrue(it.get("citation_excerpt"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
