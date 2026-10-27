"""Web 审核台应用服务：框架无关，FastAPI 与兜底 HTTP 服务共用。

这里只做 DTO 组装与用例编排，不出现任何 Web 框架。
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime

from ..harness.guardrails import sanitize_docs
from .audit_case import CaseService

KNOWN_DOCS = ("contract", "invoice", "packing_list", "bl", "declaration")
MAX_DOCS_BYTES = 1_000_000          # 导入 JSON 上限，避免误传大文件
_CASE_ID_RE = re.compile(r"[^A-Za-z0-9_-]+")
_CASE_ID_OK = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def validate_docs(docs) -> list[str]:
    """校验导入单证的结构。

    只拦“结构上没法审”的问题；业务缺陷（金额不一致、要素缺失）交给规则引擎，
    这样用户可以用导入功能测试各种缺陷，而不是被前端挡在门外。
    """
    if not isinstance(docs, dict) or not docs:
        return ["单证为空：至少需要 invoice 或 declaration"]
    try:
        size = len(json.dumps(docs, ensure_ascii=False, default=str).encode("utf-8"))
        if size > MAX_DOCS_BYTES:
            return [f"单证 JSON 超过 {MAX_DOCS_BYTES // 1000}KB 上限"]
    except (TypeError, ValueError):
        return ["单证 JSON 无法序列化"]

    present = [k for k in KNOWN_DOCS if k in docs]
    if not present:
        return ["缺少单证：需要 contract / invoice / packing_list / bl / declaration 至少一项"]

    errors: list[str] = []
    for key in KNOWN_DOCS:
        if key in docs and not isinstance(docs[key], dict):
            errors.append(f"{key} 必须是对象")
    for key in ("invoice", "declaration"):
        if key in docs and isinstance(docs[key], dict):
            items = docs[key].get("items")
            if not isinstance(items, list) or not items:
                errors.append(f"{key}.items 必须是非空数组")
            elif any(not isinstance(x, dict) for x in items):
                errors.append(f"{key}.items 里存在非对象项")
    if not any(k in docs for k in ("invoice", "declaration")):
        errors.append("至少需要 invoice 或 declaration 才能审核")
    return errors


class WebApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


class WebApi:
    def __init__(self, repo, service: CaseService, trace_dir: str,
                 scenarios: list[dict] | None = None,
                 build_docs=None, rules: list[dict] | None = None,
                 report_path: str | None = None, docs_dir: str | None = None,
                 router=None):
        self.repo = repo
        self.service = service
        self.trace_dir = os.path.abspath(trace_dir)
        self.scenarios = list(scenarios or [])
        self.build_docs = build_docs
        self.rules = list(rules or [])
        self.report_path = report_path
        # 模型路由：只用于 health 自曝"当前用什么模型"，不参与业务判断
        self.router = router
        self.docs_dir = os.path.abspath(
            docs_dir or os.path.join(os.path.dirname(self.trace_dir), "docs"))
        self._titles = {s["id"]: s.get("title", s["id"]) for s in self.scenarios}

    # ---------- 只读 ----------
    def health(self) -> dict:
        """健康检查 + **当前实际用的模型**。

        v1.6 之前这里只有 status/scenarios/rules，界面上那句「离线 mock」是写死的，
        配了真 key 也照样显示离线——所以把路由表与档位模型一起暴露出来，
        让人能一眼确认"到底在跑什么"，而不是靠猜。
        """
        model = {"offline": True, "active": "mock", "llm": "", "routes": {}, "tiers": {}}
        llm_name = str(getattr(self.service.llm, "name", "") or "")
        model["llm"] = llm_name
        if self.router is not None:
            rows = self.router.describe()
            model["routes"] = {r["task_type"]: r["tier"] for r in rows}
            model["tiers"] = {tier: self.router.models.get(tier, "")
                              for tier in sorted(set(model["routes"].values()))}
            model["offline"] = all(r["offline"] for r in rows)
            model["active"] = "mock" if model["offline"] else "router"
        else:
            model["offline"] = llm_name in ("", "mock")
            model["active"] = "mock" if model["offline"] else llm_name
        return {"status": "ok", "scenarios": len(self.scenarios),
                "rules": len(self.rules), "model": model}

    def list_scenarios(self) -> list[dict]:
        return [self._scenario(s) for s in self.scenarios]

    def list_rules(self) -> list[dict]:
        return [{"rule_id": r.get("id"), "layer": r.get("layer"),
                 "title": r.get("title"), "source": r.get("source")}
                for r in self.rules]

    def list_cases(self, limit: int = 50) -> list[dict]:
        rows = self.repo.list_cases(limit=limit)
        out = []
        for rec in rows:
            p = rec.get("payload") or {}
            review = p.get("review") or {}
            out.append({
                "case_id": rec["case_id"],
                "title": self._title(rec["case_id"]),
                "state": rec["state"],
                "verdict": p.get("verdict", ""),
                "issue_count": len(p.get("issues", []) or []),
                "cost": p.get("cost", 0.0),
                "review_recommendation": review.get("recommendation", ""),
                "updated_at": rec.get("updated_at", ""),
            })
        return out

    def get_case(self, case_id: str) -> dict:
        return self._detail(self._require(case_id))

    def get_docs(self, case_id: str) -> dict:
        docs = self._load_docs(case_id)
        return {"case_id": case_id, "docs": docs}

    def get_trace(self, case_id: str) -> list[dict]:
        rec = self._require(case_id)
        p = rec.get("payload") or {}
        path = p.get("trace_path") or os.path.join(self.trace_dir, f"{case_id}.jsonl")
        path = os.path.abspath(path)
        if not path.startswith(self.trace_dir + os.sep):
            raise WebApiError("trace 路径越界", status=403)
        if not os.path.exists(path):
            return []
        events = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return events

    def metrics(self) -> dict:
        path = self.report_path or os.path.join(
            os.path.dirname(self.trace_dir), "..", "evals", "report", "result.json")
        path = os.path.abspath(path)
        if not os.path.exists(path):
            return {"available": False,
                    "hint": "先运行 `python evals/runner.py --json` 生成评测结果"}
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        agent = data.get("agent") or {}
        return {
            "available": True,
            "generated_at": datetime.fromtimestamp(
                os.path.getmtime(path)).isoformat(timespec="seconds"),
            "n": data.get("n"),
            "accuracy": data.get("accuracy"),
            "recall": data.get("recall"),
            "false_positive_case_rate": data.get("false_positive_case_rate"),
            "rules_total": data.get("rules_total"),
            "citation": data.get("citation", {}),
            "agent": {
                "avg_steps": agent.get("avg_steps"),
                "avg_ms": agent.get("avg_ms"),
                "p95_ms": agent.get("p95_ms"),
                "per_case_cost": agent.get("per_case_cost"),
                "total_cost": agent.get("total_cost"),
                "degraded": agent.get("degraded"),
            },
            "cases": [{k: c.get(k) for k in
                       ("id", "title", "expected", "got", "verdict_ok",
                        "recall", "issue_count")}
                      for c in data.get("cases", [])],
        }

    # ---------- 写操作 ----------
    def audit(self, case_id: str, docs: dict | None = None) -> dict:
        if docs is None:
            docs = self._load_docs(case_id)
        if not isinstance(docs, dict) or not docs:
            raise WebApiError("单证为空，无法审核")
        try:
            rec = self.service.submit(case_id, docs)
        except ValueError as exc:
            raise WebApiError(str(exc), status=400) from exc
        return self._detail(rec)

    def import_case(self, case_id: str = "", docs: dict | None = None) -> dict:
        """导入一份任意结构化单证并立即审核。

        与 `audit` 的区别：允许自动生成 case_id、把单证落到 `var/docs` 供详情页回显；
        同一个 case_id 已存在时自动加后缀，避免测试数据互相覆盖。
        """
        errors = validate_docs(docs)
        if errors:
            raise WebApiError("；".join(errors))
        clean, _ = sanitize_docs(docs)
        cid = self._unique_case_id(case_id)
        try:
            rec = self.service.submit(cid, docs)
        except ValueError as exc:
            raise WebApiError(str(exc), status=400) from exc
        self._store_docs(cid, clean)
        return self._detail(rec)

    def extract(self, text: str) -> dict:
        """文本 → 结构化单证（抽取 POC）。低置信字段进 needs_human，不假装全抽对。"""
        from .extract import extract_invoice

        try:
            return extract_invoice(text, llm=self.service.llm)
        except ValueError as exc:
            raise WebApiError(str(exc), status=400) from exc

    def ask(self, case_id: str, question: str) -> dict:
        """追问：只读，不写回审核单。答案必须带证据，缺证据回「无法确认」。"""
        from .ask import AskService

        rec = self._require(case_id)
        payload = rec.get("payload") or {}
        try:
            docs = self._load_docs(case_id)
        except WebApiError:
            docs = {}
        try:
            return AskService(llm=self.service.llm).ask(
                case_id, question, docs,
                payload.get("issues") or [],
                payload.get("history_hints") or [])
        except ValueError as exc:
            raise WebApiError(str(exc), status=400) from exc

    def decide(self, case_id: str, approved: bool, comment: str = "",
               approver: str = "web") -> dict:
        try:
            rec = self.service.decide(case_id, approved, comment, approver)
        except ValueError as exc:
            status = 404 if "不存在" in str(exc) else 400
            raise WebApiError(str(exc), status=status) from exc
        return self._detail(rec)

    # ---------- 内部 ----------
    def _require(self, case_id: str) -> dict:
        rec = self.repo.load_case(case_id)
        if not rec:
            raise WebApiError(f"审核单不存在: {case_id}", status=404)
        return rec

    def _title(self, case_id: str) -> str:
        if case_id in self._titles:
            return self._titles[case_id]
        if self._docs_path(case_id) and os.path.exists(self._docs_path(case_id)):
            return f"导入单证 · {case_id}"
        return case_id

    def _docs_path(self, case_id: str) -> str | None:
        if not _CASE_ID_OK.match(case_id or ""):
            return None
        return os.path.join(self.docs_dir, f"{case_id}.json")

    def _store_docs(self, case_id: str, docs: dict) -> None:
        path = self._docs_path(case_id)
        if not path:
            return
        os.makedirs(self.docs_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(docs, f, ensure_ascii=False, indent=2)

    def _unique_case_id(self, requested: str) -> str:
        raw = (requested or "").strip()
        base = _CASE_ID_RE.sub("-", raw).strip("-_")[:40]
        if not base:
            base = f"CUS-{datetime.now():%Y%m%d-%H%M%S}"
        if base in self._titles:
            base = f"{base}-CUSTOM"
        candidate = base
        n = 2
        while self.repo.load_case(candidate) is not None:
            candidate = f"{base}-{n}"
            n += 1
            if n > 999:
                raise WebApiError("case_id 冲突过多，请换一个编号")
        return candidate

    def _load_docs(self, case_id: str) -> dict:
        path = self._docs_path(case_id)
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        if self.build_docs is None:
            raise WebApiError(f"没有内置单证: {case_id}", status=404)
        try:
            docs = self.build_docs(case_id)
        except (KeyError, StopIteration) as exc:
            raise WebApiError(f"未知用例: {case_id}", status=404) from exc
        if not docs:
            raise WebApiError(f"未知用例: {case_id}", status=404)
        return docs

    def _scenario(self, s: dict) -> dict:
        return {"id": s.get("id"), "title": s.get("title", ""),
                "expected": s.get("expected", ""),
                "tags": list(s.get("tags") or [])}

    def _detail(self, rec: dict) -> dict:
        p = rec.get("payload") or {}
        review = p.get("review") or {}
        return {
            "case_id": rec["case_id"],
            "title": self._title(rec["case_id"]),
            "state": rec["state"],
            "verdict": p.get("verdict", ""),
            "summary": p.get("summary", ""),
            "issue_count": len(p.get("issues", []) or []),
            "issues": p.get("issues", []) or [],
            "citations": p.get("citations", []) or [],
            "review": review,
            "history_hints": p.get("history_hints") or [],
            "guard": p.get("guard", []) or [],
            "usage": p.get("usage", {}) or {},
            "cost": p.get("cost", 0.0),
            "degraded": bool(p.get("degraded")),
            "rate_limited": bool(p.get("rate_limited")),
            "steps": p.get("steps", []) or [],
            "approval": p.get("approval"),
            "idempotency": p.get("idempotency"),
            "docs_digest": p.get("docs_digest", {}) or {},
            "has_trace": bool(p.get("trace_path")),
            "created_at": rec.get("created_at", ""),
            "updated_at": rec.get("updated_at", ""),
        }
