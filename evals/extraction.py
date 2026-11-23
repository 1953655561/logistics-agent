"""抽取层评测（W7）：字段准确率 + 文档类型准确率 + 字段 CER。

和端到端评测分开：OCR 错一个 0 导致结论变 REVIEW，必须能分清是"抽错"还是"判错"。

    python evals/extraction.py            # 跑评测，写 evals/report/extraction.md
    python evals/extraction.py --json     # 额外打印机器可读结果

黄金值取 ``examples/realistic/REAL-002-amount-mismatch-FIX.json``（合成数据），
与四类路由的合成样本同源，便于把「Excel / 文字层 PDF / 扫描件」放在同一口径下比较。
没有 OCR 依赖时，OCR 两条路由自动跳过并在报告里标注。
"""
from __future__ import annotations

import json
import os
import sys
from difflib import SequenceMatcher

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

REPORT = os.path.join(ROOT, "evals", "report")
GOLDEN = os.path.join(ROOT, "examples", "realistic", "REAL-002-amount-mismatch-FIX.json")
RAW = os.path.join(ROOT, "examples", "raw")
PDF = os.path.join(RAW, "pdf")
MISSING = "<缺失>"

# 每个单证参与比对的字段（只比业务关心的；不把 golden 里的可选字段全算错）
COMPARE: dict[str, list[str]] = {
    "contract": ["contract_no", "seller", "buyer", "date", "currency",
                 "incoterm", "total_amount"],
    "invoice": ["invoice_no", "contract_no", "date", "seller", "buyer",
                "currency", "incoterm", "discount", "commission", "royalty",
                "total_amount"],
    "packing_list": ["pl_no", "date", "packages", "package_type", "gross_weight",
                     "net_weight", "volume", "marks", "wood_packaging"],
    "bl": ["bl_no", "date", "arrival_date", "vessel", "voyage", "pol", "pod",
           "shipper", "consignee", "notify", "packages", "gross_weight", "volume"],
    "declaration": ["decl_no", "declare_date", "consignee", "transport_mode",
                    "trade_mode", "exemption_nature", "origin_country",
                    "loading_port", "destination", "incoterm", "currency",
                    "freight", "insurance", "contract_no", "bl_no", "packages",
                    "gross_weight", "net_weight", "total_amount", "cert_no"],
}
ITEM_COMPARE = {
    "invoice": ["name", "hs_code", "qty", "unit", "unit_price", "amount"],
    "declaration": ["name", "hs_code", "qty", "unit", "unit_price", "amount",
                    "legal_unit1", "legal_unit2"],
}
ELEMENT_KEYS = ("brand_type", "material", "use", "spec")


def _clean(value) -> str:
    """OCR 可能少空格/多空格；比对时去掉空白并大写。"""
    return "".join(str(value).split()).upper()


def _equal(expected, actual) -> bool:
    if actual == MISSING:
        return False
    if isinstance(expected, bool) or isinstance(actual, bool):
        return bool(expected) == bool(actual)
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return abs(float(expected) - float(actual)) <= 0.01
    if isinstance(expected, dict) and isinstance(actual, dict):
        return _clean(expected) == _clean(actual)
    return _clean(expected) == _clean(actual)


def _row(field: str, expected, actual) -> dict:
    ok = _equal(expected, actual)
    cer = None
    if isinstance(expected, str) and actual != MISSING:
        ratio = SequenceMatcher(None, _clean(expected), _clean(actual)).ratio()
        cer = round(1 - ratio, 4)
    return {"field": field, "expected": expected, "actual": actual,
            "ok": ok, "cer": cer}


def compare_doc(dtype: str, expected: dict, actual: dict) -> list[dict]:
    actual = actual or {}
    rows = []
    for field in COMPARE.get(dtype, []):
        if field not in expected:
            continue
        rows.append(_row(field, expected[field], actual.get(field, MISSING)))
    expected_items = expected.get("items") or []
    actual_items = actual.get("items") or []
    # 只有发票/报关单的明细是必填；装箱单/提单明细不计入抽取准确率
    compare_items = dtype in ("invoice", "declaration")
    if compare_items and expected_items:
        rows.append(_row("items.count", len(expected_items), len(actual_items)))
    for index, expected_item in enumerate(expected_items if compare_items else []):
        actual_item = actual_items[index] if index < len(actual_items) else {}
        for field in ITEM_COMPARE.get(dtype, []):
            if field in expected_item:
                rows.append(_row(f"items[{index}].{field}", expected_item[field],
                                 actual_item.get(field, MISSING)))
        if dtype != "declaration":
            continue
        expected_elements = expected_item.get("elements") or {}
        actual_elements = actual_item.get("elements") or {}
        for key in ELEMENT_KEYS:
            if key in expected_elements:
                rows.append(_row(f"items[{index}].elements.{key}",
                                 expected_elements[key],
                                 actual_elements.get(key, MISSING)))
    for row in rows:
        row["doc"] = dtype
    return rows


def _load_golden() -> dict:
    with open(GOLDEN, encoding="utf-8") as f:
        return json.load(f)


def _route_excel() -> dict:
    from src.ingest.excel import extract

    path = os.path.join(RAW, "合成发票-INV-2026-0901.xlsx")
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    result = extract(path)
    return {result["doc_type"]: result["fields"]} if result["doc_type"] else {}


def _route_pdf() -> dict:
    from src.ingest.pdf_text import extract

    docs = {}
    for name in os.listdir(PDF):
        if not name.endswith(".pdf"):
            continue
        result = extract(os.path.join(PDF, name))
        if result["doc_type"]:
            docs[result["doc_type"]] = result["fields"]
    return docs


def _route_ocr(filename: str) -> dict:
    from src.ingest.ocr import get_ocr
    from src.ingest.ocr_pdf import extract_ocr

    if get_ocr().name == "mock":
        raise ImportError("未安装 OCR 引擎（pip install -r requirements-ocr.txt）")
    path = os.path.join(RAW, filename)
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    docs = {}
    for result in extract_ocr(path):
        if result["doc_type"]:
            docs[result["doc_type"]] = result["fields"]
    return docs


def evaluate() -> dict:
    golden = _load_golden()
    routes = [
        ("Excel（发票）", {"invoice"}, _route_excel),
        ("文字层 PDF（五单）", {"contract", "invoice", "packing_list", "bl", "declaration"}, _route_pdf),
        ("OCR 扫描件（2 页）", {"packing_list", "declaration"},
         lambda: _route_ocr("合成扫描件-多页.pdf")),
        ("OCR 扫描件（5 页）", {"contract", "invoice", "packing_list", "bl", "declaration"},
         lambda: _route_ocr("合成扫描件-五单.pdf")),
    ]
    results = []
    for label, expected_docs, runner in routes:
        entry = {"route": label, "skipped": False, "doc_type_accuracy": 0.0,
                 "field_accuracy": 0.0, "cer": None, "rows": []}
        try:
            docs = runner()
        except Exception as exc:  # noqa: BLE001 - 缺依赖/样本时跳过，不阻断报告
            entry.update(skipped=True, reason=f"{type(exc).__name__}: {exc}")
            results.append(entry)
            continue
        found = set(docs) & expected_docs
        entry["doc_type_accuracy"] = round(len(found) / len(expected_docs), 4)
        rows = []
        for dtype in expected_docs & set(golden):
            rows.extend(compare_doc(dtype, golden[dtype], docs.get(dtype, {})))
        entry["rows"] = rows
        total = len(rows) or 1
        entry["field_accuracy"] = round(sum(1 for row in rows if row["ok"]) / total, 4)
        cers = [row["cer"] for row in rows if row["cer"] is not None]
        entry["cer"] = round(sum(cers) / len(cers), 4) if cers else None
        entry["correct"] = sum(1 for row in rows if row["ok"])
        entry["total"] = len(rows)
        results.append(entry)
    return {"golden": os.path.relpath(GOLDEN, ROOT),
            "routes": results}


def render(report: dict) -> str:
    lines = ["# 抽取层评测（W7）", "",
             f"> 黄金值：`{report['golden']}`（合成数据，与各路由样本同源）",
             "> 指标口径：字段准确率 = 正确字段/比对字段；CER = 字符串字段的字符错误率均值。",
             "", "| 路由 | 类型准确率 | 字段准确率 | 字段 CER | 正确/比对 | 状态 |",
             "|---|---|---|---|---|---|"]
    for entry in report["routes"]:
        if entry.get("skipped"):
            lines.append(f"| {entry['route']} | - | - | - | - | 跳过（{entry['reason']}） |")
            continue
        cer = "-" if entry["cer"] is None else f"{entry['cer']:.3f}"
        lines.append(f"| {entry['route']} | {entry['doc_type_accuracy']:.0%} | "
                     f"{entry['field_accuracy']:.1%} | {cer} | "
                     f"{entry['correct']}/{entry['total']} | ok |")
    lines += ["", "## 错误明细", ""]
    errors = [(entry["route"], row) for entry in report["routes"]
              if not entry.get("skipped") for row in entry["rows"] if not row["ok"]]
    if not errors:
        lines.append("无。")
    else:
        for route, row in errors[:30]:
            lines.append(f"- **{route}** {row['doc']}.{row['field']}：期望 "
                         f"`{row['expected']}`，实得 `{row['actual']}`")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    argv = sys.argv[1:] if argv is None else argv
    report = evaluate()

    os.makedirs(REPORT, exist_ok=True)
    with open(os.path.join(REPORT, "extraction.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    markdown = render(report)
    with open(os.path.join(REPORT, "extraction.md"), "w", encoding="utf-8") as f:
        f.write(markdown)

    print(markdown)
    if "--json" in argv:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
