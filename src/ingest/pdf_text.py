"""文字层 PDF → 五单字段。

针对本项目合成单证的版式：每行一个「标签 值」，明细表一行一条。
真实单证版式差异大，这里的标签表就是需要按模板扩展的地方。

依赖：``pypdf``（可选，未安装时导入会抛 ImportError，
由上层 ``src.ingest.detect`` 走扫描件/OCR 兜底）。
"""
from __future__ import annotations

import re
from pathlib import Path

# 文档类型 → 字段标签映射（标签要按版式扩展）
LABELS: dict[str, dict[str, str]] = {
    "contract": {
        "合同号": "contract_no",
        "卖方": "seller",
        "买方": "buyer",
        "日期": "date",
        "币制": "currency",
        "成交方式": "incoterm",
        "合同总额": "total_amount",
        "条款": "terms",
        "付款方式": "payment",
    },
    "invoice": {
        "发票号": "invoice_no",
        "合同号": "contract_no",
        "发票日期": "date",
        "卖方": "seller",
        "买方": "buyer",
        "币制": "currency",
        "成交方式": "incoterm",
        "折扣": "discount",
        "佣金": "commission",
        "特许权使用费": "royalty",
        "发票总额": "total_amount",
    },
    "packing_list": {
        "装箱单号": "pl_no",
        "日期": "date",
        "件数": "packages",
        "包装种类": "package_type",
        "毛重": "gross_weight",
        "净重": "net_weight",
        "体积": "volume",
        "唛头": "marks",
        "木包装": "wood_packaging",
    },
    "bl": {
        "提单号": "bl_no",
        "日期": "date",
        "到港日": "arrival_date",
        "船名": "vessel",
        "航次": "voyage",
        "起运港": "pol",
        "目的港": "pod",
        "发货人": "shipper",
        "收货人": "consignee",
        "通知人": "notify",
        "件数": "packages",
        "毛重": "gross_weight",
        "体积": "volume",
    },
    "declaration": {
        "报关单号": "decl_no",
        "申报日期": "declare_date",
        "收发货人": "consignee",
        "运输方式": "transport_mode",
        "贸易方式": "trade_mode",
        "征免性质": "exemption_nature",
        "启运国": "origin_country",
        "装货港": "loading_port",
        "境内目的地": "destination",
        "成交方式": "incoterm",
        "币制": "currency",
        "运费": "freight",
        "保费": "insurance",
        "合同号": "contract_no",
        "提单号": "bl_no",
        "件数": "packages",
        "毛重": "gross_weight",
        "净重": "net_weight",
        "总价": "total_amount",
        "许可证号": "license_no",
        "证书号": "cert_no",
    },
}

FLOAT_FIELDS = {
    "total_amount", "discount", "commission", "royalty", "freight",
    "insurance", "gross_weight", "net_weight", "volume", "qty",
    "unit_price", "amount",
}
INT_FIELDS = {"packages", "qty", "qty_legal1"}
REQUIRED = {
    "contract": ["contract_no", "seller", "buyer", "total_amount"],
    "invoice": ["invoice_no", "total_amount", "items"],
    "packing_list": ["pl_no", "packages", "gross_weight"],
    "bl": ["bl_no", "date", "consignee"],
    "declaration": ["decl_no", "declare_date", "consignee", "items"],
}

# 明细行：序号 品名 HS编码 数量 单位 单价 金额 法定单位(个/千克) 申报要素
ITEM_RE = re.compile(
    r"^\s*(\d+)\s+(\S+)\s+(\d{10})\s+([\d.]+)\s+(\S+)\s+([\d.]+)\s+([\d.]+)\s+"
    r"(\S+?)/(\S+)\s+(\S+)\s*$"
)


def detect_doc_type(text: str) -> str | None:
    """按标题关键词判断这是哪类单证；报关单优先，避免被"合同号/提单号"误判。"""
    compact = re.sub(r"\s+", "", text).upper()
    for dtype, marker in (
        ("declaration", "报关单"),
        ("invoice", "发票"),
        ("packing_list", "装箱单"),
        ("bl", "提单"),
        ("contract", "合同"),
    ):
        if marker in compact:
            return dtype
    if "CONTRACT" in compact:
        return "contract"
    return None


def _read_pdf_text(path) -> str:
    from pypdf import PdfReader  # 可选依赖

    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _num(value: str):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _convert(field: str, value: str):
    if field in INT_FIELDS:
        n = _num(value)
        if n is None:
            return value
        return int(n) if float(n).is_integer() else n
    if field in FLOAT_FIELDS:
        n = _num(value)
        return n if n is not None else value
    return value.strip()


def _parse_items(text: str) -> list[dict]:
    items = []
    for line in text.splitlines():
        m = ITEM_RE.match(line.strip())
        if not m:
            continue
        idx, name, hs, qty, unit, price, amount, l1, l2, el = m.groups()
        elements = {}
        for pair in el.split("|"):
            if "=" in pair:
                k, v = pair.split("=", 1)
                elements[k.strip()] = v.strip()
        items.append({
            "name": name,
            "hs_code": hs,
            "qty": _convert("qty", qty),
            "unit": unit,
            "unit_price": _convert("unit_price", price),
            "amount": _convert("amount", amount),
            "origin": "CN",
            "legal_unit1": l1,
            "legal_unit2": l2,
            "elements": elements,
        })
    return items


def _postprocess(dtype: str, fields: dict) -> dict:
    if dtype == "packing_list":
        raw = str(fields.get("marks", ""))
        if "/" in raw:
            port, text = raw.split("/", 1)
            fields["marks"] = {"port": port.strip(), "text": text.strip()}
        if "wood_packaging" in fields:
            fields["wood_packaging"] = str(fields["wood_packaging"]).startswith("是")
    if dtype == "declaration":
        for key in ("license_no", "cert_no"):
            if str(fields.get(key, "")).strip() in ("无", "-", ""):
                fields[key] = ""
    return fields


def parse_document(text: str, source: str = "") -> dict:
    """文本 → 五单字段。

    文字层 PDF 与 OCR 共用这一层：OCR 只要把识别结果拼成「一行一个标签」的文本，
    就能拿到与 PDF 完全相同的字段名与结构，审核引擎零改动。
    """
    text = str(text or "")
    p = Path(source) if source else None
    dtype = detect_doc_type(text)
    if dtype is None:
        return {"path": str(p) if p else "", "doc_type": None, "fields": {},
                "items": 0, "missing": [], "confidence": 0.0, "needs_human": True,
                "text_chars": len(text)}

    fields: dict = {}
    labels = LABELS[dtype]
    # 长标签优先，避免「日期」抢先匹配「申报日期」
    for line in text.splitlines():
        line = line.strip()
        for lab in sorted(labels, key=len, reverse=True):
            if line.startswith(lab):
                value = line[len(lab):].strip(" :：")
                if value:
                    fields[labels[lab]] = _convert(labels[lab], value)
                break

    items = _parse_items(text)
    if items and dtype in ("invoice", "packing_list", "bl", "declaration"):
        fields["items"] = items

    fields = _postprocess(dtype, fields)
    missing = [f for f in REQUIRED[dtype] if not fields.get(f)]
    confidence = round(1 - len(missing) / max(len(REQUIRED[dtype]), 1), 3)
    return {
        "path": str(p) if p else "",
        "doc_type": dtype,
        "fields": fields,
        "items": len(items),
        "missing": missing,
        "confidence": confidence,
        "needs_human": bool(missing),
        "text_chars": len(text),
    }


def extract(path) -> dict:
    """抽取一份文字层 PDF，返回 {doc_type, fields, missing, confidence, needs_human}。"""
    p = Path(path)
    return parse_document(_read_pdf_text(p), source=str(p))
