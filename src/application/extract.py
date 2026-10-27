"""抽取 POC：把「一段发票/邮件文本」变成可被规则引擎消费的结构化单证。

定位要说清：**这不是 OCR**。我们只处理文本（邮件正文、粘贴的发票文字），
扫描件识别不在本仓库范围内（没有 OCR 依赖）。目标是把"非结构化 → 结构化"这一段
真正做出来，让"为什么需要 Agent"有实物：抽取有置信度，低置信字段转人工。

离线可跑：默认走确定性正则 + 交叉校验（qty×price≈amount 才给高置信）；
接了真模型时可用 LLM 兜底补字段（`method` 会标 llm）。
"""
from __future__ import annotations

import re

CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
          "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

PATTERNS = {
    "invoice_no": r"(?:发票号|发票编号|Invoice\s*No\.?|INV)\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9\-_/]{2,})",
    "contract_no": r"(?:合同号|合同编号|Contract\s*No\.?)\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9\-_/]{2,})",
    "date": r"(?:发票日期|开票日期|Date)\s*[:：]?\s*(\d{4}-\d{1,2}-\d{1,2})",
    "seller": r"(?:供应商|卖方|Seller|Shipper)\s*[:：]\s*(.+?)\s*$",
    "buyer": r"(?:买方|购买方|Buyer|Consignee)\s*[:：]\s*(.+?)\s*$",
    "currency": r"(?:币制|币种|Currency)\s*[:：]?\s*([A-Za-z]{2,3})",
    "total_amount": r"(?:总价|总额|合计|Total)\s*[:：]?\s*([0-9][0-9,]*\.?[0-9]*)",
}

ITEM_RE = re.compile(
    r"(?:商品|品名|货物|Item)\s*[:：]?\s*(?P<name>[^\s，,；;]+)\s+"
    r"(?P<qty>\d+(?:\.\d+)?)\s*(?P<unit>个|件|套|千克|kg|pcs|箱)?\s*"
    r"(?:单价\s*)?(?P<price>\d+(?:\.\d+)?)?\s*(?:金额\s*)?(?P<amount>\d+(?:\.\d+)?)?")


def _num(text: str) -> float | None:
    try:
        return float(str(text).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _find(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
    return m.group(1).strip() if m else None


def extract_invoice(text: str, llm=None) -> dict:
    """返回 {docs, confidence, needs_human, method, missing_docs}。"""
    text = str(text or "").strip()
    if not text:
        raise ValueError("文本为空，无法抽取")
    if len(text) > 20000:
        raise ValueError("文本过长（>20000 字符），请分段抽取")

    conf: dict[str, float] = {}
    invoice: dict = {}
    for key, pattern in PATTERNS.items():
        value = _find(pattern, text)
        if value is None:
            conf[f"invoice.{key}"] = 0.0
            continue
        if key in ("seller", "buyer"):
            value = value.strip(" ：:，,。")
        if key == "currency":
            value = value.upper()
        if key in ("total_amount",):
            num = _num(value)
            value = num if num is not None else value
        invoice[key] = value
        conf[f"invoice.{key}"] = 0.9

    items = []
    for i, m in enumerate(ITEM_RE.finditer(text)):
        qty, price = _num(m.group("qty")), _num(m.group("price"))
        amount = _num(m.group("amount"))
        item = {"name": m.group("name"), "qty": qty, "unit": m.group("unit") or "个"}
        if price is not None:
            item["unit_price"] = price
        if amount is not None:
            item["amount"] = amount
        elif qty is not None and price is not None:
            item["amount"] = round(qty * price, 2)
            conf[f"invoice.items[{i}].amount"] = 0.6
        # 交叉校验：数量×单价≈金额 才敢给高置信
        if qty is not None and price is not None and item.get("amount") is not None:
            ok = abs(qty * price - item["amount"]) <= max(0.01, abs(qty * price) * 0.01)
            conf[f"invoice.items[{i}].amount"] = 1.0 if ok else 0.5
        items.append(item)
    if items:
        invoice["items"] = items

    if invoice.get("contract_no") or invoice.get("invoice_no"):
        if "total_amount" not in invoice and items:
            invoice["total_amount"] = round(
                sum(i.get("amount") or 0 for i in items), 2)
            conf["invoice.total_amount"] = 0.6

    docs = {"invoice": invoice}
    if invoice.get("contract_no"):
        docs["contract"] = {"contract_no": invoice["contract_no"],
                            "currency": invoice.get("currency"),
                            "total_amount": invoice.get("total_amount")}

    # 缺失的必备单证：交给规则引擎的 L1-06 报 REVIEW，这里先标出来
    missing_docs = [d for d in ("contract", "invoice", "packing_list", "bl", "declaration")
                    if d not in docs]
    needs_human = sorted(k for k, v in conf.items() if v < 0.9)
    if missing_docs:
        needs_human.extend(f"docs.{d}" for d in missing_docs)

    method = "rules"
    if not docs["invoice"].get("items") and llm is not None and \
            getattr(llm, "name", "") != "mock":
        docs, conf, method = _llm_fill(text, docs, conf, llm)

    return {"docs": docs, "confidence": conf, "needs_human": needs_human,
            "missing_docs": missing_docs, "method": method}


LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "invoice_no": {"type": "string"},
        "contract_no": {"type": "string"},
        "currency": {"type": "string"},
        "total_amount": {"type": "number"},
        "items": {"type": "array", "items": {"type": "object"}},
    },
    "required": ["items"],
    "additionalProperties": True,
}


def _llm_fill(text: str, docs: dict, conf: dict, llm) -> tuple[dict, dict, str]:
    """文本正则抽不到商品行时，用模型补一次（必须自行校验数量×单价）。"""
    try:
        out = llm.complete([
            {"role": "system", "content":
             "从发票文本抽取字段，只输出 JSON。金额、数量必须是文本里出现过的数字。"},
            {"role": "user", "content": f"【数据开始】{text[:4000]}【数据结束】"},
        ], schema=LLM_SCHEMA, max_tokens=600)
        data = (out or {}).get("data") or (out or {})
        inv = docs.setdefault("invoice", {})
        for key in ("invoice_no", "contract_no", "currency", "total_amount"):
            if not inv.get(key) and data.get(key) not in (None, ""):
                inv[key] = data[key]
                conf[f"invoice.{key}"] = 0.7          # 模型给的，低于正则
        if data.get("items"):
            inv["items"] = data["items"]
            conf["invoice.items"] = 0.7
        return docs, conf, "llm"
    except Exception:
        return docs, conf, "rules"
