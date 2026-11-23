"""原始文件 → 五单 JSON → 审核：最小端到端管线（文字层 PDF + Excel + OCR）。

    python -m src.ingest.pipeline examples/raw/pdf/*.pdf
    python -m src.ingest.pipeline examples/raw/合成发票-INV-2026-0901.xlsx examples/raw/pdf/其他四份.pdf
    python -m src.ingest.pipeline examples/raw/合成扫描件-多页.pdf examples/raw/pdf/其余三份.pdf

三种抽取链路：``route=table``（Excel，一个工作簿可多 sheet）、``route=text``
（文字层 PDF，一文件一单证）、``route=ocr``（扫描 PDF / 图片，一页可能一单证）。
"""
from __future__ import annotations

import json
import sys

from ..engine import audit
from .detect import detect
from .excel import extract_workbook
from .ocr_pdf import extract_ocr
from .pdf_text import extract


def _merge(docs: dict, best_confidence: dict, dtype: str, result: dict) -> None:
    """同一类型保留置信度更高的一份（隐藏模板/重复页不覆盖正式结果）。"""
    if result["confidence"] >= best_confidence.get(dtype, -1.0):
        docs[dtype] = result["fields"]
        best_confidence[dtype] = result["confidence"]


def _ingest_excel(item, det) -> tuple[dict, list[dict]]:
    """Excel：一个工作簿可能含多份单证，只要有 sheet 识别成功就都收进来。"""
    try:
        results = extract_workbook(item)
    except ImportError:
        return {}, [{
            "path": str(item), "kind": det.kind, "route": det.route,
            "status": "需要安装 openpyxl（pip install openpyxl）",
        }]
    except Exception as exc:  # noqa: BLE001 - 单文件失败不拖垮整批
        return {}, [{
            "path": str(item), "kind": det.kind, "route": det.route,
            "status": f"Excel 解析失败：{type(exc).__name__}: {exc}",
        }]
    docs: dict = {}
    details: list[dict] = []
    best_confidence: dict[str, float] = {}
    for result in results:
        dtype = result["doc_type"]
        if dtype:
            _merge(docs, best_confidence, dtype, result)
        details.append({
            "path": str(item), "sheet": result["sheet"],
            "kind": det.kind, "route": det.route,
            "doc_type": dtype, "confidence": result["confidence"],
            "missing": result["missing"], "text_chars": result["text_chars"],
            "checks": result["checks"],
            "status": "ok" if dtype else "单证类型未识别",
        })
    return docs, details


def _ingest_ocr(item, det) -> tuple[dict, list[dict]]:
    """扫描 PDF / 图片：逐页抽取，一页可能一份单证。"""
    try:
        results = extract_ocr(item)
    except ImportError as exc:
        return {}, [{
            "path": str(item), "kind": det.kind, "route": det.route,
            "status": f"需要 OCR 依赖：{exc}",
        }]
    except Exception as exc:  # noqa: BLE001 - 单文件失败不拖垮整批
        return {}, [{
            "path": str(item), "kind": det.kind, "route": det.route,
            "status": f"OCR 解析失败：{type(exc).__name__}: {exc}",
        }]
    docs: dict = {}
    details: list[dict] = []
    best_confidence: dict[str, float] = {}
    for result in results:
        dtype = result["doc_type"]
        if dtype:
            _merge(docs, best_confidence, dtype, result)
        if dtype:
            status = "ok"
        elif result["engine"] == "mock" and not result["text_chars"]:
            status = "未安装 OCR 引擎（pip install -r requirements-ocr.txt）"
        else:
            status = "单证类型未识别"
        details.append({
            "path": str(item), "page": result["page"],
            "kind": det.kind, "route": det.route,
            "doc_type": dtype, "confidence": result["confidence"],
            "missing": result["missing"], "text_chars": result["text_chars"],
            "checks": result["checks"], "engine": result["engine"],
            "ocr_confidence": result["ocr_confidence"],
            "page_source": result["page_source"],
            "status": status,
        })
    return docs, details


def _absorb(docs: dict, best_confidence: dict, incoming: dict,
            details: list[dict]) -> None:
    """把一个多单抽取器（Excel/OCR）的结果并入总 docs，仍按置信度取高。"""
    for dtype, fields in incoming.items():
        confidence = max((item.get("confidence", 0.0) for item in details
                          if item.get("doc_type") == dtype), default=0.0)
        if confidence >= best_confidence.get(dtype, -1.0):
            docs[dtype] = fields
            best_confidence[dtype] = confidence


def ingest(paths: list[str]) -> tuple[dict, list[dict]]:
    """按类型检测路由到对应抽取器，把结果合并成五单 docs。"""
    docs: dict = {}
    details: list[dict] = []
    best_confidence: dict[str, float] = {}
    for item in paths:
        det = detect(item)
        if det.kind == "excel":
            sheet_docs, sheet_details = _ingest_excel(item, det)
            _absorb(docs, best_confidence, sheet_docs, sheet_details)
            details.extend(sheet_details)
        elif det.kind == "text_pdf":
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
                _merge(docs, best_confidence, dtype, r)
            details.append({
                "path": str(item), "kind": det.kind, "route": det.route,
                "doc_type": dtype, "confidence": r["confidence"],
                "missing": r["missing"], "text_chars": r["text_chars"],
                "status": "ok" if dtype else "单证类型未识别",
            })
        elif det.route == "ocr":
            ocr_docs, ocr_details = _ingest_ocr(item, det)
            _absorb(docs, best_confidence, ocr_docs, ocr_details)
            details.extend(ocr_details)
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
