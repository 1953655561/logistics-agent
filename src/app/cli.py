"""命令行入口：一条命令跑完单个 case 的完整流程。

    python -m src.app.cli audit IMP-0025 --auto
    python -m src.app.cli list
    python -m src.app.cli show IMP-0025
    python -m src.app.cli resume IMP-0025 --auto
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from data.synth.generator import build_case          # noqa: E402
from data.synth.scenarios import CASES               # noqa: E402
from src.adapters.llm_mock import MockLLM            # noqa: E402
from src.adapters.llm_openai import (LLMNotConfigured,  # noqa: E402
                                     OpenAICompatLLM)
from src.adapters.sqlite_repo import SqliteRepo      # noqa: E402
from src.agents.reviewer import ReviewAgent          # noqa: E402
from src.application.audit_case import CaseService   # noqa: E402
from src.harness.approval import AutoApprover, CliApprover  # noqa: E402
from src.harness.cost import CostMeter               # noqa: E402
from src.harness.ratelimit import TokenBucket        # noqa: E402

VAR = os.path.join(ROOT, "var")


def _get_llm(offline: bool):
    if offline:
        return MockLLM()
    llm = OpenAICompatLLM()
    if not llm.api_key:
        print("提示：未配置 LOGIAGENT_LLM_API_KEY，自动使用离线 mock 模型。")
        return MockLLM()
    return llm


def _docs_for(case_id: str, path: str | None) -> dict:
    if path:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    case = next((c for c in CASES if c["id"] == case_id), None)
    if not case:
        raise SystemExit(f"未知用例: {case_id}（可用 --docs 指定单证 JSON）")
    return build_case(case)["docs"]


def _service(args) -> CaseService:
    os.makedirs(VAR, exist_ok=True)
    repo = SqliteRepo(os.path.join(VAR, "audit.db"))
    approver = AutoApprover(approve=not args.deny) if args.auto or args.deny else CliApprover()
    reviewer = None if getattr(args, "no_review", False) else ReviewAgent()
    limiter = None if getattr(args, "no_ratelimit", False) else TokenBucket(60)
    return CaseService(repo, approver, llm=_get_llm(args.offline),
                       trace_dir=os.path.join(VAR, "traces"),
                       pause_for_approval=getattr(args, "pause", False),
                       reviewer=reviewer, cost_meter=CostMeter(),
                       rate_limiter=limiter)


def cmd_audit(args):
    docs = _docs_for(args.case_id, args.docs)
    rec = _service(args).submit(args.case_id, docs)
    _render(rec, args.json)


def cmd_resume(args):
    rec = _service(args).resume(args.case_id)
    _render(rec, args.json)


def cmd_ask(args):
    """对已有审核单追问：python -m src.app.cli ask CASE "为什么报 L2-13？" """
    from src.app.wiring import build_web_api

    web = build_web_api(offline=True)
    try:
        out = web.ask(args.case_id, args.question)
    except Exception as exc:
        raise SystemExit(f"追问失败：{exc}")
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    print(f"\n问：{out['question']}")
    print(f"答：{out['answer']}")
    if out["evidence"]:
        print("证据：")
        for ev in out["evidence"]:
            print(f"  - [{ev['rule_id']}] {ev['field_path']} {ev['evidence']}")
    if out["citations"]:
        ids = "、".join(c["chunk_id"] for c in out["citations"] if c.get("chunk_id"))
        print(f"引用：{ids}")
    print(f"置信：{out['confidence']}{'（无证据支撑）' if out['uncited'] else ''}")


def cmd_list(args):
    repo = SqliteRepo(os.path.join(VAR, "audit.db"))
    rows = repo.list_cases(limit=args.limit)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    print(f"{'CASE':<12}{'STATE':<18}{'VERDICT':<8}UPDATED")
    for r in rows:
        print(f"{r['case_id']:<12}{r['state']:<18}{r['payload'].get('verdict', '-'):<8}{r['updated_at']}")


def cmd_show(args):
    repo = SqliteRepo(os.path.join(VAR, "audit.db"))
    rec = repo.load_case(args.case_id)
    if not rec:
        raise SystemExit(f"审核单不存在: {args.case_id}")
    _render(rec, args.json)


def _render(rec: dict, as_json: bool):
    if as_json:
        print(json.dumps(rec, ensure_ascii=False, indent=2))
        return
    p = rec["payload"]
    print(f"\n审核单 {rec['case_id']}    状态 {rec['state']}")
    print(f"结论 {p.get('verdict', '-')}（问题 {len(p.get('issues', []))} 处）")
    if p.get("degraded"):
        print("⚠ 本次有降级（预算/模型/工具异常）")
    for it in p.get("issues", []):
        cite = it.get("citation_text") or it.get("citation", "")
        print(f"  - [{it.get('rule_id')}] {it.get('message')}  ← {cite}")
    if p.get("summary"):
        print(f"摘要：{p['summary']}")
    rv = p.get("review") or {}
    if rv:
        print(f"复核：{rv.get('recommendation', '-')} — {rv.get('reason', '')}")
        for d in rv.get("doubts", []):
            print(f"  · 疑问 [{d.get('code')}] {d.get('detail', '')}")
        for o in rv.get("observations", []):
            print(f"  · 观察 [{o.get('code')}] {o.get('detail', '')}")
    if p.get("guard"):
        kinds = "、".join(sorted({g.get("kind", "") for g in p["guard"]}))
        print(f"护栏：命中 {len(p['guard'])} 条（{kinds}）")
    if p.get("usage"):
        u = p["usage"]
        print(f"成本：¥{p.get('cost', 0):.6f}"
              f"（in {u.get('input_tokens', 0)} / out {u.get('output_tokens', 0)} token）")
    if (p.get("idempotency") or {}).get("hit"):
        print("幂等：重复提交，返回已有审核单（未重复建单/计费）")
    steps = p.get("steps", [])
    if steps:
        print("步骤：")
        for i, s in enumerate(steps, 1):
            flag = "" if s.get("ok") else "（失败）"
            print(f"  {i}. {s['name']:<16} {s.get('tool', ''):<14} {s.get('ms', 0):>7.2f}ms{flag}")
    if p.get("approval"):
        a = p["approval"]
        print(f"审批：{a['approver']} {'通过' if a['approved'] else '退回'} — {a['comment']}")
    if p.get("trace_path"):
        print(f"trace：{p['trace_path']}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="关务智能审核 Agent")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("audit", help="跑一票单证")
    p.add_argument("case_id")
    p.add_argument("--docs", help="自定义单证 JSON 路径")
    p.add_argument("--auto", action="store_true", help="非交互：审批自动通过")
    p.add_argument("--deny", action="store_true", help="非交互：审批自动退回")
    p.add_argument("--pause", action="store_true", help="挂起在待审批，稍后用 resume 续跑")
    p.add_argument("--offline", action="store_true", help="强制离线 mock 模型")
    p.add_argument("--no-review", action="store_true", help="关闭独立复核 Agent（单链路）")
    p.add_argument("--no-ratelimit", action="store_true", help="关闭令牌桶限流")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_audit)

    p = sub.add_parser("resume", help="续跑待审批的审核单")
    p.add_argument("case_id")
    p.add_argument("--auto", action="store_true")
    p.add_argument("--deny", action="store_true")
    p.add_argument("--offline", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_resume)

    p = sub.add_parser("list", help="列出审核单")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("show", help="查看审核单")
    p.add_argument("case_id")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("ask", help="对已有审核单追问（带证据与引用）")
    p.add_argument("case_id")
    p.add_argument("question")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_ask)

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
