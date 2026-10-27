"""L2 单证一致性（14 条，确定性规则）。"""
from __future__ import annotations

from ..common import (AMOUNT_TOL, BULK_QTY_TOL, QTY_TOL, WEIGHT_TOL, get,
                      money, name_match, num, party_match, rel_diff, within)
from ..domain.codes import INCOTERMS
from ..issue import Issue, RuleResult
from ..registry import rule

L = "L2"

_DOC_LABEL = {"contract": "合同", "invoice": "发票", "declaration": "报关单"}


def _items(ctx, doc):
    return get(ctx, f"{doc}.items", []) or []


@rule("L2-11", L, "品名一致", "内审 SOP")
def check_names(ctx):
    issues = []
    inv_items = _items(ctx, "invoice")
    if not inv_items:
        return RuleResult("L2-11", L, "品名一致", "PASS", [], "内审 SOP")
    inv_names = [it.get("name") for it in inv_items]
    for doc, label in [("packing_list", "装箱单"), ("bl", "提单"), ("declaration", "报关单")]:
        doc_items = _items(ctx, doc)
        if not doc_items:
            continue
        for idx, item in enumerate(doc_items):
            name = item.get("name")
            # 按中文名配对，多商品项时不能都拿发票第 0 项比
            matched = [it for it in inv_items if name_match(name, it.get("name"))]
            if not matched:
                issues.append(Issue("L2-11", f"{doc}.items[].name", "high",
                                    f"{label}品名与发票不一致：{name}",
                                    {"invoice": inv_names[0], "found": name},
                                    "统一品名写法后重报"))
                continue
            # 中文名一致时才看英文名：只做低危提示，不改变结论（避免中英混写误判）
            en = item.get("name_en")
            inv_ens = [it.get("name_en") for it in matched if it.get("name_en")]
            if en and inv_ens and not any(name_match(en, e) for e in inv_ens):
                issues.append(Issue("L2-11", f"{doc}.items[{idx}].name_en", "low",
                                    f"{label}英文品名与发票不一致（中文一致）：{en}",
                                    {"invoice": inv_ens[0], "found": en},
                                    "统一英文品名写法后重报"))
    conclusion = "REVIEW" if any(i.severity != "low" for i in issues) else "PASS"
    return RuleResult("L2-11", L, "品名一致", conclusion, issues, "内审 SOP")


@rule("L2-12", L, "数量一致", "内审 SOP")
def check_qty(ctx):
    inv = sum(num(it.get("qty")) for it in _items(ctx, "invoice"))
    tol = BULK_QTY_TOL if ctx.get("invoice", {}).get("bulk") else QTY_TOL
    issues = []
    # 四单都看：提单数量原来被漏掉，而提单是舱单比对的第一手依据
    for doc, label in [("packing_list", "装箱单"), ("bl", "提单"), ("declaration", "报关单")]:
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
    issues = []
    for doc, label in (("bl", "提单"), ("declaration", "报关单")):
        b = num(get(ctx, f"{doc}.gross_weight"))
        if a and b and rel_diff(a, b) > WEIGHT_TOL:
            issues.append(Issue("L2-15", f"{doc}.gross_weight", "high",
                                f"装箱单与{label}毛重不一致",
                                {"packing": a, doc: b}))
    return RuleResult("L2-15", L, "毛重一致", "FIX" if issues else "PASS", issues, "内审 SOP")


@rule("L2-16", L, "净重一致", "内审 SOP")
def check_net(ctx):
    a = num(get(ctx, "packing_list.net_weight"))
    issues = []
    for doc, label in (("bl", "提单"), ("declaration", "报关单")):
        b = num(get(ctx, f"{doc}.net_weight"))
        if a and b and rel_diff(a, b) > WEIGHT_TOL:
            issues.append(Issue("L2-16", f"{doc}.net_weight", "high",
                                f"装箱单与{label}净重不一致",
                                {"packing": a, doc: b}))
    return RuleResult("L2-16", L, "净重一致", "FIX" if issues else "PASS", issues, "内审 SOP")


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
    issues = []
    dec_consignee = get(ctx, "declaration.consignee")
    # 提单收货人/通知人 vs 报关单境内收货人
    for path, label in (("bl.consignee", "提单收货人"), ("bl.notify", "提单通知人")):
        value = get(ctx, path)
        if value and dec_consignee and not name_match(value, dec_consignee):
            issues.append(Issue("L2-18", "declaration.consignee", "mid",
                                f"报关单收货人与{label}不一致",
                                {"bl": value, "declaration": dec_consignee}))

    # 合同卖方 vs 发票卖方（交易双方卖方链：合同 → 发票 → 提单发货人）
    contract_seller = get(ctx, "contract.seller")
    invoice_seller = get(ctx, "invoice.seller")
    if contract_seller and invoice_seller and not party_match(contract_seller, invoice_seller):
        issues.append(Issue("L2-18", "invoice.seller", "mid",
                            "合同卖方与发票卖方不一致",
                            {"contract": contract_seller, "invoice": invoice_seller}))

    # 发票卖方 vs 提单发货人（交易双方）
    seller = invoice_seller or contract_seller
    shipper = get(ctx, "bl.shipper")
    if seller and shipper and not party_match(seller, shipper):
        issues.append(Issue("L2-18", "bl.shipper", "mid",
                            "提单发货人与发票卖方不一致",
                            {"shipper": shipper, "seller": seller}))

    # 合同买方 vs 发票买方（交易双方）
    contract_buyer = get(ctx, "contract.buyer")
    invoice_buyer = get(ctx, "invoice.buyer")
    if contract_buyer and invoice_buyer and not party_match(contract_buyer, invoice_buyer):
        issues.append(Issue("L2-18", "invoice.buyer", "mid",
                            "合同买方与发票买方不一致",
                            {"contract": contract_buyer, "invoice": invoice_buyer}))

    return RuleResult("L2-18", L, "收发货人一致", "REVIEW" if issues else "PASS",
                      issues, "内审 SOP")


@rule("L2-19", L, "成交方式与运保费", "审价办法")
def check_incoterm(ctx):
    issues = []
    raw = {doc: str(get(ctx, f"{doc}.incoterm", "") or "").strip().upper()
           for doc in ("contract", "invoice", "declaration")}
    # 先判代码合法性：脏值（OB / FOpB）以前会从三个分支全部滑过去，运保费校验等于没做
    invalid = {doc: value for doc, value in raw.items() if value and value not in INCOTERMS}
    if invalid:
        detail = "、".join(f"{_DOC_LABEL[doc]} {value}" for doc, value in invalid.items())
        issues.append(Issue("L2-19", "incoterm", "mid",
                            f"成交方式代码非法（不在 Incoterms 内）：{detail}",
                            {"invalid": invalid}, "改用标准三字代码"))
    valid = [value for value in raw.values() if value in INCOTERMS]
    if len(set(valid)) > 1:
        issues.append(Issue("L2-19", "incoterm", "mid",
                            "合同/发票/报关单成交方式不一致", raw,
                            "统一成交方式或提供说明"))
    inc = valid[0] if valid else ""
    freight = num(get(ctx, "declaration.freight"))
    insurance = num(get(ctx, "declaration.insurance"))
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
    ctr_no = get(ctx, "contract.contract_no")
    dec_no = get(ctx, "declaration.contract_no")
    inv_no = get(ctx, "invoice.contract_no")
    if not dec_no:
        issues.append(Issue("L2-21", "declaration.contract_no", "mid",
                            "报关单未填合同号"))
    elif ctr_no and dec_no != ctr_no:
        issues.append(Issue("L2-21", "declaration.contract_no", "mid",
                            "报关单合同号与合同不一致",
                            {"declaration": dec_no, "contract": ctr_no}))
    # 发票上也必须出现合同号，且与合同一致（v1.5 补齐，原来只比报关单）
    if ctr_no and inv_no and inv_no != ctr_no:
        issues.append(Issue("L2-21", "invoice.contract_no", "mid",
                            "发票合同号与合同不一致",
                            {"invoice": inv_no, "contract": ctr_no}))
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


@rule("L2-23", L, "合同金额勾稽", "审价办法")
def check_contract_amount(ctx):
    """合同总额 vs 发票总额。

    合同是价格谈判的结果，分批/溢短装条款下允许小幅差异，容差取 1%（与 L1-07 行级一致）；
    取 0.1% 会把"分批装运只报一票"这种正常业务判成错误。
    """
    ctr = num(get(ctx, "contract.total_amount"))
    inv = num(get(ctx, "invoice.total_amount"))
    if ctr and inv and rel_diff(ctr, inv) > AMOUNT_TOL:
        return RuleResult("L2-23", L, "合同金额勾稽", "FIX",
                          [Issue("L2-23", "contract.total_amount", "high",
                                 "合同总额与发票总额不一致（超过 1%）",
                                 {"contract": money(ctr), "invoice": money(inv),
                                  "diff": round(rel_diff(ctr, inv), 4)},
                                 "核对合同金额与分批/溢短装条款，必要时改单或补说明")],
                          "审价办法")
    return RuleResult("L2-23", L, "合同金额勾稽", "PASS", [], "审价办法")


@rule("L2-24", L, "要素跨单一致", "规范申报目录")
def check_cross_doc_elements(ctx):
    """发票 vs 报关单的申报要素一致（只比三键，且双方都有值时才比）。

    缺失由 L3-23/24 负责，这里只抓"两张单写的不一样"——
    例如发票写"无品g牌"、报关单写"无品牌"，是同一票货两套口径。
    """
    issues = []
    inv_items, dec_items = _items(ctx, "invoice"), _items(ctx, "declaration")
    for i, dec in enumerate(dec_items):
        inv = inv_items[i] if i < len(inv_items) else {}
        inv_elems, dec_elems = inv.get("elements") or {}, dec.get("elements") or {}
        for key, label in (("brand_type", "品牌类型"), ("material", "材质"), ("use", "用途")):
            a, b = inv_elems.get(key), dec_elems.get(key)
            if a in (None, "") or b in (None, ""):
                continue
            if str(a).strip() != str(b).strip():
                issues.append(Issue("L2-24", f"declaration.items[{i}].elements.{key}", "mid",
                                    f"发票与报关单{label}不一致：{a} vs {b}",
                                    {"invoice": a, "declaration": b},
                                    "统一申报要素后重报"))
    return RuleResult("L2-24", L, "要素跨单一致", "FIX" if issues else "PASS",
                      issues, "规范申报目录")
