"""并发基准：真实起一个 uvicorn，量并发 10 的端到端 P50/P95。

为什么单独写：`evals/perf.py` 量的是「内存里直接跑 Agent 循环」，
不含 HTTP 栈。异步化（async 端点 + `asyncio.to_thread`）到底有没有用，
要在真实 ASGI 上量。

    python scripts/async_bench.py [--n 40] [--concurrency 10]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import statistics
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

REPORT = os.path.join(ROOT, "evals", "report")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _serve(port: int, ready: threading.Event, holder: dict):
    import uvicorn
    from src.adapters.fastapi_api import create_app
    from src.app.wiring import build_web_api

    web = build_web_api(offline=True)
    app = create_app(web)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    holder["server"] = server
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _run():
        task = asyncio.create_task(server.serve())
        while not server.started:
            await asyncio.sleep(0.02)
        ready.set()
        try:
            await task
        except asyncio.CancelledError:
            pass

    loop.run_until_complete(_run())


async def _workload(base: str, n: int, concurrency: int) -> list[float]:
    import httpx

    lat: list[float] = []
    sem = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(base_url=base, timeout=30) as client:
        async def one(i: int):
            async with sem:
                t0 = time.perf_counter()
                r = await client.get("/api/cases", params={"limit": 20})
                r.raise_for_status()
                lat.append((time.perf_counter() - t0) * 1000)

        await asyncio.gather(*(one(i) for i in range(n)))
    return lat


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--concurrency", type=int, default=10)
    args = ap.parse_args()

    port = _free_port()
    ready, holder = threading.Event(), {}
    th = threading.Thread(target=_serve, args=(port, ready, holder), daemon=True)
    th.start()
    if not ready.wait(20):
        print("服务启动超时")
        return 1

    try:
        lat = asyncio.run(_workload(f"http://127.0.0.1:{port}", args.n, args.concurrency))
    finally:
        server = holder.get("server")
        if server is not None:
            server.should_exit = True
        th.join(timeout=10)

    lat.sort()
    p50 = statistics.median(lat)
    p95 = lat[min(len(lat) - 1, int(round(0.95 * (len(lat) - 1))))]
    out = {
        "requests": len(lat), "concurrency": args.concurrency,
        "p50_ms": round(p50, 1), "p95_ms": round(p95, 1),
        "max_ms": round(max(lat), 1),
        "throughput_rps": round(len(lat) / (sum(lat) / 1000 / args.concurrency), 1),
        "endpoint": "GET /api/cases (async 端点 + asyncio.to_thread)",
    }
    os.makedirs(REPORT, exist_ok=True)
    with open(os.path.join(REPORT, "async.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("ASGI 并发基准")
    print("=" * 46)
    print(f"请求 {out['requests']} 次 / 并发 {out['concurrency']}")
    print(f"P50 {out['p50_ms']} ms，P95 {out['p95_ms']} ms，最大 {out['max_ms']} ms")
    print(f"近似吞吐 {out['throughput_rps']} 次/s")
    print(f"报告已写入 {os.path.join(REPORT, 'async.json')}")
    return 0 if p95 <= 5000 else 1


if __name__ == "__main__":
    raise SystemExit(main())
