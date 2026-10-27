"""MCP 服务：stdio + JSON-RPC 2.0。

支持 `initialize` / `tools/list` / `tools/call`，5 个工具直接复用现有 schema：
doc.get / doc.summary / rules.audit / rule.search / case.draft。

用法：
    python -m src.mcp.server --case IMP-0001
    python -m src.mcp.server --docs path/to/docs.json
    echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python -m src.mcp.server --case IMP-0001
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.harness.guardrails import sanitize_docs, tool_allowed  # noqa: E402
from src.tools.audit_tools import build_registry                # noqa: E402

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "logistics-agent"
SERVER_VERSION = "1.0.0"


class McpServer:
    def __init__(self, docs: dict):
        self.docs, self.guard = sanitize_docs(docs)
        self.registry = build_registry(self.docs)

    # ---------- JSON-RPC ----------
    def handle(self, request: dict) -> dict | None:
        if not isinstance(request, dict):
            return _error(None, -32600, "Invalid Request")
        method = request.get("method")
        rid = request.get("id")
        if request.get("jsonrpc") != "2.0" or not isinstance(method, str):
            return _error(rid, -32600, "Invalid Request")

        # JSON-RPC 通知（无 id）不需要响应
        if rid is None:
            return None

        try:
            if method == "initialize":
                return _ok(rid, {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                })
            if method == "ping":
                return _ok(rid, {})
            if method == "tools/list":
                return _ok(rid, {"tools": self._tool_specs()})
            if method == "tools/call":
                return self._tools_call(rid, request.get("params") or {})
            return _error(rid, -32601, f"Method not found: {method}")
        except Exception as exc:  # 兜底：任何异常都不能把服务打挂
            return _error(rid, -32603, f"{type(exc).__name__}: {exc}")

    def _tool_specs(self) -> list[dict]:
        return [{"name": t["name"], "description": t["description"],
                 "inputSchema": t["schema"]} for t in self.registry.specs()]

    def _tools_call(self, rid, params: dict) -> dict:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return _error(rid, -32602, "tools/call 参数非法")
        if not tool_allowed(name):
            return _error(rid, -32602, f"工具不在白名单：{name}")
        res = self.registry.call(name, **arguments)
        payload = res.to_dict()
        return _ok(rid, {
            "content": [{"type": "text",
                         "text": json.dumps(payload, ensure_ascii=False)}],
            "isError": not res.ok,
        })

    # ---------- stdio ----------
    def serve(self, stdin=None, stdout=None, once: bool = False) -> int:
        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                response = _error(None, -32700, "Parse error")
            else:
                response = self.handle(request)
            if response is not None:
                stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                stdout.flush()
            if once:
                break
        return 0


def _ok(rid, result) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _error(rid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def _load_docs(case_id: str, docs_path: str | None) -> dict:
    if docs_path:
        with open(docs_path, encoding="utf-8") as f:
            return json.load(f)
    from data.synth.generator import build_case
    from data.synth.scenarios import CASES
    case = next((c for c in CASES if c["id"] == case_id), None)
    if case is None:
        raise SystemExit(f"未知用例: {case_id}；可用 --docs 指定单证 JSON")
    return build_case(case)["docs"]


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="关务审核 MCP 服务（stdio JSON-RPC）")
    ap.add_argument("--case", default="IMP-0001", help="用内置评测用例的合成单证")
    ap.add_argument("--docs", help="自定义单证 JSON 路径")
    ap.add_argument("--once", action="store_true", help="处理一条请求后退出")
    args = ap.parse_args(argv)
    server = McpServer(_load_docs(args.case, args.docs))
    return server.serve(once=args.once)


if __name__ == "__main__":
    raise SystemExit(main())
