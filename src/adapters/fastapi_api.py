"""FastAPI 适配器：只做路由与 DTO，业务全部在 application.web_api。

这个文件是唯一 import fastapi/pydantic 的 Web 适配层；核心逻辑不依赖它。
"""
from __future__ import annotations

import asyncio
import os

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from ..application.web_api import WebApi, WebApiError


# ---------------- DTO ----------------
class IssueOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    rule_id: str = ""
    field_path: str = ""
    severity: str = ""
    message: str = ""
    evidence: dict = Field(default_factory=dict)
    suggestion: str = ""
    layer: str = ""
    citation: str = ""
    citation_text: str = ""
    citation_chunk: str = ""
    citation_excerpt: str = ""


class CitationOut(BaseModel):
    rule_id: str = ""
    chunk_id: str = ""
    section: str = ""
    excerpt: str = ""


class DoubtOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    code: str = ""
    detail: str = ""
    rule_id: str = ""
    field_path: str = ""


class ReviewOut(BaseModel):
    agree: bool = True
    doubts: list[DoubtOut] = Field(default_factory=list)
    observations: list[DoubtOut] = Field(default_factory=list)
    reason: str = ""
    recommendation: str = "agree"
    source: str = "rules"
    degraded: bool = False


class StepOut(BaseModel):
    name: str = ""
    tool: str = ""
    ok: bool = True
    ms: float = 0.0
    error: str = ""


class UsageOut(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    calls: int = 0


class ApprovalOut(BaseModel):
    approved: bool = False
    comment: str = ""
    approver: str = ""
    ts: str = ""


class HealthOut(BaseModel):
    status: str
    scenarios: int = 0
    rules: int = 0
    # 当前实际使用的模型（offline / routes / tiers），由 WebApi.health() 提供
    model: dict = Field(default_factory=dict)


class CaseSummary(BaseModel):
    case_id: str
    title: str = ""
    state: str
    verdict: str = ""
    issue_count: int = 0
    cost: float = 0.0
    review_recommendation: str = ""
    updated_at: str = ""


class CaseDetail(BaseModel):
    case_id: str
    title: str = ""
    state: str
    verdict: str = ""
    summary: str = ""
    issue_count: int = 0
    issues: list[IssueOut] = Field(default_factory=list)
    citations: list[CitationOut] = Field(default_factory=list)
    review: ReviewOut = Field(default_factory=ReviewOut)
    guard: list[dict] = Field(default_factory=list)
    usage: UsageOut = Field(default_factory=UsageOut)
    cost: float = 0.0
    degraded: bool = False
    rate_limited: bool = False
    steps: list[StepOut] = Field(default_factory=list)
    approval: ApprovalOut | None = None
    idempotency: dict | None = None
    docs_digest: dict = Field(default_factory=dict)
    has_trace: bool = False
    created_at: str = ""
    updated_at: str = ""


class ScenarioOut(BaseModel):
    id: str
    title: str = ""
    expected: str = ""
    tags: list[str] = Field(default_factory=list)


class RuleOut(BaseModel):
    rule_id: str
    layer: str
    title: str
    source: str


class AuditRequest(BaseModel):
    docs: dict | None = None


class AskRequest(BaseModel):
    question: str


class ExtractRequest(BaseModel):
    text: str


class ExtractOut(BaseModel):
    docs: dict = Field(default_factory=dict)
    confidence: dict[str, float] = Field(default_factory=dict)
    needs_human: list[str] = Field(default_factory=list)
    missing_docs: list[str] = Field(default_factory=list)
    method: str = "rules"


class AskOut(BaseModel):
    case_id: str
    question: str
    intent: str = ""
    answer: str = ""
    evidence: list[dict] = Field(default_factory=list)
    citations: list[dict] = Field(default_factory=list)
    tools_called: list[str] = Field(default_factory=list)
    confidence: str = "low"
    uncited: bool = False
    guard: list = Field(default_factory=list)


class ImportRequest(BaseModel):
    case_id: str = ""
    docs: dict


class ApprovalRequest(BaseModel):
    approved: bool
    comment: str = ""


class DocsOut(BaseModel):
    case_id: str
    docs: dict


class MetricsOut(BaseModel):
    available: bool
    hint: str = ""
    generated_at: str = ""
    n: int | None = None
    accuracy: float | None = None
    recall: float | None = None
    false_positive_case_rate: float | None = None
    rules_total: int | None = None
    citation: dict = Field(default_factory=dict)
    agent: dict = Field(default_factory=dict)
    cases: list[dict] = Field(default_factory=list)


# ---------------- App ----------------
def create_app(web: WebApi, static_dir: str | None = None) -> FastAPI:
    app = FastAPI(
        title="关务智能审核 Agent API",
        version="1.0.0",
        description="审核单查询、审核执行、人工审批与评测指标。",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173",
                       "http://localhost:8000", "http://127.0.0.1:8000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(WebApiError)
    async def _web_error(_request, exc: WebApiError):
        return JSONResponse(status_code=exc.status, content={"detail": exc.message})

    @app.get("/api/health", response_model=HealthOut)
    async def health():
        return await asyncio.to_thread(web.health)

    @app.get("/api/cases", response_model=list[CaseSummary])
    async def list_cases(limit: int = Query(50, ge=1, le=500)):
        return await asyncio.to_thread(web.list_cases, limit=limit)

    @app.post("/api/cases/import", response_model=CaseDetail)
    async def import_case(body: ImportRequest):
        return await asyncio.to_thread(web.import_case, body.case_id, body.docs)

    @app.get("/api/cases/{case_id}", response_model=CaseDetail)
    async def get_case(case_id: str):
        return await asyncio.to_thread(web.get_case, case_id)

    @app.get("/api/cases/{case_id}/docs", response_model=DocsOut)
    async def get_docs(case_id: str):
        return await asyncio.to_thread(web.get_docs, case_id)

    @app.get("/api/cases/{case_id}/trace", response_model=list[dict])
    async def get_trace(case_id: str):
        return await asyncio.to_thread(web.get_trace, case_id)

    @app.post("/api/cases/{case_id}/audit", response_model=CaseDetail)
    async def audit(case_id: str, body: AuditRequest | None = None):
        docs = body.docs if body else None
        return await asyncio.to_thread(web.audit, case_id, docs)

    @app.post("/api/extract", response_model=ExtractOut)
    async def extract(body: ExtractRequest):
        return await asyncio.to_thread(web.extract, body.text)

    @app.post("/api/cases/{case_id}/ask", response_model=AskOut)
    async def ask(case_id: str, body: AskRequest):
        return await asyncio.to_thread(web.ask, case_id, body.question)

    @app.post("/api/cases/{case_id}/approve", response_model=CaseDetail)
    async def approve(case_id: str, body: ApprovalRequest):
        return await asyncio.to_thread(web.decide, case_id, body.approved,
                                       body.comment, "web")

    @app.get("/api/scenarios", response_model=list[ScenarioOut])
    async def scenarios():
        return await asyncio.to_thread(web.list_scenarios)

    @app.get("/api/rules", response_model=list[RuleOut])
    async def rules():
        return await asyncio.to_thread(web.list_rules)

    @app.get("/api/metrics", response_model=MetricsOut)
    async def metrics():
        return await asyncio.to_thread(web.metrics)

    if static_dir and os.path.isdir(static_dir):
        # 放在所有 /api 路由之后：前端构建产物由同一个进程兜底。
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="web")
    return app
