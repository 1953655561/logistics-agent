"""L1 完整性与格式（10 条，确定性规则）。"""
from __future__ import annotations

from datetime import date

from ..common import get, money, num, rel_diff, norm_unit
from ..domain.codes import COUNTRIES, CURRENCIES, PALLET_TYPES
from ..issue import Issue, RuleResult
from ..registry import rule

L = "L1"

REQUIRED_HEADER = [
    ("declaration", "consignee", "境内收货人"),
    ("declaration", "transport_mode", "运输方式"),
    ("declaration", "trade_mode", "贸易方式"),
    ("declaration", "exemption_nature", "征免性质"),
    ("declaration", "origin_country", "启运国"),
    ("declaration", "loading_port", "装货港"),
    ("declaration", "destination", "境内目的地"),
]


def _d(s):
    try:
        return date.fromisoformat(str(s))
    except Exception:
        return None


@rule("L1-01", L, "表头必填项", "报关单填制规范")
def check_required_header(ctx):
    issues = []
    for doc, path, label in REQUIRED_HEADER:
        if not get(ctx.get(doc, {}), path):
            issues.append(Issue("L1-01", f"{doc}.{path}", "high",
                                f"必填项缺失：{label}", suggestion="补填后重新审核"))
    return RuleResult("L1-01", L, "表头必填项", "FIX" if issues else "PASS",
                      issues, "报关单填制规范")


@rule("L1-02", L, "日期逻辑", "报关单填制规范")
def check_dates(ctx):
    issues, hard = [], False
    bl_d = _d(get(ctx, "bl.date"))
    dec_d = _d(get(ctx, "declaration.declare_date"))
    inv_d = _d(get(ctx, "invoice.date"))
    if bl_d and dec_d and bl_d > dec_d:
        hard = True
        issues.append(Issue("L1-02", "declaration.declare_date", "high",
                            "申报日期早于提单日期", {"bl_date": str(bl_d), "declare_date": str(dec_d)},
                            "核对提单日期或申报日期"))
    if inv_d and bl_d and inv_d > bl_d:
        issues.append(Issue("L1-02", "invoice.date", "low",
                            "发票日期晚于提单日期（预开票/补开票场景可解释）",
                            {"invoice_date": str(inv_d), "bl_date": str(bl_d)},
                            "如为补开票，留存说明"))
    return RuleResult("L1-02", L, "日期逻辑", "FIX" if hard else "PASS", issues,
                      "报关单填制规范")


@rule("L1-03", L, "币制合法", "报关单填制规范")
def check_currency(ctx):
    issues = []
    cur = str(get(ctx, "declaration.currency", "")).upper()
    if cur and cur not in CURRENCIES:
        issues.append(Issue("L1-03", "declaration.currency", "high",
                            f"币制代码非法：{cur}", suggestion="改用 ISO 4217 代码"))
    contract_cur = str(get(ctx, "contract.currency", "")).upper()
    inv_cur = str(get(ctx, "invoice.currency", "")).upper()
    if contract_cur and inv_cur and contract_cur != inv_cur:
        issues.append(Issue("L1-03", "invoice.currency", "mid",
                            f"发票币制 {inv_cur} 与合同币制 {contract_cur} 不一致"))
    return RuleResult("L1-03", L, "币制合法", "FIX" if issues else "PASS",
                      issues, "报关单填制规范")


@rule("L1-04", L, "计量单位", "税则")
def check_units(ctx):
    issues = []
    for i, item in enumerate(get(ctx, "declaration.items", []) or []):
        if not item.get("legal_unit1"):
            issues.append(Issue("L1-04", f"declaration.items[{i}].legal_unit1", "high",
                                "缺法定第一计量单位", suggestion="按税则补第一计量单位"))
        if not norm_unit(item.get("unit")):
            issues.append(Issue("L1-04", f"declaration.items[{i}].unit", "mid",
                                "成交计量单位缺失"))
    return RuleResult("L1-04", L, "计量单位", "FIX" if issues else "PASS", issues, "税则")


@rule("L1-05", L, "商品项数", "内审 SOP")
def check_item_count(ctx):
    items = get(ctx, "declaration.items", []) or []
    if len(items) > 50:
        return RuleResult("L1-05", L, "商品项数", "REVIEW",
                          [Issue("L1-05", "declaration.items", "mid",
                                 f"商品项数 {len(items)} 超过 50 项", suggestion="拆单申报")],
                          "内审 SOP")
    return RuleResult("L1-05", L, "商品项数", "PASS", [], "内审 SOP")


@rule("L1-06", L, "单证齐套", "内审 SOP")
def check_docset(ctx):
    required = [("contract", "合同"), ("invoice", "商业发票"),
                ("packing_list", "装箱单"), ("bl", "提单")]
    missing = [label for doc, label in required if not ctx.get(doc)]
    if missing:
        return RuleResult("L1-06", L, "单证齐套", "REVIEW",
                          [Issue("L1-06", "docs", "high", "随附单证缺失：" + "、".join(missing))],
                          "内审 SOP")
    return RuleResult("L1-06", L, "单证齐套", "PASS", [], "内审 SOP")


@rule("L1-07", L, "金额勾稽", "内审 SOP")
def check_amount_math(ctx):
    issues = []
    inv = ctx.get("invoice", {})
    items = inv.get("items", []) or []
    for i, it in enumerate(items):
        expect = num(it.get("qty")) * num(it.get("unit_price"))
        if expect and rel_diff(expect, num(it.get("amount"))) > 0.01:
            issues.append(Issue("L1-07", f"invoice.items[{i}].amount", "high",
                                "单价×数量与金额不符",
                                {"calc": money(expect), "declared": money(it.get("amount"))},
                                "核对单价、数量或金额"))
    subtotal = sum(num(it.get("amount")) for it in items)
    net_total = subtotal - num(inv.get("discount")) - num(inv.get("commission"))
    if items and rel_diff(net_total, num(inv.get("total_amount"))) > 0.01:
        issues.append(Issue("L1-07", "invoice.total_amount", "high",
                            "扣折扣/佣金后与发票总额不符",
                            {"calc": money(net_total), "declared": money(inv.get("total_amount"))},
                            "按 (小计-折扣-佣金) 重算"))
    return RuleResult("L1-07", L, "金额勾稽", "FIX" if issues else "PASS", issues, "内审 SOP")


@rule("L1-08", L, "毛净重逻辑", "常识校验")
def check_weight_logic(ctx):
    pk = ctx.get("packing_list", {})
    gross, net = num(pk.get("gross_weight")), num(pk.get("net_weight"))
    if gross and net and gross < net:
        return RuleResult("L1-08", L, "毛净重逻辑", "FIX",
                          [Issue("L1-08", "packing_list.gross_weight", "high",
                                 "毛重小于净重", {"gross": gross, "net": net})],
                          "常识校验")
    return RuleResult("L1-08", L, "毛净重逻辑", "PASS", [], "常识校验")


@rule("L1-09", L, "件数包装", "内审 SOP")
def check_package_count(ctx):
    pk = ctx.get("packing_list", {})
    ptype = str(pk.get("package_type", "")).strip().lower()
    if ptype in {p.lower() for p in PALLET_TYPES} and num(pk.get("packages")) <= 0:
        return RuleResult("L1-09", L, "件数包装", "FIX",
                          [Issue("L1-09", "packing_list.packages", "mid",
                                 "包装种类为托盘但未填托盘数", suggestion="补托盘数")],
                          "内审 SOP")
    return RuleResult("L1-09", L, "件数包装", "PASS", [], "内审 SOP")


@rule("L1-10", L, "字段格式", "报关单填制规范")
def check_formats(ctx):
    issues = []
    for i, item in enumerate(get(ctx, "declaration.items", []) or []):
        hs = str(item.get("hs_code", ""))
        if not (len(hs) == 10 and hs.isdigit()):
            issues.append(Issue("L1-10", f"declaration.items[{i}].hs_code", "high",
                                f"商品编号格式非法：{hs!r}", suggestion="应为 10 位数字"))
    # 只校国别字段；境内目的地是国内地区，不做国别校验
    for doc, path in [("declaration", "origin_country")]:
        code = str(get(ctx, f"{doc}.{path}", "")).upper()
        if code and code not in COUNTRIES:
            issues.append(Issue("L1-10", f"{doc}.{path}", "mid",
                                f"国别代码不在表内：{code}"))
    return RuleResult("L1-10", L, "字段格式", "FIX" if issues else "PASS", issues,
                      "报关单填制规范")
