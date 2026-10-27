"""无第三方依赖的兜底 HTTP 服务：同一套 WebApi + 原生 HTML 审核台。

    python -m src.app.fallback_server --port 8000

优先服务 `web/fallback/index.html`（无构建），如果 `web/dist/index.html` 存在，
也可以用它查看构建后的 AntD 审核台。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.app.wiring import build_web_api                   # noqa: E402
from src.application.web_api import WebApi, WebApiError    # noqa: E402

FALLBACK_INDEX = os.path.join(ROOT, "web", "fallback", "index.html")
CONTENT_TYPES = {".html": "text/html; charset=utf-8",
                 ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8",
                 ".json": "application/json; charset=utf-8",
                 ".svg": "image/svg+xml", ".png": "image/png",
                 ".ico": "image/x-icon"}


class Handler(BaseHTTPRequestHandler):
    web: WebApi = None          # 由 make_handler 注入
    static_dir: str = ""

    # ---------- 响应 ----------
    def _send(self, status: int, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data, status: int = 200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _error(self, message: str, status: int = 400):
        self._json({"detail": message}, status=status)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise WebApiError("请求体不是合法 JSON")

    # ---------- 路由 ----------
    def do_OPTIONS(self):
        self._send(204, b"", "text/plain")

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        try:
            if path == "/api/health":
                return self._json(self.web.health())
            if path == "/api/cases":
                return self._json(self.web.list_cases())
            if path == "/api/scenarios":
                return self._json(self.web.list_scenarios())
            if path == "/api/rules":
                return self._json(self.web.list_rules())
            if path == "/api/metrics":
                return self._json(self.web.metrics())
            if path.startswith("/api/cases/"):
                parts = path.strip("/").split("/")
                # /api/cases/{id} 或 /api/cases/{id}/docs|trace
                case_id = parts[2]
                if len(parts) == 3:
                    return self._json(self.web.get_case(case_id))
                if len(parts) == 4 and parts[3] == "docs":
                    return self._json(self.web.get_docs(case_id))
                if len(parts) == 4 and parts[3] == "trace":
                    return self._json(self.web.get_trace(case_id))
            if path.startswith("/api/"):
                return self._error("接口不存在", 404)
            return self._static(path)
        except WebApiError as exc:
            return self._error(exc.message, exc.status)
        except Exception as exc:  # 兜底：服务不崩
            return self._error(f"{type(exc).__name__}: {exc}", 500)

    def do_POST(self):
        path = unquote(urlparse(self.path).path)
        try:
            body = self._body()
            if path == "/api/cases/import":
                return self._json(self.web.import_case(
                    str(body.get("case_id", "")), body.get("docs")))
            if path == "/api/extract":
                return self._json(self.web.extract(str(body.get("text", ""))))
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "cases":
                case_id, action = parts[2], parts[3]
                if action == "audit":
                    return self._json(self.web.audit(case_id, body.get("docs")))
                if action == "ask":
                    return self._json(self.web.ask(case_id, str(body.get("question", ""))))
                if action == "approve":
                    approved = body.get("approved")
                    if not isinstance(approved, bool):
                        return self._error("approved 必须是布尔值")
                    return self._json(self.web.decide(
                        case_id, approved, str(body.get("comment", "")), "web"))
            return self._error("接口不存在", 404)
        except WebApiError as exc:
            return self._error(exc.message, exc.status)
        except Exception as exc:
            return self._error(f"{type(exc).__name__}: {exc}", 500)

    # ---------- 静态页 ----------
    def _static(self, path: str):
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        candidates: list[tuple[str, str]] = []
        if self.static_dir:
            base = os.path.abspath(self.static_dir)
            candidates.append((os.path.join(base, "index.html" if path in ("/", "") else rel), base))
        fallback_base = os.path.dirname(FALLBACK_INDEX)
        candidates.append((os.path.join(fallback_base, rel), fallback_base))

        for candidate, base in candidates:
            candidate = os.path.abspath(candidate)
            if not candidate.startswith(base + os.sep):
                continue
            if os.path.isfile(candidate):
                with open(candidate, "rb") as f:
                    body = f.read()
                ext = os.path.splitext(candidate)[1].lower()
                return self._send(200, body,
                                  CONTENT_TYPES.get(ext, "application/octet-stream"))
        # SPA 回退：非 API 路径统一回 index.html
        for index in ((os.path.join(self.static_dir, "index.html") if self.static_dir else ""),
                      FALLBACK_INDEX):
            if index and os.path.isfile(index):
                with open(index, "rb") as f:
                    return self._send(200, f.read(), CONTENT_TYPES[".html"])
        return self._error("前端页面不存在", 404)

    def log_message(self, fmt, *args):  # 安静一点
        pass


def make_server(web: WebApi, host: str = "127.0.0.1", port: int = 8000,
                static_dir: str = "") -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"web": web, "static_dir": static_dir})
    return ThreadingHTTPServer((host, port), handler)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="关务审核台（无第三方依赖兜底服务）")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--offline", action="store_true", default=True)
    ap.add_argument("--no-review", action="store_true")
    ap.add_argument("--no-ratelimit", action="store_true")
    args = ap.parse_args(argv)

    web = build_web_api(offline=args.offline, review=not args.no_review,
                        ratelimit=not args.no_ratelimit)
    dist = os.path.join(ROOT, "web", "dist")
    server = make_server(web, args.host, args.port,
                         static_dir=dist if os.path.isdir(dist) else "")
    print(f"兜底审核台：http://{args.host}:{server.server_address[1]}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
