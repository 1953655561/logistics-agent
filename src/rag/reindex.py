"""重建 RAG 索引（增量）：python -m src.rag.reindex [--full] [--store PATH]

- 默认增量：对比 corpus 与已落盘索引的 chunk 指纹，只写有变化的部分；
- `--full` 强制整库重写；
- 输出"新增/更新/删除/未变"与耗时，供 CI 与人工判断。
"""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="增量重建 RAG 索引")
    ap.add_argument("--store", default="var/rag/index.json")
    ap.add_argument("--full", action="store_true")
    args = ap.parse_args(argv)

    from .store import rebuild

    out = rebuild(args.store, full=args.full)
    s = out["stats"]
    mode = "全量" if out["full"] else "增量"
    print(f"[{mode}] chunk {out['old_chunks']} → {out['chunks']}，"
          f"新增 {len(s['added'])}、更新 {len(s['updated'])}、删除 {len(s['removed'])}、"
          f"未变 {s['unchanged']}；耗时 {out['ms']} ms")
    if s["changed"]:
        for key in ("added", "updated", "removed"):
            if s[key]:
                print(f"  {key}: {', '.join(s[key][:10])}"
                      + (" …" if len(s[key]) > 10 else ""))
    print(f"  索引文件：{out['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
