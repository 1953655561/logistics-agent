"""FastAPI 启动入口：组装依赖 + uvicorn。

    python -m src.app.api --port 8000
    python -m src.app.api --dump-openapi web/openapi.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.adapters.fastapi_api import create_app              # noqa: E402
from src.app.wiring import build_web_api                     # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="关务审核 Web API / 审核台")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--offline", action="store_true", default=True,
                    help="使用离线 mock 模型（默认开启）")
    ap.add_argument("--no-review", action="store_true", help="关闭独立复核")
    ap.add_argument("--no-ratelimit", action="store_true", help="关闭令牌桶限流")
    ap.add_argument("--dump-openapi", metavar="PATH",
                    help="只导出 OpenAPI JSON，不启动服务")
    args = ap.parse_args(argv)

    web = build_web_api(offline=args.offline, review=not args.no_review,
                        ratelimit=not args.no_ratelimit)
    dist = os.path.join(ROOT, "web", "dist")
    app = create_app(web, static_dir=dist if os.path.isdir(dist) else None)

    if args.dump_openapi:
        path = os.path.abspath(args.dump_openapi)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(app.openapi(), f, ensure_ascii=False, indent=2)
        print(f"OpenAPI 已写入 {path}")
        return 0

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
