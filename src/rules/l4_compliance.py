"""L4 监管与合规（12 条，确定性规则 + 名录表）。"""
from __future__ import annotations

from ..common import get, num, parse_date
from ..domain.codes import (CERT_REQUIRED_HS6, DUAL_ANTI_HS6, FOOD_HS2,
                            PROHIBITED_HS4, PROHIBITED_KEYWORDS,
                            TRADE_MODE_EXEMPTION)
from ..issue import Issue, RuleResult
from ..registry import rule

L = "L4"


def _hs_items(ctx):
    return get(ctx, "declaration.items", []) or []


@rule("L4-33", L, "监管证件", "监管条件表")
def check_cert(ctx):
    issues = []
    cert = get(ctx, "declaration.cert_no")
    for i, it in enumerate(_hs_items(ctx)):
        hs6 = str(it.get("hs_code", ""))[:6]
        if hs6 in CERT_REQUIRED_HS6 and not cert:
            issues.append(Issue("L4-33", f"declaration.items[{i}].hs_code", "high",
                                f"{hs6} 属需 3C 认证品类，未申报证书号",
                                suggestion="补 3C 证书号，或办理免办证明"))
    return RuleResult("L4-33", L, "监管证件", "REVIEW" if issues else "PASS",
                      issues, "监管条件表")


@rule("L4-34", L, "协定税率", "原产地规则")
def check_agreement(ctx):
    if get(ctx, "declaration.agreement_rate") and not get(ctx, "declaration.cert_origin"):
        return RuleResult("L4-34", L, "协定税率", "REVIEW",
                          [Issue("L4-34", "declaration.cert_origin", "high",
                                 "申报协定税率但无有效原产地证",
                                 suggestion="补原产地证或改按最惠国税率")],
                          "原产地规则")
    return RuleResult("L4-34", L, "协定税率", "PASS", [], "原产地规则")


@rule("L4-35", L, "贸易方式匹配", "报关单填制规范")
def check_trade_mode(ctx):
    mode = str(get(ctx, "declaration.trade_mode", "")).strip()
    nature = str(get(ctx, "declaration.exemption_nature", "")).strip()
    issues = []
    allowed = TRADE_MODE_EXEMPTION.get(mode)
    # 代码表查不到要报，不能当合法放行——否则脏文本会让整条规则静默通过
    if mode and allowed is None:
        issues.append(Issue("L4-35", "declaration.trade_mode", "mid",
                            f"贸易方式不在代码表内：{mode}",
                            {"allowed": sorted(TRADE_MODE_EXEMPTION)},
                            "按填制规范代码表填写"))
    if allowed and nature and nature not in allowed:
        issues.append(Issue("L4-35", "declaration.exemption_nature", "high",
                            f"贸易方式「{mode}」与征免性质「{nature}」不匹配",
                            {"allowed": sorted(allowed)}))
    return RuleResult("L4-35", L, "贸易方式匹配", "FIX" if issues else "PASS",
                      issues, "报关单填制规范")


@rule("L4-36", L, "禁限类目", "禁限目录")
def check_prohibited(ctx):
    issues = []
    for i, it in enumerate(_hs_items(ctx)):
        hs = str(it.get("hs_code", ""))
        name = str(it.get("name", ""))
        if hs[:4] in PROHIBITED_HS4:
            issues.append(Issue("L4-36", f"declaration.items[{i}].hs_code", "high",
                                f"编码 {hs} 属禁止/限制进口类目",
                                {"match": "hs4", "hs4": hs[:4]}))
        for k in sorted(PROHIBITED_KEYWORDS):
            if k in name:
                # 记下证据类型：仅关键词命中属于弱证据，复核 Agent 会提示人工确认
                issues.append(Issue("L4-36", f"declaration.items[{i}].name", "high",
                                    f"品名含禁限关键词：{name}",
                                    {"match": "keyword", "keyword": k}))
                break
    return RuleResult("L4-36", L, "禁限类目", "REJECT" if issues else "PASS",
                      issues, "禁限目录")


@rule("L4-37", L, "双反税", "双反公告")
def check_dual_anti(ctx):
    issues = []
    for i, it in enumerate(_hs_items(ctx)):
        hs6 = str(it.get("hs_code", ""))[:6]
        if hs6 in DUAL_ANTI_HS6 and not get(ctx, "declaration.dual_anti_declared"):
            issues.append(Issue("L4-37", f"declaration.items[{i}].hs_code", "mid",
                                f"{hs6} 命中双反税目，未申报相应税款",
                                suggestion="按公告税率补报反倾销/反补贴税"))
    return RuleResult("L4-37", L, "双反税", "REVIEW" if issues else "PASS",
                      issues, "双反公告")


@rule("L4-38", L, "食品化妆品注册", "海关总署令")
def check_food(ctx):
    issues = []
    for i, it in enumerate(_hs_items(ctx)):
        hs2 = str(it.get("hs_code", ""))[:2]
        if hs2 in FOOD_HS2 and not get(ctx, "declaration.overseas_reg_no"):
            issues.append(Issue("L4-38", "declaration.overseas_reg_no", "high",
                                "进口食品缺境外生产企业注册号"))
    return RuleResult("L4-38", L, "食品化妆品注册", "REJECT" if issues else "PASS",
                      issues, "海关总署令")


@rule("L4-39", L, "预包装标签", "食品安全法")
def check_label(ctx):
    issues = []
    for i, it in enumerate(_hs_items(ctx)):
        hs2 = str(it.get("hs_code", ""))[:2]
        if hs2 in FOOD_HS2 and not get(ctx, "declaration.label_filed", True):
            issues.append(Issue("L4-39", "declaration.label_filed", "mid",
                                "预包装食品缺中文标签备案"))
    return RuleResult("L4-39", L, "预包装标签", "REVIEW" if issues else "PASS",
                      issues, "食品安全法")


@rule("L4-40", L, "舱单一致", "内审 SOP")
def check_manifest(ctx):
    dec_bl = get(ctx, "declaration.bl_no")
    bl_no = get(ctx, "bl.bl_no")
    if dec_bl and bl_no and dec_bl != bl_no:
        return RuleResult("L4-40", L, "舱单一致", "REVIEW",
                          [Issue("L4-40", "declaration.bl_no", "high",
                                 "报关单提运单号与提单不一致",
                                 {"declaration": dec_bl, "bl": bl_no})], "内审 SOP")
    return RuleResult("L4-40", L, "舱单一致", "PASS", [], "内审 SOP")


@rule("L4-41", L, "完税价格构成", "审价办法")
def check_dutiable_value(ctx):
    issues = []
    royalty = num(get(ctx, "invoice.royalty"))
    if royalty > 0 and not get(ctx, "declaration.royalty_declared"):
        issues.append(Issue("L4-41", "declaration.royalty_declared", "high",
                            "存在特许权使用费但未计入完税价格",
                            {"royalty": royalty},
                            "判断是否与进口货物有关并构成销售条件，必要时计入"))
    commission = num(get(ctx, "invoice.commission"))
    if commission > 0 and not get(ctx, "declaration.commission_declared"):
        issues.append(Issue("L4-41", "declaration.commission_declared", "mid",
                            "除购货佣金外的佣金应计入完税价格",
                            {"commission": commission}))
    return RuleResult("L4-41", L, "完税价格构成", "REVIEW" if issues else "PASS",
                      issues, "审价办法")


@rule("L4-42", L, "申报期限", "海关法")
def check_deadline(ctx):
    raw = get(ctx, "bl.arrival_date")
    arrival = parse_date(raw)
    dec = parse_date(get(ctx, "declaration.declare_date"))
    issues = []
    # 到港日有值却解析不了：申报期限没法核定，必须报出来而不是直接 PASS
    if raw is not None and str(raw).strip() != "" and arrival is None:
        issues.append(Issue("L4-42", "bl.arrival_date", "mid",
                            f"提单到港日格式非法，申报期限无法核定：{raw}",
                            suggestion="按 YYYY-MM-DD 改正到港日后重新核定期限"))
    overdue = False
    if arrival and dec:
        days = (dec - arrival).days
        if days > 14:
            overdue = True
            issues.append(Issue("L4-42", "declaration.declare_date", "mid",
                                f"进境后 {days} 天申报，超过 14 天法定期限",
                                suggestion="核算滞报金"))
    conclusion = "REVIEW" if overdue else ("FIX" if issues else "PASS")
    return RuleResult("L4-42", L, "申报期限", conclusion, issues, "海关法")


@rule("L4-43", L, "木质包装", "木质包装检疫")
def check_wood(ctx):
    if get(ctx, "packing_list.wood_packaging") and not get(ctx, "packing_list.ippc_mark"):
        return RuleResult("L4-43", L, "木质包装", "REVIEW",
                          [Issue("L4-43", "packing_list.ippc_mark", "mid",
                                 "使用木质包装但无 IPPC 标识或处理证明")],
                          "木质包装检疫")
    return RuleResult("L4-43", L, "木质包装", "PASS", [], "木质包装检疫")


@rule("L4-44", L, "许可证有效期", "内审 SOP")
def check_license(ctx):
    issues = []
    exp = parse_date(get(ctx, "declaration.license_expiry"))
    dec = parse_date(get(ctx, "declaration.declare_date"))
    if exp and dec and exp < dec:
        issues.append(Issue("L4-44", "declaration.license_expiry", "high",
                            "许可证件在申报日已过期",
                            {"expiry": str(exp), "declare": str(dec)},
                            "换证或改单"))
    lic_qty = num(get(ctx, "declaration.license_qty"))
    qty = sum(num(it.get("qty")) for it in _hs_items(ctx))
    if lic_qty and qty and lic_qty < qty:
        issues.append(Issue("L4-44", "declaration.license_qty", "mid",
                            "许可证数量不足以覆盖申报数量",
                            {"license_qty": lic_qty, "qty": qty}))
    return RuleResult("L4-44", L, "许可证有效期", "REVIEW" if issues else "PASS",
                      issues, "内审 SOP")
