"""L1 完整性与格式（10 条，确定性规则）。"""
from __future__ import annotations

from ..common import (BULK_QTY_TOL, get, money, num, parse_date, rel_diff,
                      unit_ok)
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

# 需要做"格式可解析"校验的日期字段：缺失不算错，有值但解析不了才报
DATE_FIELDS = [
    ("contract", "date", "合同日期"),
    ("invoice", "date", "发票日期"),
    ("packing_list", "date", "装箱单日期"),
    ("bl", "date", "提单日期"),
    ("bl", "arrival_date", "提单到港日"),
    ("declaration", "declare_date", "申报日期"),
]

# 需要做字符集校验的单号字段：只拦非 ASCII / 含空白，防的是粘贴污染
NUMBER_FIELDS = [
    ("contract", "contract_no", "合同号"),
    ("invoice", "invoice_no", "发票号"),
    ("packing_list", "pl_no", "装箱单号"),
    ("bl", "bl_no", "提单号"),
    ("declaration", "decl_no", "报关单号"),
    ("declaration", "cert_no", "证件号"),
]


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
    # 先查"有值但解析不了"：脏日期不能静默跳过，否则后面的时序与申报期限校验全部失效
    for doc, path, label in DATE_FIELDS:
        raw = get(ctx, f"{doc}.{path}")
        if raw is None or str(raw).strip() == "":
            continue
        if parse_date(raw) is None:
            issues.append(Issue("L1-02", f"{doc}.{path}", "mid",
                                f"{label}格式非法（应为 YYYY-MM-DD）：{raw}",
                                suggestion="按 YYYY-MM-DD 改正后重报"))
    bl_d = parse_date(get(ctx, "bl.date"))
    dec_d = parse_date(get(ctx, "declaration.declare_date"))
    inv_d = parse_date(get(ctx, "invoice.date"))
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
    return RuleResult("L1-02", L, "日期逻辑", "FIX" if (hard or any(
        i.severity != "low" for i in issues)) else "PASS", issues, "报关单填制规范")


@rule("L1-03", L, "币制合法", "报关单填制规范")
def check_currency(ctx):
    issues = []
    for doc, label, sev in (("declaration", "报关单", "high"),
                            ("contract", "合同", "mid"),
                            ("invoice", "发票", "mid")):
        cur = str(get(ctx, f"{doc}.currency", "")).strip().upper()
        if cur and cur not in CURRENCIES:
            issues.append(Issue("L1-03", f"{doc}.currency", sev,
                                f"{label}币制代码非法：{cur}",
                                suggestion="改用 ISO 4217 代码"))
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
    for doc, label in (("declaration", "报关单"), ("invoice", "发票")):
        for i, item in enumerate(get(ctx, f"{doc}.items", []) or []):
            if doc == "declaration":
                if not item.get("legal_unit1"):
                    issues.append(Issue("L1-04", f"{doc}.items[{i}].legal_unit1", "high",
                                        "缺法定第一计量单位", suggestion="按税则补第一计量单位"))
                if not item.get("legal_unit2"):
                    issues.append(Issue("L1-04", f"{doc}.items[{i}].legal_unit2", "high",
                                        "缺法定第二计量单位", suggestion="按税则补第二计量单位"))
            for key, klabel in (("unit", "成交计量单位"), ("legal_unit2", "法定第二计量单位")):
                value = item.get(key)
                if value not in (None, "") and not unit_ok(value):
                    issues.append(Issue("L1-04", f"{doc}.items[{i}].{key}", "mid",
                                        f"{label}{klabel}非法：{value}",
                                        suggestion="改用税则/单证标准单位"))
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
    # 报关单行级勾稽：成交价与申报金额也要自洽（v1.6 补齐，原来只勾稽发票）
    # 散装货按溢短装放宽到 3%，与 L2-12 的散装数量口径保持一致
    line_tol = BULK_QTY_TOL if inv.get("bulk") else 0.01
    for i, it in enumerate(get(ctx, "declaration.items", []) or []):
        expect = num(it.get("qty")) * num(it.get("unit_price"))
        if expect and rel_diff(expect, num(it.get("amount"))) > line_tol:
            issues.append(Issue("L1-07", f"declaration.items[{i}].amount", "high",
                                "报关单单价×数量与金额不符",
                                {"calc": money(expect), "declared": money(it.get("amount")),
                                 "tol": line_tol},
                                "核对单价、数量或金额"))
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
    # 商品编号：四单都可能被引用，任何一单写错都会带偏归类与勾稽
    for doc, label in (("invoice", "发票"), ("packing_list", "装箱单"),
                       ("bl", "提单"), ("declaration", "报关单")):
        for i, item in enumerate(get(ctx, f"{doc}.items", []) or []):
            hs = str(item.get("hs_code", ""))
            if not (len(hs) == 10 and hs.isdigit()):
                issues.append(Issue("L1-10", f"{doc}.items[{i}].hs_code", "high",
                                    f"{label}商品编号格式非法：{hs!r}",
                                    suggestion="应为 10 位数字"))
    # 只校国别字段；境内目的地是国内地区，不做国别校验
    for doc, path in [("declaration", "origin_country")]:
        code = str(get(ctx, f"{doc}.{path}", "")).upper()
        if code and code not in COUNTRIES:
            issues.append(Issue("L1-10", f"{doc}.{path}", "mid",
                                f"国别代码不在表内：{code}"))
    # 单号：只拦明显污染（非 ASCII、含空白）；数字位被改写的笔误无法通用识别
    for doc, path, label in NUMBER_FIELDS:
        value = str(get(ctx, f"{doc}.{path}", "") or "").strip()
        if value and (not value.isascii() or any(ch.isspace() for ch in value)):
            issues.append(Issue("L1-10", f"{doc}.{path}", "mid",
                                f"{label}含非法字符：{value!r}",
                                suggestion="只允许字母、数字与 - _ / . 等半角符号"))
    return RuleResult("L1-10", L, "字段格式", "FIX" if issues else "PASS", issues,
                      "报关单填制规范")
