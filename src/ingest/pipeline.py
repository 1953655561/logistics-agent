"""原始文件 → 五单 JSON → 审核：最小端到端管线（文字层 PDF）。

    python -m src.ingest.pipeline examples/raw/pdf/*.pdf
"""
from __future__ import annotations

import json
import sys

from ..engine import audit
from .detect import detect
from .pdf_text import extract


def ingest(paths: list[str]) -> tuple[dict, list[dict]]:
    """按类型检测路由到对应抽取器，把结果合并成五单 docs。"""
    docs: dict = {}
    details: list[dict] = []
    for item in paths:
        det = detect(item)
        if det.kind == "text_pdf":
            try:
                r = extract(item)
            except ImportError:
                details.append({
                    "path": str(item), "kind": det.kind, "route": det.route,
                    "status": "需要安装 pypdf（pip install pypdf）",
                })
                continue
            dtype = r["doc_type"]
            if dtype:
                docs[dtype] = r["fields"]
            details.append({
                "path": str(item), "kind": det.kind, "route": det.route,
                "doc_type": dtype, "confidence": r["confidence"],
                "missing": r["missing"], "text_chars": r["text_chars"],
                "status": "ok" if dtype else "单证类型未识别",
            })
        else:
            details.append({
                "path": str(item), "kind": det.kind, "route": det.route,
                "status": f"暂未实现（route={det.route}）",
            })
    return docs, details


def run(paths: list[str]) -> dict:
    docs, details = ingest(paths)
    report = audit(docs)
    return {
        "docs": docs,
        "details": details,
        "verdict": report["verdict"],
        "issue_count": report["issue_count"],
        "issues": report["issues"],
        "missing_docs": [d for d in ("contract", "invoice", "packing_list", "bl", "declaration")
                         if d not in docs],
    }


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("用法: python -m src.ingest.pipeline <文件> [<文件> ...]")
        return 2
    out = run(argv)
    payload = {
        "details": out["details"],
        "docs": sorted(out["docs"]),
        "missing_docs": out["missing_docs"],
        "verdict": out["verdict"],
        "issue_count": out["issue_count"],
        "issues": [
            {"rule_id": i.get("rule_id"), "severity": i.get("severity"),
             "field_path": i.get("field_path"), "message": i.get("message")}
            for i in out["issues"]
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
