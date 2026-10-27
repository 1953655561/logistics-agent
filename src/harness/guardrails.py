"""护栏：输入隔离、注入检测、工具白名单、输出 schema 校验。

原则：**单证内容一律当数据**。任何“忽略规则 / 直接判 PASS / 改编码”的文字
都只作为可疑文本被记录，绝不进入指令通道。
"""
from __future__ import annotations

import json
import re

MAX_STRING_LEN = 2000          # 单个字符串字段上限，超出截断并标记
MAX_DOC_BYTES = 200_000        # 单票单证 JSON 体积上限
VALID_VERDICTS = ("PASS", "FIX", "REVIEW", "REJECT")
VALID_SEVERITIES = ("high", "mid", "low")

# 允许 Agent 调用的工具白名单（与实际注册的工具一一对应）
ALLOWED_TOOLS = frozenset({
    "doc.get", "doc.summary", "rules.audit", "rule.search", "case.draft",
})

# 禁用的“动作”类输出：归类只能给建议，绝不自动改判（D3）
FORBIDDEN_ACTIONS = frozenset({"auto_change_hs", "change_hs", "auto_reclassify"})

# ---------------- 注入 / 伪造检测 ----------------
_INJECTION_PATTERNS = [
    ("zh_ignore_rules", re.compile(r"忽略.{0,8}(规则|指令|要求|以上|上述)")),
    ("zh_skip_steps", re.compile(r"跳过.{0,8}(审核|规则|步骤|校验)")),
    ("zh_force_pass", re.compile(r"(直接|强行|一律).{0,6}(判|输出|返回|给).{0,6}PASS",
                                 re.IGNORECASE)),
    ("en_ignore_rules", re.compile(
        r"(ignore|disregard|forget).{0,30}(rules|instructions|prompt)", re.IGNORECASE)),
    ("en_force_pass", re.compile(
        r"(return|output|mark|judge|verdict).{0,12}\bPASS\b", re.IGNORECASE)),
    ("ja_ignore_rules", re.compile(r"(ルール|指示)を無視")),
    ("ru_ignore_rules", re.compile(r"игнорир", re.IGNORECASE)),
    ("system_prompt", re.compile(r"system\s*prompt|you\s+are\s+now", re.IGNORECASE)),
    ("zh_role_override", re.compile(r"你现在是|扮演|切换到.{0,6}(模式|角色)")),
]

_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f"
                      r"\u200b-\u200f\u202a-\u202e\ufeff]")
_CITE_RE = re.compile(r"rules#([A-Za-z0-9\-]+)")

# 触发“降级 REVIEW”的护栏发现类型
ESCALATING_KINDS = frozenset({
    "injection", "forged_citation", "oversized", "oversized_document",
    "control_char", "empty_docs", "missing_docs", "forbidden_action",
})

_RULE_IDS: set[str] | None = None
_CHUNK_IDS: set[str] | None = None


def _known_rule_ids() -> set[str]:
    global _RULE_IDS
    if _RULE_IDS is None:
        import src.rules  # noqa: F401  触发规则注册
        from ..registry import RULES
        _RULE_IDS = {r["id"] for r in RULES}
    return _RULE_IDS


def _known_chunk_ids() -> set[str]:
    global _CHUNK_IDS
    if _CHUNK_IDS is None:
        from ..rag.retriever import default_retriever
        _CHUNK_IDS = {c["chunk_id"] for c in default_retriever().chunks}
    return _CHUNK_IDS


def detect_injection(text) -> list[str]:
    """返回命中的注入模式名列表。"""
    if not isinstance(text, str) or not text:
        return []
    return [name for name, pat in _INJECTION_PATTERNS if pat.search(text)]


def detect_forged_citations(text) -> list[str]:
    """识别形如 rules#L9-99 的伪造引用（规则编号不存在）。"""
    if not isinstance(text, str) or not text:
        return []
    known = _known_rule_ids()
    return [rid for rid in _CITE_RE.findall(text) if rid not in known]


def contains_forbidden_action(obj) -> list[str]:
    """递归找 auto_change_hs 等禁用动作，返回命中的路径。"""
    hits: list[str] = []

    def walk(node, path: str):
        if isinstance(node, dict):
            for k, v in node.items():
                p = f"{path}.{k}" if path else str(k)
                if str(k).lower() in FORBIDDEN_ACTIONS and v:
                    hits.append(p)
                if isinstance(v, str) and v.strip().lower() in FORBIDDEN_ACTIONS:
                    hits.append(p)
                walk(v, p)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(obj, "")
    return hits


def _add(findings: list[dict], kind: str, path: str, **detail) -> None:
    findings.append({"kind": kind, "path": path, **detail})


def _scan_string(findings: list[dict], path: str, text: str) -> str:
    """检测并清洗单条字符串；返回可安全使用的文本。"""
    for name in detect_injection(text):
        _add(findings, "injection", path, pattern=name)
    for rid in detect_forged_citations(text):
        _add(findings, "forged_citation", path, rule_id=rid)
    if "auto_change_hs" in text.lower():
        _add(findings, "forbidden_action", path, detail="输入中出现 auto_change_hs")

    cleaned = _CTRL_RE.sub("", text)
    if cleaned != text:
        _add(findings, "control_char", path, detail="已移除控制字符/零宽字符")

    if len(cleaned) > MAX_STRING_LEN:
        _add(findings, "oversized", path, length=len(cleaned))
        cleaned = cleaned[:MAX_STRING_LEN]
    return cleaned


def sanitize_docs(docs) -> tuple[dict, list[dict]]:
    """清洗单证：移除控制字符、截断超长字段、标记注入与伪造引用。

    返回 (清洗后的单证, findings)。**不修改入参**。
    """
    findings: list[dict] = []
    if not isinstance(docs, dict) or not docs:
        _add(findings, "empty_docs", "docs", detail="单证为空")
        return {}, findings

    try:
        raw_size = len(json.dumps(docs, ensure_ascii=False, default=str).encode("utf-8"))
        if raw_size > MAX_DOC_BYTES:
            _add(findings, "oversized_document", "docs", bytes=raw_size)
    except (TypeError, ValueError):
        pass

    missing = [d for d in ("contract", "invoice", "packing_list", "bl", "declaration")
               if d not in docs]
    if missing:
        _add(findings, "missing_docs", "docs", missing=missing)

    def clean(node, path: str):
        if isinstance(node, str):
            return _scan_string(findings, path, node)
        if isinstance(node, dict):
            return {k: clean(v, f"{path}.{k}" if path else str(k))
                    for k, v in node.items()}
        if isinstance(node, list):
            return [clean(v, f"{path}[{i}]") for i, v in enumerate(node)]
        return node

    cleaned_docs = clean(docs, "")
    # findings 去重，避免同一字段同一问题重复刷屏
    unique: list[dict] = []
    seen: set[tuple] = set()
    for f in findings:
        key = (f["kind"], f["path"], str(f.get("pattern", f.get("rule_id", ""))))
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return cleaned_docs, unique


def escalate_needed(findings: list[dict]) -> bool:
    return any(f.get("kind") in ESCALATING_KINDS for f in findings)


def tool_allowed(name: str) -> bool:
    return name in ALLOWED_TOOLS


def validate_result(verdict, issues, citations) -> list[dict]:
    """输出 schema 校验 + 引用可回查校验 + 禁用动作检查。"""
    problems: list[dict] = []

    def add(kind: str, detail: str, path: str = ""):
        problems.append({"kind": kind, "path": path, "detail": detail})

    if verdict not in VALID_VERDICTS:
        add("invalid_verdict", f"结论不在枚举内：{verdict!r}", "verdict")

    if not isinstance(issues, list):
        add("invalid_issues", "issues 必须是数组", "issues")
        issues = []
    for i, it in enumerate(issues):
        if not isinstance(it, dict):
            add("invalid_issue", f"第 {i} 条问题不是对象", f"issues[{i}]")
            continue
        if not it.get("rule_id"):
            add("invalid_issue", f"第 {i} 条问题缺 rule_id", f"issues[{i}]")
        if it.get("severity") not in VALID_SEVERITIES:
            add("invalid_severity", f"第 {i} 条问题 severity 非法", f"issues[{i}]")

    if not isinstance(citations, list):
        add("invalid_citations", "citations 必须是数组", "citations")
        citations = []
    known_chunks = _known_chunk_ids()
    for i, c in enumerate(citations):
        if not isinstance(c, dict):
            add("invalid_citation", f"第 {i} 条引用不是对象", f"citations[{i}]")
            continue
        cid = c.get("chunk_id")
        if cid and cid not in known_chunks:
            add("invalid_citation", f"引用不可回查：{cid}", f"citations[{i}].chunk_id")
    for i, it in enumerate(issues):
        if isinstance(it, dict):
            cid = it.get("citation_chunk")
            if cid and cid not in known_chunks:
                add("invalid_citation", f"引用不可回查：{cid}",
                    f"issues[{i}].citation_chunk")

    for p in contains_forbidden_action(issues) + contains_forbidden_action(citations):
        add("forbidden_action", f"输出含禁用动作 auto_change_hs（{p}）", p)

    return problems
