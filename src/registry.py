"""规则注册表。每条规则是一个纯函数：ctx(dict) -> RuleResult。"""
from __future__ import annotations

from typing import Callable

from .issue import RuleResult

RULES: list[dict] = []


def rule(rid: str, layer: str, title: str, source: str):
    def deco(fn: Callable) -> Callable:
        RULES.append({"id": rid, "layer": layer, "title": title,
                      "source": source, "fn": fn})
        return fn
    return deco


def run_all(ctx: dict) -> list[RuleResult]:
    out: list[RuleResult] = []
    for r in RULES:
        try:
            res = r["fn"](ctx)
        except Exception as exc:  # 规则自身异常不应中断整单审核
            res = RuleResult(r["id"], r["layer"], r["title"], "REVIEW",
                             [], r["source"], error=f"{type(exc).__name__}: {exc}")
        if not isinstance(res, RuleResult):
            res = RuleResult(r["id"], r["layer"], r["title"], "PASS", [], r["source"])
        out.append(res)
    return out
