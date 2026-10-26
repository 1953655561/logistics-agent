"""Agent 主循环：Plan → Tool → Observe → Reflect，带步数预算与降级。"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict

STEP_BUDGET = 8


@dataclass
class Step:
    name: str
    tool: str = ""
    ok: bool = True
    ms: float = 0.0
    detail: dict = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ms"] = round(self.ms, 2)
        return d


@dataclass
class LoopResult:
    verdict: str = "REVIEW"
    issues: list = field(default_factory=list)
    summary: str = ""
    citations: list = field(default_factory=list)
    steps: list = field(default_factory=list)
    degraded: bool = False


class AuditLoop:
    def __init__(self, tools, tracer, llm=None, max_steps: int = STEP_BUDGET):
        self.tools = tools
        self.tracer = tracer
        self.llm = llm
        self.max_steps = max_steps

    # ---- 内部：执行一步并落 trace ----
    def _run(self, result: LoopResult, name: str, fn, tool: str = "") -> object:
        if len(result.steps) >= self.max_steps:
            raise _BudgetExceeded()
        t0 = time.perf_counter()
        try:
            value = fn()
            step = Step(name, tool, True, (time.perf_counter() - t0) * 1000,
                        {"result": _trim(value)})
        except _BudgetExceeded:
            raise
        except Exception as exc:
            step = Step(name, tool, False, (time.perf_counter() - t0) * 1000,
                        {}, f"{type(exc).__name__}: {exc}")
            value = None
        result.steps.append(step)
        self.tracer.emit({"kind": "step", **step.to_dict()})
        return value

    def run(self, case_id: str) -> LoopResult:
        r = LoopResult()
        self.tracer.emit({"kind": "run.start", "case_id": case_id})
        try:
            # 1) 看单证齐套
            summary = self._run(r, "检查单证齐套", lambda: self._call("doc.summary"), "doc.summary")
            missing = (summary or {}).get("missing", []) if isinstance(summary, dict) else []
            if missing:
                r.verdict = "REVIEW"
                r.issues = [{"rule_id": "L1-06", "severity": "high",
                             "message": "随附单证缺失：" + "、".join(missing),
                             "field_path": "docs", "citation": "内审 SOP"}]
                r.summary = "单证不齐，转人工补齐后再审。"
                r.degraded = True
                return r

            # 2) 跑规则
            audit = self._run(r, "执行规则审核", lambda: self._call("rules.audit"), "rules.audit")
            if not isinstance(audit, dict):
                r.verdict = "REVIEW"
                r.summary = "规则引擎不可用，转人工。"
                r.degraded = True
                return r
            r.verdict = audit.get("verdict", "REVIEW")
            r.issues = audit.get("issues", [])

            # 3) 给高危问题补引用（最多 4 条，兼顾预算）
            highs = [i for i in r.issues if i.get("severity") == "high"][:4]
            for it in highs:
                rid = it.get("rule_id", "")
                hit = self._run(r, f"检索条款 {rid}",
                                lambda rid=rid: self._call("rule.search", query=rid),
                                "rule.search")
                if isinstance(hit, dict) and hit.get("hits"):
                    first = hit["hits"][0]
                    it["citation_text"] = f"依据：{first.get('section', '')}"
                    it["citation_chunk"] = first.get("chunk_id", "")
                    it["citation_excerpt"] = (first.get("text") or "")[:120]
                    r.citations.append({"rule_id": rid,
                                        "chunk_id": first.get("chunk_id", ""),
                                        "section": first.get("section", ""),
                                        "excerpt": it["citation_excerpt"]})

            # 4) 生成说明（LLM，失败可降级）
            r.summary = self._summarize(r)

            # 5) 生成草稿
            self._run(r, "生成审核单草稿",
                      lambda: self._call("case.draft", verdict=r.verdict, summary=r.summary),
                      "case.draft")
        except _BudgetExceeded:
            r.degraded = True
            if not r.issues:
                r.verdict = "REVIEW"
        finally:
            self.tracer.emit({"kind": "run.end", "case_id": case_id,
                              "verdict": r.verdict, "steps": len(r.steps),
                              "degraded": r.degraded})
        return r

    # ---- 工具调用：失败不抛，转成 None 让循环继续 ----
    def _call(self, name: str, **kwargs):
        res = self.tools.call(name, **kwargs)
        if not res.ok:
            raise RuntimeError(f"{name} 失败: {res.error}")
        return res.value

    def _summarize(self, r: LoopResult) -> str:
        base = f"结论 {r.verdict}，发现 {len(r.issues)} 处问题。"
        if not r.issues:
            base = "四单一致，申报要素齐全，可直接申报。"
        if self.llm is None:
            return base
        try:
            out = self.llm.complete([
                {"role": "system", "content": "你是报关审核助手，用一句话总结审核结论。"},
                {"role": "user", "content": base + " 问题：" +
                 "; ".join(f"[{i['rule_id']}]{i['message']}" for i in r.issues[:5])},
            ], max_tokens=120)
            text = out.get("text", "") if isinstance(out, dict) else ""
            return text or base
        except Exception as exc:
            r.degraded = True
            self.tracer.emit({"kind": "llm.fallback", "error": f"{type(exc).__name__}: {exc}"})
            return base


class _BudgetExceeded(Exception):
    pass


def _trim(value, limit: int = 600):
    """trace 里不塞大对象。"""
    try:
        text = str(value)
    except Exception:
        return "<unserializable>"
    return value if len(text) <= limit else text[:limit] + "...(truncated)"
