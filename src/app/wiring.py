"""依赖组装（不 import Web 框架）：CLI / FastAPI / 兜底服务共用。

把组装放在这里，`make demo` 才不会因为 `fallback_server` 间接 import FastAPI
而丢掉“无第三方依赖”的兜底能力。
"""
from __future__ import annotations

import os

from data.synth.generator import build_case                  # noqa: E402
from data.synth.scenarios import CASES                       # noqa: E402
from src.adapters.llm_mock import MockLLM                    # noqa: E402
from src.adapters.llm_openai import OpenAICompatLLM          # noqa: E402
from src.adapters.sqlite_repo import SqliteRepo              # noqa: E402
from src.agents.reviewer import ReviewAgent                  # noqa: E402
from src.application.audit_case import CaseService           # noqa: E402
from src.application.web_api import WebApi                   # noqa: E402
from src.engine import RULES                                 # noqa: E402
from src.harness.approval import AutoApprover                # noqa: E402
from src.harness.cost import CostMeter                       # noqa: E402
from src.harness.memory import MemoryStore                   # noqa: E402
from src.harness.planner import build_planner                # noqa: E402
from src.harness.ratelimit import TokenBucket                # noqa: E402
from src.harness.router import default_router                # noqa: E402
from src.harness.skills import load_default_skill            # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VAR = os.path.join(ROOT, "var")
SCENARIO_KEYS = ("id", "title", "expected", "tags")


def _llm(offline: bool):
    if offline:
        return MockLLM()
    llm = OpenAICompatLLM()
    return llm if llm.api_key else MockLLM()


def _build_docs(case_id: str) -> dict:
    case = next((c for c in CASES if c["id"] == case_id), None)
    if case is None:
        raise KeyError(case_id)
    return build_case(case)["docs"]


def build_web_api(offline: bool = True, review: bool = True,
                  ratelimit: bool = True, memory: bool = True,
                  mode: str = "scripted", skill: bool = True) -> WebApi:
    os.makedirs(VAR, exist_ok=True)
    repo = SqliteRepo(os.path.join(VAR, "audit.db"))
    router = default_router(offline=offline)
    store = MemoryStore(os.path.join(VAR, "memory.db")) if memory else None
    service = CaseService(
        repo, AutoApprover(), llm=router.llm("summarize"),
        trace_dir=os.path.join(VAR, "traces"),
        pause_for_approval=True,
        reviewer=ReviewAgent(llm=router.llm("review")) if review else None,
        cost_meter=CostMeter(),
        rate_limiter=TokenBucket(60) if ratelimit else None,
        memory=store, mode=mode,
        planner=build_planner(mode, router.llm("ask")),
        skill=load_default_skill() if skill else None,
    )
    return WebApi(
        repo, service, trace_dir=os.path.join(VAR, "traces"),
        scenarios=[{k: c.get(k) for k in SCENARIO_KEYS} for c in CASES],
        build_docs=_build_docs,
        rules=RULES,
        report_path=os.path.join(ROOT, "evals", "report", "result.json"),
        router=router,
    )
