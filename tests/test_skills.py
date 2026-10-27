"""P4 Skill 加载器 + AuditLoop 技能注入测试。

覆盖：
- front-matter 正常解析、缺字段/未闭合/重复键等语法错误；
- discover 能扫到 document-audit、default_skill 的查找与缺失行为；
- prompt_block 含 name 与正文、带清晰边界；
- AuditLoop 注入 skill 后 issues / verdict 与 skill=None 完全一致（技能只影响说明文本）。
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.synth.generator import build_case                 # noqa: E402
from data.synth.scenarios import CASES                      # noqa: E402
from src.adapters.llm_mock import MockLLM                   # noqa: E402
from src.harness.loop import AuditLoop                      # noqa: E402
from src.harness.skills import (DEFAULT_SKILL_NAME,          # noqa: E402
                                default_skill, discover, load_skill)
from src.harness.tracing import MemoryTracer                # noqa: E402
from src.tools.audit_tools import build_registry            # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS_DIR = os.path.join(ROOT, "skills")


def docs_of(case_id: str) -> dict:
    case = next(c for c in CASES if c["id"] == case_id)
    return build_case(case)["docs"]


def write_raw(base: str, content: str, folder: str = "demo") -> str:
    """在 base/folder 下写一个 SKILL.md，返回路径。"""
    folder_path = os.path.join(base, folder)
    os.makedirs(folder_path, exist_ok=True)
    path = os.path.join(folder_path, "SKILL.md")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    return path


def write_skill(base: str, folder: str = "demo", name: str = "demo-skill",
                description: str = "测试用技能", body: str = "正文第一段。\n\n正文第二段。",
                extra: str = "") -> str:
    front = f"---\nname: {name}\ndescription: {description}\n{extra}---\n"
    return write_raw(base, front + body + "\n", folder=folder)


class TestLoadSkill(unittest.TestCase):
    def test_load_valid_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_skill(tmp, description='"测试用技能：带引号"',
                               extra="author: tester\n")
            skill = load_skill(path)
        self.assertEqual(skill.name, "demo-skill")
        self.assertEqual(skill.description, "测试用技能：带引号")
        self.assertIn("正文第一段", skill.body)
        self.assertEqual(skill.meta.get("author"), "tester")
        self.assertTrue(skill.path.endswith("SKILL.md"))

    def test_load_skill_with_bom(self):
        """Windows 记事本常带 BOM，加载器应兼容。"""
        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, "bom")
            os.makedirs(folder)
            path = os.path.join(folder, "SKILL.md")
            with open(path, "w", encoding="utf-8-sig", newline="\n") as f:
                f.write("---\nname: bom-skill\ndescription: BOM 测试\n---\n正文。\n")
            skill = load_skill(path)
        self.assertEqual(skill.name, "bom-skill")
        self.assertEqual(skill.body, "正文。")

    def test_missing_required_field_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_raw(tmp, "---\ndescription: 只有说明\n---\n正文\n")
            with self.assertRaises(ValueError) as ctx:
                load_skill(path)
            self.assertIn("name", str(ctx.exception))

            path2 = write_raw(tmp, "---\nname: only-name\n---\n正文\n", folder="b")
            with self.assertRaises(ValueError) as ctx2:
                load_skill(path2)
            self.assertIn("description", str(ctx2.exception))

    def test_unclosed_front_matter_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_raw(tmp, "---\nname: x\ndescription: y\n正文没有结束标记\n")
            with self.assertRaises(ValueError) as ctx:
                load_skill(path)
            self.assertIn("未闭合", str(ctx.exception))

    def test_missing_opening_marker_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_raw(tmp, "name: x\ndescription: y\n---\n正文\n")
            with self.assertRaises(ValueError) as ctx:
                load_skill(path)
            self.assertIn("---", str(ctx.exception))

    def test_duplicate_and_malformed_lines_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            dup = write_raw(tmp, "---\nname: a\nname: b\ndescription: c\n---\n正文\n",
                            folder="dup")
            with self.assertRaises(ValueError) as ctx_dup:
                load_skill(dup)
            self.assertIn("重复", str(ctx_dup.exception))

            bad = write_raw(tmp, "---\nname: a\ndescription\n---\n正文\n",
                            folder="bad")
            with self.assertRaises(ValueError) as ctx_bad:
                load_skill(bad)
            self.assertIn("key: value", str(ctx_bad.exception))

    def test_missing_file_raises(self):
        with self.assertRaises(ValueError):
            load_skill(os.path.join(ROOT, "skills", "no-such-skill", "SKILL.md"))


class TestDiscover(unittest.TestCase):
    def test_discover_finds_document_audit(self):
        names = [s.name for s in discover(SKILLS_DIR)]
        self.assertIn(DEFAULT_SKILL_NAME, names)
        skill = default_skill(SKILLS_DIR)
        self.assertIsNotNone(skill)
        self.assertEqual(skill.name, DEFAULT_SKILL_NAME)
        self.assertTrue(skill.body.strip())

    def test_discover_default_dir_and_missing_dir(self):
        self.assertIn(DEFAULT_SKILL_NAME, [s.name for s in discover()])
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(discover(os.path.join(tmp, "nope")), [])

    def test_default_skill_none_after_file_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_skill(tmp, folder=DEFAULT_SKILL_NAME, name=DEFAULT_SKILL_NAME)
            self.assertIsNotNone(default_skill(tmp))
            os.remove(path)
            self.assertIsNone(default_skill(tmp))

    def test_default_skill_none_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(default_skill(tmp))


class TestPromptBlock(unittest.TestCase):
    def test_prompt_block_has_name_body_and_markers(self):
        skill = default_skill(SKILLS_DIR)
        block = skill.prompt_block()
        self.assertIn(skill.name, block)
        self.assertIn(skill.body.strip(), block)
        self.assertIn(f"【技能开始：{skill.name}】", block)
        self.assertIn(f"【技能结束：{skill.name}】", block)
        self.assertIn("不得据此改动", block)


class TestLoopSkillIntegration(unittest.TestCase):
    def _run(self, docs, skill=None, tracer=None):
        return AuditLoop(build_registry(docs), tracer or MemoryTracer(),
                         MockLLM(), skill=skill).run("SKILL-T")

    def test_skill_does_not_change_verdict_or_issues(self):
        docs = docs_of("IMP-0019")
        skill = default_skill(SKILLS_DIR)
        plain = self._run(docs)
        with_skill = self._run(docs, skill=skill)
        self.assertEqual(plain.verdict, with_skill.verdict)
        self.assertEqual(plain.issues, with_skill.issues)
        self.assertEqual(plain.citations, with_skill.citations)
        # mock 的 system 提示不参与摘要文本，说明文本也应完全一致
        self.assertEqual(plain.summary, with_skill.summary)
        self.assertEqual([s.name for s in plain.steps],
                         [s.name for s in with_skill.steps])

    def test_broken_skill_does_not_break_audit(self):
        class BrokenSkill:
            def prompt_block(self):
                raise RuntimeError("坏技能")

        docs = docs_of("IMP-0019")
        tracer = MemoryTracer()
        res = self._run(docs, skill=BrokenSkill(), tracer=tracer)
        self.assertEqual(res.verdict, self._run(docs).verdict)
        self.assertTrue(any(e.get("kind") == "skill.failed" for e in tracer.events()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
