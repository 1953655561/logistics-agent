"""L2 单证一致性（12 条，确定性规则）。"""
from __future__ import annotations

from ..common import (BULK_QTY_TOL, QTY_TOL, WEIGHT_TOL, get, money,
                      name_match, num, rel_diff, within)
from ..issue import Issue, RuleResult
from ..registry import rule

L = "L2"


def _items(ctx, doc):
    return get(ctx, f"{doc}.items", []) or []


@rule("L2-11", L, "品名一致", "内审 SOP")
def check_names(ctx):
    issues = []
    inv_names = [it.get("name") for it in _items(ctx, "invoice")]
    for doc, label in [("packing_list", "装箱单"), ("bl", "提单"), ("declaration", "报关单")]:
        names = [it.get("name") for it in _items(ctx, doc)]
        if not names or not inv_names:
            continue
        for name in names:
            if not any(name_match(name, n) for n in inv_names):
                issues.append(Issue("L2-11", f"{doc}.items[].name", "high",
                                    f"{label}品名与发票不一致：{name}",
                                    {"invoice": inv_names[0], "found": name},
                                    "统一品名写法后重报"))
    return RuleResult("L2-11", L, "品名一致", "REVIEW" if issues else "PASS", issues, "内审 SOP")


@rule("L2-12", L, "数量一致", "内审 SOP")
def check_qty(ctx):
    inv = sum(num(it.get("qty")) for it in _items(ctx, "invoice"))
    tol = BULK_QTY_TOL if ctx.get("invoice", {}).get("bulk") else QTY_TOL
    issues = []
    for doc, label in [("packing_list", "装箱单"), ("declaration", "报关单")]:
        q = sum(num(it.get("qty")) for it in _items(ctx, doc))
        if inv and q and rel_diff(inv, q) > tol:
            issues.append(Issue("L2-12", f"{doc}.items[].qty", "high",
                                f"{label}数量与发票不一致",
                                {"invoice": inv, "found": q, "tol": tol},
                                "核对数量口径"))
    return RuleResult("L2-12", L, "数量一致", "FIX" if issues else "PASS", issues, "内审 SOP")


@rule("L2-13", L, "金额一致", "内审 SOP")
def check_amount(ctx):
    # 总额是精确值，容差只允许汇率/四舍五入（0.1%）；行级勾稽另用 1%
    inv = num(get(ctx, "invoice.total_amount"))
    dec = num(get(ctx, "declaration.total_amount"))
    if inv and dec and rel_diff(inv, dec) > 0.001:
        return RuleResult("L2-13", L, "金额一致", "FIX",
                          [Issue("L2-13", "declaration.total_amount", "high",
                                 "报关单总价与发票总额不一致",
                                 {"invoice": money(inv), "declaration": money(dec)},
                                 "以发票为准核对总价")],
                          "内审 SOP")
    return RuleResult("L2-13", L, "金额一致", "PASS", [], "内审 SOP")


@rule("L2-14", L, "币制一致", "内审 SOP")
def check_currency(ctx):
    cur = str(get(ctx, "invoice.currency", "")).upper()
    issues = []
    for doc, label in [("declaration", "报关单")]:
        d = str(get(ctx, f"{doc}.currency", "")).upper()
        if cur and d and cur != d:
            issues.append(Issue("L2-14", f"{doc}.currency", "high",
                                f"{label}币制 {d} 与发票 {cur} 不一致",
                                suggestion="统一币制或提供折算依据"))
    return RuleResult("L2-14", L, "币制一致", "FIX" if issues else "PASS", issues, "内审 SOP")


@rule("L2-15", L, "毛重一致", "内审 SOP")
def check_gross(ctx):
    a = num(get(ctx, "packing_list.gross_weight"))
    b = num(get(ctx, "bl.gross_weight"))
    if a and b and rel_diff(a, b) > WEIGHT_TOL:
        return RuleResult("L2-15", L, "毛重一致", "FIX",
                          [Issue("L2-15", "bl.gross_weight", "high",
                                 "装箱单与提单毛重不一致",
                                 {"packing": a, "bl": b})], "内审 SOP")
    return RuleResult("L2-15", L, "毛重一致", "PASS", [], "内审 SOP")


@rule("L2-16", L, "净重一致", "内审 SOP")
def check_net(ctx):
    a = num(get(ctx, "packing_list.net_weight"))
    b = num(get(ctx, "declaration.net_weight"))
    if a and b and rel_diff(a, b) > WEIGHT_TOL:
        return RuleResult("L2-16", L, "净重一致", "FIX",
                          [Issue("L2-16", "declaration.net_weight", "high",
                                 "装箱单与报关单净重不一致",
                                 {"packing": a, "declaration": b})], "内审 SOP")
    return RuleResult("L2-16", L, "净重一致", "PASS", [], "内审 SOP")


@rule("L2-17", L, "件数一致", "内审 SOP")
def check_packages(ctx):
    a = num(get(ctx, "packing_list.packages"))
    b = num(get(ctx, "bl.packages"))
    c = num(get(ctx, "declaration.packages"))
    if a and ((b and a != b) or (c and a != c)):
        return RuleResult("L2-17", L, "件数一致", "FIX",
                          [Issue("L2-17", "packing_list.packages", "high",
                                 "件数在单证间不一致",
                                 {"packing": a, "bl": b, "declaration": c})], "内审 SOP")
    return RuleResult("L2-17", L, "件数一致", "PASS", [], "内审 SOP")


@rule("L2-18", L, "收发货人一致", "内审 SOP")
def check_parties(ctx):
    a = get(ctx, "bl.consignee")
    b = get(ctx, "declaration.consignee")
    if a and b and not name_match(a, b):
        return RuleResult("L2-18", L, "收发货人一致", "REVIEW",
                          [Issue("L2-18", "declaration.consignee", "mid",
                                 "报关单收货人与提单收货人不一致",
                                 {"bl": a, "declaration": b})], "内审 SOP")
    return RuleResult("L2-18", L, "收发货人一致", "PASS", [], "内审 SOP")


@rule("L2-19", L, "成交方式与运保费", "审价办法")
def check_incoterm(ctx):
    inc = str(get(ctx, "invoice.incoterm", "") or get(ctx, "declaration.incoterm", "")).upper()
    freight = num(get(ctx, "declaration.freight"))
    insurance = num(get(ctx, "declaration.insurance"))
    issues = []
    if inc in {"CIF", "CIP"} and (freight or insurance):
        issues.append(Issue("L2-19", "declaration.freight", "high",
                            f"{inc} 成交，运费/保费已含在成交价内，重复申报会导致重复计税",
                            {"freight": freight, "insurance": insurance},
                            "将运费、保费置 0"))
    elif inc in {"CFR", "CPT"} and freight:
        issues.append(Issue("L2-19", "declaration.freight", "high",
                            f"{inc} 成交，运费已含在成交价内，不应重复申报",
                            {"freight": freight}, "运费置 0"))
    elif inc in {"FOB", "EXW", "FCA"} and (freight <= 0):
        issues.append(Issue("L2-19", "declaration.freight", "high",
                            f"{inc} 成交，买方支付的运保费应计入完税价格，但未申报",
                            {"incoterm": inc, "freight": freight},
                            "补报运至境内输入地点起卸前的运费、保费"))
    return RuleResult("L2-19", L, "成交方式与运保费", "FIX" if issues else "PASS",
                      issues, "审价办法")


@rule("L2-20", L, "原产国一致", "报关单填制规范")
def check_origin(ctx):
    issues = []
    dec_origin = str(get(ctx, "declaration.origin_country", "")).upper()
    for i, it in enumerate(_items(ctx, "invoice")):
        o = str(it.get("origin", "")).upper()
        if o and dec_origin and o != dec_origin:
            issues.append(Issue("L2-20", "declaration.origin_country", "mid",
                                "报关单原产国与发票不一致",
                                {"invoice": o, "declaration": dec_origin},
                                "核对原产地证"))
    cert_origin = str(get(ctx, "declaration.cert_origin", "")).upper()
    if cert_origin and dec_origin and cert_origin != dec_origin:
        issues.append(Issue("L2-20", "declaration.cert_origin", "mid",
                            "原产地证与报关单原产国不一致",
                            {"cert": cert_origin, "declaration": dec_origin}))
    return RuleResult("L2-20", L, "原产国一致", "REVIEW" if issues else "PASS",
                      issues, "报关单填制规范")


@rule("L2-21", L, "单号引用", "内审 SOP")
def check_refs(ctx):
    issues = []
    dec_no = get(ctx, "declaration.contract_no")
    ctr_no = get(ctx, "contract.contract_no")
    if not dec_no:
        issues.append(Issue("L2-21", "declaration.contract_no", "mid",
                            "报关单未填合同号"))
    elif ctr_no and dec_no != ctr_no:
        issues.append(Issue("L2-21", "declaration.contract_no", "mid",
                            "报关单合同号与合同不一致",
                            {"declaration": dec_no, "contract": ctr_no}))
    return RuleResult("L2-21", L, "单号引用", "FIX" if issues else "PASS", issues, "内审 SOP")


@rule("L2-22", L, "唛头对应", "内审 SOP")
def check_marks(ctx):
    port = str(get(ctx, "packing_list.marks.port", "")).upper()
    pod = str(get(ctx, "bl.pod", "")).upper()
    if port and pod and port != pod:
        return RuleResult("L2-22", L, "唛头对应", "FIX",
                          [Issue("L2-22", "packing_list.marks.port", "mid",
                                 "唛头目的港与提单卸货港不一致",
                                 {"marks": port, "bl_pod": pod})], "内审 SOP")
    return RuleResult("L2-22", L, "唛头对应", "PASS", [], "内审 SOP")
