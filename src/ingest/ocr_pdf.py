"""扫描 PDF / 图片 → 页图 → OCR → 五单字段。

流程：
1. 逐页取图：优先用 ``pypdf`` 读扫描件里嵌入的图片（不需要 PyMuPDF）；
   文字层页面直接用文本；图片文件直接交给 Pillow；
2. 预处理：灰度、自动对比度、去噪（可选纠偏在 P1.2 补）；
3. ``OcrPort`` 识别 → 文本块（带坐标/置信度）；
4. 按行重排文本，先复用 :func:`pdf_text.parse_document` 抽单头字段；
5. 明细表用 OCR 块坐标按表头切列（比正则更抗列错位）；
6. 输出与 PDF/Excel 同一套五单字段名，附带 ``confidence`` / ``missing`` /
   ``checks`` / ``locators``，低置信不静默通过。

依赖：``pypdf`` 读扫描 PDF、``Pillow`` 处理图片、OCR 引擎见 :mod:`src.ingest.ocr`。
"""
from __future__ import annotations

import io
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from ..domain.codes import CURRENCIES
from .excel import (STOP_MARKERS, _match_item_header, _match_label,
                    _parse_elements, _to_number)
from .ocr import OcrBlock, OcrResult, get_ocr, group_rows
from .pdf_text import LABELS, REQUIRED, _postprocess, parse_document

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}

# 一页文本少于这么多字符，就当作没有文字层（与 detect.py 口径一致）
TEXT_MIN_CHARS = 20
# OCR 低于该置信度时转人工（P1.2 可按评测校准）
LOW_CONFIDENCE = 0.6
MAX_ITEMS = 500

ITEM_FIELDS = ("qty", "unit", "unit_price", "amount")

_CJK = re.compile(r"[\u4e00-\u9fff]")
# 拆分「一行多个标签」时只认中文标签：英文别名容易在值里误命中
_CJK_LABELS = sorted(
    {label for mapping in LABELS.values() for label in mapping if _CJK.search(label)},
    key=len, reverse=True)


@dataclass
class PageInput:
    number: int
    image: object | None = None      # PIL.Image
    text: str = ""
    source: str = ""                 # pdf-image / text-layer / image / empty


def preprocess(image):
    """OCR 前预处理：灰度；小图放大。

    实测（合成扫描件）中值滤波会把 8–10px 的小字糊掉，这里不做去噪滤镜；
    真实脏扫描再按评测结果加轻量处理，避免"预处理反而降低准确率"。
    """
    from PIL import Image

    img = image.convert("L")
    if img.width < 1200:
        scale = 1200 / max(img.width, 1)
        img = img.resize((int(img.width * scale), int(img.height * scale)),
                         Image.LANCZOS)
    return img


def load_pages(path) -> list[PageInput]:
    """把一份扫描 PDF / 图片拆成页。"""
    p = Path(path)
    ext = p.suffix.lower()
    if ext in IMAGE_EXTS:
        from PIL import Image

        with Image.open(p) as img:
            return [PageInput(1, img.convert("RGB"), source="image")]

    from pypdf import PdfReader  # 可选依赖

    reader = PdfReader(str(p))
    pages: list[PageInput] = []
    for number, page in enumerate(reader.pages, 1):
        try:
            text = (page.extract_text() or "").strip()
        except Exception:
            text = ""
        if len(text) >= TEXT_MIN_CHARS:
            pages.append(PageInput(number, text=text, source="text-layer"))
            continue
        image = _page_image(page)
        if image is not None:
            pages.append(PageInput(number, image=image, source="pdf-image"))
        else:
            pages.append(PageInput(number, text=text, source="empty"))
    return pages


def _page_image(page):
    """取页面里最大的嵌入图；取不到返回 None。"""
    try:
        images = list(page.images)
    except Exception:
        return None
    if not images:
        return None
    from PIL import Image

    best = max(images, key=lambda item: len(item.data or b""))
    try:
        with Image.open(io.BytesIO(best.data)) as img:
            return img.convert("RGB")
    except Exception:
        return None


def _lines_from_blocks(blocks: list[OcrBlock]) -> str:
    """按行合并文本块，再把「一行多个标签」拆成一行一个，便于复用 parse_document。"""
    lines = (" ".join(block.text for block in row) for row in group_rows(blocks))
    return "\n".join(segment for line in lines
                     for segment in _split_label_values(line))


def _split_label_values(line: str) -> list[str]:
    """把「装箱单号 X 日期 Y」拆成两行；只按中文标签拆，避免误伤英文值。"""
    hits: list[tuple[int, str]] = []
    used = [False] * len(line)
    for label in _CJK_LABELS:
        start = 0
        while True:
            index = line.find(label, start)
            if index < 0:
                break
            end = index + len(label)
            if any(used[index:end]):
                start = index + 1
                continue
            hits.append((index, label))
            for pos in range(index, end):
                used[pos] = True
            start = end
    if not hits:
        return [line]
    hits.sort()
    segments = []
    if hits[0][0] > 0:
        prefix = line[:hits[0][0]].strip()
        if prefix:
            segments.append(prefix)
    for order, (index, label) in enumerate(hits):
        end = hits[order + 1][0] if order + 1 < len(hits) else len(line)
        value = line[index + len(label):end].strip(" :：")
        # 「毛重(kg) 960.4」：去掉标签后的单位括号
        value = re.sub(r"^[（(][^）)]*[）)]\s*", "", value)
        segments.append(f"{label} {value}".strip())
    return segments


def _table_items(blocks: list[OcrBlock]) -> tuple[list[dict], list[str], dict]:
    """用 OCR 块坐标按表头切列，抽明细行与合计行。"""
    rows = group_rows(blocks)
    header_index = None
    columns: list[tuple[str, float, float]] = []
    for index, row in enumerate(rows):
        found: list[tuple[str, float, float]] = []
        for block in row:
            field = _match_item_header(block.text)
            if field and all(field != item[0] for item in found):
                found.append((field, block.bbox[0], block.bbox[2]))
        if (len(found) >= 3 and any(f == "name" for f, _, _ in found)
                and (any(f == "amount" for f, _, _ in found)
                     or (any(f == "qty" for f, _, _ in found)
                         and any(f in ("unit_price", "unit") for f, _, _ in found)))):
            header_index, columns = index, found
            break
    if header_index is None:
        return [], [], {}

    items: list[dict] = []
    checks: list[str] = []
    totals: dict = {}
    for row in rows[header_index + 1:]:
        values: dict[str, str] = {}
        for block in row:
            field = _column_for(block, columns)
            if not field:
                continue
            text = block.text.strip()
            if field in ("name", "name_en", "elements", "spec"):
                # 这些列可能被 OCR 拆成多个块，需要拼接
                values[field] = (values.get(field, "") + text).strip()
            else:
                # 数量/单位/金额/法定单位：只认第一个块，避免把邻列粘进来
                values.setdefault(field, text)

        name = values.get("name", "").strip()
        if not name or _is_total_row(row):
            # 明细结束：合计行的金额/数量回填到单头字段
            amount = _to_number(values.get("amount", ""))
            qty = _to_number(values.get("qty", ""))
            if amount is not None:
                totals["total_amount"] = amount
            if qty is not None:
                totals["qty_total"] = qty
            break

        # 「800个」被 OCR 合成一格时，把单位从数量里拆出来
        if not values.get("unit"):
            match = re.match(r"^([\d.,]+)\s*([个件套台只箱包卷张])$",
                             values.get("qty", ""))
            if match:
                values["qty"] = match.group(1)
                values["unit"] = match.group(2)

        item = _build_item(values)
        if item is None:
            break
        qty, price, amount = item.get("qty"), item.get("unit_price"), item.get("amount")
        if all(isinstance(v, (int, float)) for v in (qty, price, amount)):
            expected = float(qty) * float(price)
            if abs(expected - float(amount)) > max(0.01, abs(expected) * 0.01):
                checks.append(f"items[{len(items)}] 数量×单价={expected:.2f} ≠ 金额={amount}")
        items.append(item)
        if len(items) >= MAX_ITEMS:
            break
    return items, checks, totals


def _is_total_row(row: list[OcrBlock]) -> bool:
    from .excel import _compact

    for block in row:
        text = _compact(block.text)
        if text and any(text.startswith(_compact(marker)) for marker in STOP_MARKERS):
            return True
    return False


def _column_for(block: OcrBlock, columns: list[tuple[str, float, float]]) -> str | None:
    """把一个 OCR 块落到最可能的那一列：先看 x 重叠，再看中心距离。"""
    best_field, best_ratio = None, 0.0
    for field, x0, x1 in columns:
        overlap = max(0.0, min(block.bbox[2], x1) - max(block.bbox[0], x0))
        width = max(1.0, min(block.bbox[2] - block.bbox[0], x1 - x0))
        ratio = overlap / width
        if ratio > best_ratio:
            best_field, best_ratio = field, ratio
    if best_field is not None and best_ratio > 0:
        return best_field
    center = (block.bbox[0] + block.bbox[2]) / 2
    if not columns:
        return None
    return min(columns, key=lambda item: abs(center - (item[1] + item[2]) / 2))[0]


def _bottom_table(blocks: list[OcrBlock]) -> dict:
    """报关单底部「件数/毛重/净重」小表：表头一行、数值在下一行。"""
    rows = group_rows(blocks)
    for index, row in enumerate(rows[:-1]):
        columns: list[tuple[str, float, float]] = []
        for block in row:
            field, _ = _match_label("declaration", block.text)
            if field in ("packages", "gross_weight", "net_weight") and \
                    all(field != item[0] for item in columns):
                columns.append((field, block.bbox[0], block.bbox[2]))
        if len(columns) < 2:
            continue
        values: dict = {}
        for block in rows[index + 1]:
            field = _column_for(block, columns)
            if not field:
                continue
            number = _to_number(block.text, integer=(field == "packages"))
            if number is not None:
                values.setdefault(field, number)
        if values:
            return values
    return {}


def _build_item(values: dict) -> dict | None:
    item: dict = {"name": values.get("name", "").strip()}
    if not item["name"]:
        return None
    # 「塑料制玩具配件（通用）」：括号里通常是规格型号，拆回 elements.spec
    spec_in_name = ""
    match = re.match(r"^(.*?)[（(]([^）)]*)[）)]\s*$", item["name"])
    if match:
        item["name"] = match.group(1).strip()
        spec_in_name = match.group(2).strip()
    if values.get("name_en"):
        item["name_en"] = values["name_en"].strip()
    hs = re.sub(r"\s+", "", values.get("hs_code", ""))
    if hs:
        item["hs_code"] = hs
    for field in ITEM_FIELDS:
        raw = values.get(field, "").strip()
        if not raw:
            continue
        if field == "unit":
            item["unit"] = raw
        else:
            number = _to_number(raw, integer=(field == "qty"))
            item[field] = number if number is not None else raw
    item["origin"] = values.get("origin", "").strip().upper() or "CN"

    legal = values.get("legal_unit", "").strip()
    if legal:
        if "/" in legal:
            first, second = legal.split("/", 1)
            item["legal_unit1"] = first.strip()
            item["legal_unit2"] = second.strip()
        else:
            item["legal_unit1"] = legal

    elements = _parse_elements(values.get("elements", ""))
    if values.get("spec"):
        elements.setdefault("spec", values["spec"].strip())
    if spec_in_name:
        elements.setdefault("spec", spec_in_name)
    if elements:
        item["elements"] = elements
    return item


def _sanitize_fields(dtype: str, fields: dict) -> list[str]:
    """OCR 字段兜底校验：代码表纠错、币制取 3 位、数值解析不了就丢掉。"""
    import difflib

    from ..domain.codes import CURRENCIES, INCOTERMS, TRADE_MODE_EXEMPTION

    checks: list[str] = []
    currency = fields.get("currency")
    if isinstance(currency, str) and currency.strip():
        match = re.match(r"[A-Za-z]{3}", currency.strip())
        if match:
            fields["currency"] = match.group(0).upper()
        else:
            checks.append(f"币制识别异常：{currency[:30]}")
            fields.pop("currency", None)

    # 代码表字段：OCR 少一个字（如「般贸易」）时做最近邻纠正，并留痕
    candidates = {
        "trade_mode": set(TRADE_MODE_EXEMPTION),
        "incoterm": INCOTERMS,
        "currency": CURRENCIES,
    }
    for field, allowed in candidates.items():
        value = str(fields.get(field, "") or "").strip()
        if not value or value in allowed:
            continue
        match = difflib.get_close_matches(value, sorted(allowed), n=1, cutoff=0.75)
        if match:
            fields[field] = match[0]
            checks.append(f"{field} OCR 修正：{value} → {match[0]}")
        elif field == "trade_mode":
            checks.append(f"贸易方式不在代码表：{value}")

    # 证件号：OCR 常把相邻标签粘在值后面，只保留第一个编号
    for field in ("cert_no", "license_no"):
        value = str(fields.get(field, "") or "").strip()
        if not value:
            continue
        match = re.match(r"[A-Za-z0-9][A-Za-z0-9\-/]*", value)
        fields[field] = match.group(0) if match else value

    numeric_fields = ("total_amount", "qty_total", "packages", "gross_weight",
                      "net_weight", "volume", "freight", "insurance",
                      "discount", "commission", "royalty")
    for field in numeric_fields:
        value = fields.get(field)
        if isinstance(value, str) and value.strip():
            number = _to_number(value)
            if number is None:
                # 纯文字（多为表头被误当值）直接丢；带数字的才值得报
                if re.search(r"\d", value):
                    checks.append(f"{field} 无法解析：{value[:30]}")
                fields.pop(field, None)
            else:
                fields[field] = number
    return checks


def _locators(dtype: str, blocks: list[OcrBlock], page: int) -> dict:
    """单头字段 → 出处（页码 + 坐标 + 块文本 + 置信度）。"""
    locators: dict = {}
    labels = LABELS.get(dtype) or {}
    for block in blocks:
        text = block.text.strip()
        for label in sorted(labels, key=len, reverse=True):
            if text.startswith(label):
                field = labels[label]
                locators.setdefault(field, {
                    "page": page, "bbox": [round(v, 1) for v in block.bbox],
                    "text": text[:80], "confidence": block.confidence,
                })
                break
    return locators


def _page_result(path, page: PageInput, ocr) -> dict:
    if page.text:
        text = page.text
        blocks: list[OcrBlock] = []
        ocr_confidence = 1.0
        engine_name = "text-layer"
    elif page.image is not None:
        result: OcrResult = ocr.recognize(preprocess(page.image), page=page.number)
        blocks = result.blocks
        text = _lines_from_blocks(blocks) if blocks else result.text
        ocr_confidence = result.confidence
        engine_name = result.engine
    else:
        text, blocks, ocr_confidence, engine_name = "", [], 0.0, ocr.name

    parsed = parse_document(text, source=str(path))
    dtype = parsed["doc_type"]
    fields = parsed["fields"]
    checks: list[str] = []

    checks.extend(_sanitize_fields(dtype, fields))
    if dtype in ("invoice", "declaration", "contract") and not fields.get("currency"):
        for token in re.findall(r"\b[A-Z]{3}\b", text):
            if token in CURRENCIES:
                fields["currency"] = token
                checks.append(f"币制从文本补全：{token}")
                break
    if dtype in ("invoice", "packing_list", "bl", "declaration") and blocks:
        items, item_checks, totals = _table_items(blocks)
        checks.extend(item_checks)
        if items:
            fields["items"] = items
        if dtype == "declaration":
            for key, value in _bottom_table(blocks).items():
                if not fields.get(key):
                    fields[key] = value
        if dtype in ("invoice", "declaration"):
            for key in ("total_amount", "qty_total"):
                if totals.get(key) is not None and not fields.get(key):
                    fields[key] = totals[key]

    if dtype:
        missing = [field for field in REQUIRED[dtype] if not fields.get(field)]
        parsed["missing"] = missing
        parsed["confidence"] = round(
            1 - len(missing) / max(len(REQUIRED[dtype]), 1), 3)
    if dtype in ("invoice", "declaration") and not fields.get("total_amount"):
        checks.append("总价缺失：金额勾稽会失效")

    if ocr_confidence and ocr_confidence < LOW_CONFIDENCE:
        checks.append(f"OCR 平均置信度 {ocr_confidence:.2f} < {LOW_CONFIDENCE}")

    parse_confidence = float(parsed["confidence"]) if dtype else 0.0
    confidence = round(min(parse_confidence, ocr_confidence if ocr_confidence else 0.0), 3)
    if not blocks and page.source == "text-layer":
        confidence = round(parse_confidence, 3)
    blocking = (bool(parsed["missing"])
                or (ocr_confidence and ocr_confidence < LOW_CONFIDENCE)
                or any(("数量×单价" in check) or ("总价缺失" in check)
                       for check in checks))

    return {
        "path": str(path),
        "page": page.number,
        "doc_type": dtype,
        "fields": fields,
        "items": len(fields.get("items") or []),
        "missing": parsed["missing"],
        "confidence": confidence,
        "needs_human": bool(blocking or not dtype),
        "checks": checks,
        "text_chars": len(text),
        "engine": engine_name,
        "ocr_confidence": ocr_confidence,
        "page_source": page.source,
        "locators": _locators(dtype, blocks, page.number) if dtype else {},
    }


def extract_ocr(path, engine=None) -> list[dict]:
    """抽取扫描 PDF / 图片：逐页返回结果（一页可能一份单证）。"""
    ocr = engine or get_ocr()
    pages = load_pages(path)
    return [_page_result(path, page, ocr) for page in pages]


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("用法: python -m src.ingest.ocr_pdf <扫描件.pdf|图片> [<文件> ...]")
        return 2
    for item in argv:
        try:
            results = extract_ocr(item)
        except ImportError as exc:
            print(json.dumps({"path": item, "error": str(exc)}, ensure_ascii=False))
            continue
        except Exception as exc:  # noqa: BLE001 - CLI 只负责打印
            print(json.dumps({"path": item, "error": f"{type(exc).__name__}: {exc}"},
                             ensure_ascii=False))
            continue
        print(json.dumps({"path": str(Path(item)), "pages": results},
                         ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
