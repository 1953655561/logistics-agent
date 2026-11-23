"""Excel 单证 → 五单字段（``route=table``）。

版式假设（与 ``docs/10-raw-data-ingest.md`` 第 4 节一致）：

- 单头字段是同一行里的「标签 + 值」相邻单元格，允许跨列合并；
- 明细表有独立表头行，逐列按**同义词**映射，遇到合计/折扣/佣金/特许权等停止；
- 单证类型靠「标题关键词 + 标签命中数」判断，**不硬编码列号**；
- 输出字段名与 :mod:`src.ingest.pdf_text` 完全一致，两类文件可混跑。

依赖：``openpyxl``（可选）。本模块可被安全导入；未安装时 ``extract`` 抛
``ImportError``，由 :mod:`src.ingest.pipeline` 提示安装，不中断整条链路。
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import sys
import unicodedata
from pathlib import Path

from .pdf_text import FLOAT_FIELDS, INT_FIELDS, REQUIRED, _postprocess

# 判断标题时只看前几行（真实表格的标题/抬头一般都在这里）
TITLE_ROWS = 6

# 单头字段同义词：field -> 标签写法。匹配时**长标签优先**，
# 例如「发票总额」必须先于「总额」，「申报日期」必须先于「日期」。
LABELS: dict[str, dict[str, tuple[str, ...]]] = {
    "contract": {
        "contract_no": ("合同号", "合同编号", "合同号码", "CONTRACT NO", "CONTRACT NUMBER"),
        "seller": ("卖方", "出口商", "供货方", "SELLER", "EXPORTER", "VENDOR"),
        "buyer": ("买方", "进口商", "采购方", "BUYER", "IMPORTER"),
        "date": ("签订日期", "合同日期", "日期", "SIGNED DATE", "CONTRACT DATE", "DATE"),
        "currency": ("币制", "币种", "货币", "CURRENCY"),
        "incoterm": ("成交方式", "贸易术语", "价格条款", "INCOTERM", "TRADE TERM"),
        "total_amount": ("合同总额", "合同金额", "合同总价", "总金额",
                         "CONTRACT AMOUNT", "TOTAL AMOUNT"),
        "terms": ("合同条款", "条款", "TERMS"),
        "payment": ("付款方式", "支付方式", "PAYMENT"),
    },
    "invoice": {
        "invoice_no": ("发票号", "发票号码", "发票编号",
                       "INVOICE NO", "INVOICE NUMBER", "INVOICE#"),
        "contract_no": ("合同号", "合同编号", "CONTRACT NO", "CONTRACT NUMBER"),
        "date": ("发票日期", "开票日期", "日期", "INVOICE DATE", "DATE"),
        "seller": ("卖方", "出口商", "供应商", "SELLER", "EXPORTER", "VENDOR"),
        "buyer": ("买方", "进口商", "购买方", "BUYER", "IMPORTER"),
        "currency": ("币制", "币种", "货币", "CURRENCY"),
        "incoterm": ("成交方式", "贸易术语", "INCOTERM", "TRADE TERM"),
        "discount": ("折扣", "减让", "DISCOUNT"),
        "commission": ("佣金", "COMMISSION"),
        "royalty": ("特许权使用费", "特许权费", "特许权", "ROYALTY"),
        "total_amount": ("发票总额", "发票金额", "价税合计", "含税总额", "总额",
                         "INVOICE TOTAL", "TOTAL AMOUNT", "GRAND TOTAL", "AMOUNT DUE"),
    },
    "packing_list": {
        "pl_no": ("装箱单号", "箱单号", "PACKING LIST NO", "PL NO"),
        "date": ("装箱日期", "日期", "DATE"),
        "packages": ("总件数", "件数", "箱数", "TOTAL PACKAGES", "PACKAGES", "CTNS"),
        "package_type": ("包装种类", "包装方式", "PACKAGE TYPE", "PACKING"),
        "gross_weight": ("总毛重", "毛重", "GROSS WEIGHT", "G.W.", "GW"),
        "net_weight": ("总净重", "净重", "NET WEIGHT", "N.W.", "NW"),
        "volume": ("总体积", "体积", "容积", "TOTAL VOLUME", "VOLUME", "CBM"),
        "marks": ("唛头", "麦头", "标记", "MARKS", "SHIPPING MARKS"),
        "wood_packaging": ("木包装", "木质包装", "WOOD PACKAGING"),
    },
    "bl": {
        "bl_no": ("提单号", "提单号码", "BILL OF LADING NO", "B/L NO", "BL NO"),
        "date": ("签发日期", "装船日期", "开船日期", "日期",
                 "SHIPPED ON BOARD", "ISSUE DATE", "DATE"),
        "arrival_date": ("到港日期", "到港日", "预计到港", "ARRIVAL DATE", "ETA"),
        "vessel": ("船名", "船舶名称", "VESSEL", "SHIP NAME"),
        "voyage": ("航次", "VOYAGE", "VOYAGE NO"),
        "pol": ("起运港", "装运港", "出发港", "PORT OF LOADING", "POL"),
        "pod": ("目的港", "卸货港", "PORT OF DISCHARGE", "POD"),
        "shipper": ("发货人", "托运人", "SHIPPER"),
        "consignee": ("收货人", "CONSIGNEE"),
        "notify": ("通知人", "通知方", "NOTIFY PARTY", "NOTIFY"),
        "packages": ("总件数", "件数", "PACKAGES", "CTNS"),
        "gross_weight": ("毛重", "GROSS WEIGHT", "G.W."),
        "volume": ("体积", "VOLUME", "CBM"),
    },
    "declaration": {
        "decl_no": ("报关单号", "报关单编号", "DECLARATION NO", "DECL NO"),
        "declare_date": ("申报日期", "DECLARE DATE", "DECLARATION DATE"),
        "consignee": ("收发货人", "收发货人名称", "收货人", "CONSIGNEE"),
        "transport_mode": ("运输方式", "TRANSPORT MODE"),
        "trade_mode": ("贸易方式", "TRADE MODE"),
        "exemption_nature": ("征免性质", "EXEMPTION NATURE"),
        "origin_country": ("启运国", "启运国（地区）", "原产国", "ORIGIN COUNTRY"),
        "loading_port": ("装货港", "装运港", "PORT OF LOADING"),
        "destination": ("境内目的地", "目的地", "DESTINATION"),
        "incoterm": ("成交方式", "INCOTERM"),
        "currency": ("币制", "币种", "CURRENCY"),
        "freight": ("运费", "FREIGHT"),
        "insurance": ("保险费", "保费", "INSURANCE"),
        "contract_no": ("合同号", "合同编号", "CONTRACT NO"),
        "bl_no": ("提单号", "提单号码", "BILL OF LADING NO", "BL NO"),
        "packages": ("件数", "总件数", "PACKAGES"),
        "gross_weight": ("毛重", "GROSS WEIGHT", "G.W."),
        "net_weight": ("净重", "NET WEIGHT", "N.W."),
        "total_amount": ("总价", "总金额", "TOTAL AMOUNT", "TOTAL VALUE"),
        "license_no": ("许可证号", "LICENSE NO"),
        "cert_no": ("证书号", "CERT NO"),
    },
}

# 明细表列同义词：field -> 表头写法（同样长表头优先）
ITEM_HEADERS: dict[str, tuple[str, ...]] = {
    "idx": ("项号", "序号", "项次", "ITEM NO", "SN", "NO."),
    "name": ("商品名称及规格型号", "品名描述", "商品名称", "货物名称",
             "品名", "名称", "GOODS DESCRIPTION", "DESCRIPTION", "COMMODITY", "ITEM NAME", "品"),
    "spec": ("规格型号", "规格/型号", "规格", "型号", "SPEC", "MODEL", "SPECIFICATION"),
    "hs_code": ("HS编码", "商品编号", "商品编码", "税则号列", "海关编码",
                "HS CODE", "HS"),
    "qty": ("数量", "QTY", "QUANTITY"),
    "unit": ("计量单位", "单位", "UNIT", "UOM"),
    "unit_price": ("单价", "UNIT PRICE", "PRICE"),
    "amount": ("金额", "小计", "总价", "AMOUNT", "TOTAL", "VALUE"),
    "origin": ("原产国", "原产地", "ORIGIN", "COUNTRY OF ORIGIN"),
    "legal_unit": ("法定单位", "LEGAL UNIT"),
    "elements": ("申报要素", "ELEMENTS"),
    "name_en": ("英文品名", "品名英文", "ENGLISH NAME", "NAME EN"),
}

# 明细表结束标志（表头下方的汇总/附注行）
STOP_MARKERS = (
    "合计", "总计", "小计", "总额", "折扣", "佣金", "特许权",
    "备注", "条款", "声明", "签字", "盖章",
    "TOTAL", "SUBTOTAL", "DISCOUNT", "COMMISSION", "ROYALTY", "REMARK", "NOTE",
)

# 标题关键词：只用于前 TITLE_ROWS 行 + sheet 名。顺序 = 同分时的优先级
TITLE_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("declaration", ("报关单", "CUSTOMS DECLARATION", "DECLARATION")),
    ("invoice", ("商业发票", "增值税专用发票", "COMMERCIAL INVOICE", "INVOICE")),
    ("packing_list", ("装箱单", "PACKING LIST")),
    ("bl", ("提单", "BILL OF LADING")),
    ("contract", ("合同", "CONTRACT")),
)

DATE_FIELDS = {"date", "arrival_date", "declare_date"}
NUM_FIELDS = FLOAT_FIELDS | INT_FIELDS | {"packages", "total_amount"}

MAX_ITEMS = 500


def _compact(value) -> str:
    """归一化：全角转半角、去括号单位、只留字母/数字/汉字并大写。"""
    text = unicodedata.normalize("NFKC", str(value))
    text = re.sub(r"[（(][^）)]*[）)]", "", text)
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", text).upper()


def _build_index(mapping: dict[str, tuple[str, ...]]) -> list[tuple[str, str, str]]:
    pairs = [( _compact(alias), field, alias)
             for field, aliases in mapping.items() for alias in aliases]
    # 长标签优先（发票总额 > 总额，申报日期 > 日期）
    return sorted(pairs, key=lambda x: -len(x[0]))


_LABEL_INDEX = {dtype: _build_index(mapping) for dtype, mapping in LABELS.items()}
_ITEM_INDEX = _build_index(ITEM_HEADERS)


def _split_inline(raw) -> tuple[str, str]:
    """把「标签：值」拆开；没有分隔符时整段视为标签。"""
    text = str(raw)
    for sep in ("：", ":", "="):
        if sep in text:
            left, right = text.split(sep, 1)
            return left, right.strip()
    return text, ""


def _match_label(dtype: str, raw) -> tuple[str | None, str]:
    """判断一个单元格是不是单头标签；返回 (字段, 同一单元格里的值)。"""
    index = _LABEL_INDEX.get(dtype) or []
    text, inline = _split_inline(raw)
    norm = _compact(text)
    if not norm:
        return None, ""
    for key_norm, field, key_raw in index:
        if not norm.startswith(key_norm):
            continue
        if inline:
            return field, inline
        if norm == key_norm:
            return field, ""
        # 标签后还粘着内容：带数字视为「标签 + 值」，否则当英文别名（如 Invoice No.）
        tail = norm[len(key_norm):]
        if re.search(r"\d", tail):
            original = str(text).strip()
            m = re.match(re.escape(key_raw), original, re.IGNORECASE)
            if m:
                rest = original[m.end():].strip(" :：")
                if rest:
                    return field, rest
        return field, ""
    return None, ""


def _match_item_header(raw) -> str | None:
    """判断一个单元格是不是明细表列名。"""
    norm = _compact(raw)
    if not norm or len(norm) > 24:
        return None
    for key_norm, field, _ in _ITEM_INDEX:
        if norm == key_norm or norm.startswith(key_norm):
            return field
    return None


def _cell_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _is_formula(value) -> bool:
    """公式单元格（由 ``data_only=False`` 的那次加载识别）。"""
    return isinstance(value, str) and value.strip().startswith("=")


def _to_number(value, integer: bool = False):
    """数值清洗：千分位、货币符号、全角数字；解析不了返回 None。"""
    if isinstance(value, bool) or value is None or _is_formula(value):
        return None
    if isinstance(value, (_dt.datetime, _dt.date)):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = unicodedata.normalize("NFKC", str(value))
        text = text.replace(",", "").replace("，", "")
        m = re.search(r"[-+]?\d+(?:\.\d+)?", text)
        if not m:
            return None
        number = float(m.group())
    if integer and abs(number - round(number)) < 1e-9:
        return int(round(number))
    return round(number, 6)


def _coerce(field: str, value):
    """按字段类型转换单元格值；日期兼容 Excel 序列号与字符串。"""
    if field == "wood_packaging":
        if isinstance(value, bool):
            return "是" if value else "否"
        return _cell_text(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.strftime("%Y-%m-%d")
    if field in DATE_FIELDS:
        if isinstance(value, (int, float)) and 20000 <= value <= 80000:
            try:
                return (_dt.date(1899, 12, 30) + _dt.timedelta(days=int(value))).isoformat()
            except ValueError:
                return _cell_text(value)
        return _cell_text(value)
    if field in NUM_FIELDS:
        number = _to_number(value, integer=field in INT_FIELDS)
        if number is not None:
            return number
        # 公式读不到值：不猜数字，交给缺失/低置信处理
        return None if _is_formula(value) else _cell_text(value)
    return _cell_text(value)


def _build_grid(ws) -> dict[tuple[int, int], object]:
    """展开合并单元格：整个区域都填左上角的值（与 Excel 显示一致）。"""
    grid: dict[tuple[int, int], object] = {}
    for row in ws.iter_rows():
        for cell in row:
            if cell.value is not None:
                grid[(cell.row, cell.column)] = cell.value
    merged = getattr(ws, "merged_cells", None)
    if merged is not None:
        for rng in list(merged.ranges):
            top = grid.get((rng.min_row, rng.min_col))
            if top is None:
                continue
            for r in range(rng.min_row, rng.max_row + 1):
                for c in range(rng.min_col, rng.max_col + 1):
                    grid.setdefault((r, c), top)
    return grid


def _detect_doc_type(ws, grid: dict) -> str | None:
    """标题关键词打分 + 标签命中数，取最高分；都不像则返回 None。"""
    title_cells = {str(ws.title)}
    for r in range(1, min(ws.max_row, TITLE_ROWS) + 1):
        for c in range(1, ws.max_column + 1):
            value = grid.get((r, c))
            if isinstance(value, str):
                title_cells.add(value)
    title = _compact(" ".join(title_cells))

    label_hits = {}
    for dtype in LABELS:
        hits = set()
        for value in grid.values():
            if not isinstance(value, str):
                continue
            field, _ = _match_label(dtype, value)
            if field:
                hits.add(field)
        label_hits[dtype] = len(hits)

    scores: dict[str, tuple[int, int, int]] = {}
    for priority, (dtype, markers) in enumerate(TITLE_MARKERS):
        title_hits = sum(1 for marker in markers if _compact(marker) in title)
        scores[dtype] = (title_hits, label_hits.get(dtype, 0), -priority)

    best = max(scores, key=lambda d: scores[d])
    title_hits, hits, _ = scores[best]
    if title_hits == 0 and hits < 3:
        return None
    return best


def _value_right(grid: dict, row: int, col: int, label_raw, dtype: str,
                 max_col: int):
    """在标签右侧找第一个非空值；碰到下一个标签说明本标签没有值。"""
    label_text = str(label_raw).strip()
    for c in range(col + 1, max_col + 1):
        value = grid.get((row, c))
        if value is None:
            continue
        text = str(value).strip()
        if not text or text == label_text:
            continue
        if _match_label(dtype, text)[0]:
            return None
        return value
    return None


def _read_kv(dtype: str, grid: dict, skip_rows: set[int], max_col: int) -> dict:
    fields: dict = {}
    for (row, col), value in sorted(grid.items()):
        if row in skip_rows or not isinstance(value, str):
            continue
        field, inline = _match_label(dtype, value)
        if not field or field in fields:
            continue
        raw = inline if inline else _value_right(grid, row, col, value, dtype, max_col)
        if raw is None or str(raw).strip() == "":
            continue
        coerced = _coerce(field, raw)
        if coerced is None or (isinstance(coerced, str) and not coerced.strip()):
            continue
        fields[field] = coerced
    return fields


def _find_item_header(grid: dict, max_row: int, max_col: int):
    """找明细表表头行；要求至少 3 列且含品名，避免把单头行误判成表格。"""
    for r in range(1, max_row + 1):
        mapping: dict[str, int] = {}
        for c in range(1, max_col + 1):
            value = grid.get((r, c))
            if not isinstance(value, str):
                continue
            field = _match_item_header(value)
            if field and field not in mapping:
                mapping[field] = c
        if (len(mapping) >= 3 and "name" in mapping
                and ("amount" in mapping
                     or ("qty" in mapping and "unit_price" in mapping))):
            return r, mapping
    return None


def _is_stop_row(grid: dict, row: int, max_col: int, name_col: int | None,
                 dtype: str) -> bool:
    """汇总/附注行：命中结束标志，或本身就是单头标签（如「发票总额」）。"""
    for c in range(1, max_col + 1):
        value = grid.get((row, c))
        text = _compact(value)
        if not text:
            continue
        if _match_label(dtype, value)[0]:
            return True
        if c != name_col and any(text.startswith(_compact(marker))
                                 for marker in STOP_MARKERS):
            return True
    return False


def _parse_elements(value) -> dict:
    elements: dict = {}
    for pair in re.split(r"[|;；]", _cell_text(value)):
        if "=" in pair:
            key, val = pair.split("=", 1)
            if key.strip():
                elements[key.strip()] = val.strip()
    return elements


def _read_items(grid: dict, header_row: int, mapping: dict[str, int],
                max_row: int, max_col: int, dtype: str):
    """从表头下一行读到合计/折扣/佣金/特许权/空白行，返回 (items, 行集合, 校验问题)。"""
    items: list[dict] = []
    block_rows = {header_row}
    checks: list[str] = []
    name_col = mapping.get("name")
    for r in range(header_row + 1, max_row + 1):
        values = {field: _cell_text(grid.get((r, c))) for field, c in mapping.items()}
        if not any(values.values()):
            continue
        if _is_stop_row(grid, r, max_col, name_col, dtype):
            break
        name = values.get("name", "").strip()
        if not name:
            break

        item: dict = {"name": name}
        if values.get("name_en"):
            item["name_en"] = values["name_en"].strip()
        hs = re.sub(r"\s+", "", values.get("hs_code", ""))
        if hs:
            item["hs_code"] = hs
        for field in ("qty", "unit", "unit_price", "amount"):
            raw = values.get(field, "")
            if raw == "":
                continue
            if field in NUM_FIELDS:
                number = _to_number(raw, integer=(field == "qty"))
                # 解析不了就保留原文（与 pdf_text 的口径一致），不静默丢字段
                item[field] = number if number is not None else raw
            else:
                item[field] = raw
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
        if elements:
            item["elements"] = elements

        qty, price, amount = (item.get("qty"), item.get("unit_price"), item.get("amount"))
        if qty is not None and price is not None and amount is not None:
            expected = float(qty) * float(price)
            if abs(expected - float(amount)) > max(0.01, abs(expected) * 0.01):
                checks.append(
                    f"items[{len(items)}] 数量×单价={expected:.2f} ≠ 金额={amount}")
        items.append(item)
        block_rows.add(r)
        if len(items) >= MAX_ITEMS:
            break
    return items, block_rows, checks


def extract_sheet(ws, path="", formula_cells=frozenset()) -> dict:
    """抽取一个 sheet；返回与 ``pdf_text.extract`` 同形的 dict（多一个 sheet 名）。

    ``formula_cells`` 是 ``(row, col)`` 集合（来自不做值缓存的工作簿）；
    这些位置在 ``data_only=True`` 下读不到值，计入 ``checks`` 降置信。
    """
    grid = _build_grid(ws)
    dtype = _detect_doc_type(ws, grid)
    result = {
        "path": str(path),
        "sheet": ws.title,
        "doc_type": dtype,
        "fields": {},
        "items": 0,
        "missing": [],
        "confidence": 0.0,
        "needs_human": True,
        "checks": [],
        "text_chars": sum(len(str(v)) for v in grid.values()),
    }
    if dtype is None:
        return result

    header = _find_item_header(grid, ws.max_row, ws.max_column)
    items: list[dict] = []
    block_rows: set[int] = set()
    checks: list[str] = []
    if header:
        header_row, mapping = header
        items, block_rows, checks = _read_items(
            grid, header_row, mapping, ws.max_row, ws.max_column, dtype)

    fields = _read_kv(dtype, grid, block_rows, ws.max_column)
    if items:
        fields["items"] = items
    fields = _postprocess(dtype, fields)

    # 公式单元格没有缓存值时 data_only=True 读不到，不能静默当"有值"
    empty_formulas = sum(1 for (row, col) in formula_cells
                         if grid.get((row, col)) in (None, ""))
    if empty_formulas:
        checks = checks + [f"{empty_formulas} 个公式单元格无缓存值"]

    required = REQUIRED[dtype]
    missing = [field for field in required if not fields.get(field)]
    base = 1 - len(missing) / max(len(required), 1)
    confidence = max(0.0, round(base - 0.1 * len(checks), 3))
    result.update({
        "fields": fields,
        "items": len(items),
        "missing": missing,
        "confidence": confidence,
        "needs_human": bool(missing or checks),
        "checks": checks,
    })
    return result


def extract_workbook(path) -> list[dict]:
    """逐 sheet 抽取（含隐藏 sheet），返回每个 sheet 一条结果。"""
    wb = _load_workbook(path, data_only=True)
    raw = _load_workbook(path, data_only=False)
    try:
        results = []
        for ws in wb.worksheets:
            formula_cells = frozenset(
                (cell.row, cell.column)
                for row in raw[ws.title].iter_rows() for cell in row
                if _is_formula(cell.value))
            results.append(extract_sheet(ws, path, formula_cells))
        return results
    finally:
        for book in (wb, raw):
            try:
                book.close()
            except Exception:
                pass


def extract(path) -> dict:
    """抽取一个工作簿：返回第一份识别出的单证（附 ``sheets`` 明细）。"""
    results = extract_workbook(path)
    primary = next((r for r in results if r["doc_type"]), None)
    if primary is None:
        return {
            "path": str(path), "doc_type": None, "fields": {}, "items": 0,
            "missing": [], "confidence": 0.0, "needs_human": True,
            "checks": [], "sheets": results, "text_chars": 0,
        }
    out = dict(primary)
    out["sheets"] = results
    return out


def _load_workbook(path, data_only: bool = True):
    try:
        import openpyxl  # 可选依赖
    except ImportError as exc:  # pragma: no cover - 取决于环境
        raise ImportError("需要 openpyxl（pip install openpyxl）") from exc
    return openpyxl.load_workbook(str(path), data_only=data_only)


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("用法: python -m src.ingest.excel <文件.xlsx> [<文件> ...]")
        return 2
    for item in argv:
        try:
            results = extract_workbook(item)
        except ImportError as exc:
            print(json.dumps({"path": item, "error": str(exc)}, ensure_ascii=False))
            continue
        except Exception as exc:  # noqa: BLE001 - CLI 只负责打印
            print(json.dumps({"path": item, "error": f"{type(exc).__name__}: {exc}"},
                             ensure_ascii=False))
            continue
        print(json.dumps({"path": str(Path(item)), "sheets": results},
                         ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
