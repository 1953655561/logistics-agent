"""合成单证生成器：基线 → 施加缺陷 → 可复现（无随机）。"""
from __future__ import annotations

import copy

from src.domain.elements import fill

BASE_ITEM = {
    "name": "塑料制玩具配件",
    "name_en": "PLASTIC TOY PARTS",
    "hs_code": "9503008900",
    "qty": 1000,
    "unit": "个",
    "unit_price": 48.0,
    "amount": 48000.0,
    "origin": "CN",
    "legal_unit1": "个",
    "legal_unit2": "千克",
}


def _items(spec):
    out = []
    for name, hs, qty, price in spec:
        out.append({
            "name": name, "name_en": name, "hs_code": hs, "qty": qty,
            "unit": "个", "unit_price": price, "amount": round(qty * price, 2),
            "origin": "CN", "legal_unit1": "个", "legal_unit2": "千克",
        })
    return out


def make_docs(**kw):
    """生成一票四单一致的单证；kw 覆盖默认值。"""
    spec = kw.get("items_spec")
    items = _items(spec) if spec else [copy.deepcopy(BASE_ITEM)]
    if kw.get("qty"):
        for it in items:
            it["qty"] = kw["qty"]
            it["amount"] = round(it["qty"] * it["unit_price"], 2)
    if kw.get("price"):
        for it in items:
            it["unit_price"] = kw["price"]
            it["amount"] = round(it["qty"] * it["unit_price"], 2)
    for it in items:                     # 按编码补申报要素默认值
        fill(it)
    subtotal = round(sum(it["amount"] for it in items), 2)
    discount = kw.get("discount", 0.0)
    commission = kw.get("commission", 0.0)
    total = round(subtotal - discount - commission, 2)
    qty_total = sum(it["qty"] for it in items)

    cur = kw.get("currency", "USD")
    incoterm = kw.get("incoterm", "FOB")
    freight = kw.get("freight", 1200.0)
    insurance = kw.get("insurance", 60.0)
    if incoterm in {"CIF", "CIP"}:
        freight, insurance = 0.0, 0.0

    docs = {
        "contract": {
            "contract_no": "C-2026-0001",
            "seller": "GLOBAL TOYS PTE LTD",
            "buyer": "宁波测试进出口有限公司",
            "date": "2026-08-28",
            "currency": cur,
            "incoterm": incoterm,
            "total_amount": total,
        },
        "invoice": {
            "invoice_no": "INV-2026-0001",
            "contract_no": "C-2026-0001",
            "date": kw.get("inv_date", "2026-09-01"),
            "seller": "GLOBAL TOYS PTE LTD",
            "buyer": "宁波测试进出口有限公司",
            "currency": cur,
            "incoterm": incoterm,
            "items": items,
            "discount": discount,
            "commission": commission,
            "royalty": kw.get("royalty", 0.0),
            "total_amount": total,
            "bulk": kw.get("bulk", False),
        },
        "packing_list": {
            "pl_no": "PL-2026-0001",
            "date": "2026-09-01",
            "packages": kw.get("packages", 50),
            "package_type": kw.get("ptype", "纸箱"),
            "gross_weight": kw.get("gross", 1200.5),
            "net_weight": kw.get("net", 1150.0),
            "volume": 12.5,
            "marks": {"port": kw.get("pod", "NINGBO"), "text": "N/M"},
            "wood_packaging": kw.get("wood", False),
            "ippc_mark": kw.get("ippc", False),
            "items": copy.deepcopy(items),
        },
        "bl": {
            "bl_no": "BL-2026-0001",
            "date": kw.get("bl_date", "2026-09-03"),
            "arrival_date": kw.get("arrival", "2026-09-20"),
            "vessel": "EVER GIVEN",
            "voyage": "V001",
            "pol": "SINGAPORE",
            "pod": kw.get("pod", "NINGBO"),
            "shipper": "GLOBAL TOYS PTE LTD",
            "consignee": "宁波测试进出口有限公司",
            "notify": "宁波测试进出口有限公司",
            "packages": kw.get("packages", 50),
            "gross_weight": kw.get("gross", 1200.5),
            "volume": 12.5,
            "items": copy.deepcopy(items),
        },
        "declaration": {
            "decl_no": "DEC-2026-0001",
            "declare_date": kw.get("declare", "2026-09-25"),
            "consignee": "宁波测试进出口有限公司",
            "transport_mode": "水路运输",
            "trade_mode": "一般贸易",
            "exemption_nature": "照章征税",
            "origin_country": kw.get("origin", "CN"),
            "cert_origin": kw.get("origin", "CN"),
            "loading_port": "SINGAPORE",
            "destination": "宁波",
            "currency": cur,
            "incoterm": incoterm,
            "freight": freight,
            "insurance": insurance,
            "items": copy.deepcopy(items),
            "total_amount": total,
            "qty_total": qty_total,
            "packages": kw.get("packages", 50),
            "gross_weight": kw.get("gross", 1200.5),
            "net_weight": kw.get("net", 1150.0),
            "contract_no": "C-2026-0001",
            "bl_no": "BL-2026-0001",
            "cert_no": kw.get("cert_no", "3C-2026-0001"),
            "agreement_rate": kw.get("agreement_rate", False),
            "license_no": kw.get("license_no", ""),
            "license_expiry": kw.get("license_expiry", ""),
            "license_qty": kw.get("license_qty", 0),
            "dual_anti_declared": kw.get("dual_anti", False),
            "overseas_reg_no": kw.get("reg_no", "CN-REG-0001"),
            "label_filed": kw.get("label_filed", True),
            "royalty_declared": kw.get("royalty_declared", False),
            "commission_declared": kw.get("commission_declared", True),
        },
    }
    return docs


# ---------------- 缺陷注入 ----------------
def _decl_items(d):
    return d["declaration"]["items"]


def _set_items(d, hs=None, name=None, refill=True):
    """改编码/品名（四单同步），并重算申报要素。"""
    for doc in ("invoice", "packing_list", "bl", "declaration"):
        for it in d[doc]["items"]:
            if hs:
                it["hs_code"] = hs
            if name:
                it["name"] = name
            if refill:
                fill(it)


def m_amount_0975(d):
    d["declaration"]["total_amount"] = round(d["declaration"]["total_amount"] * 0.9975, 2)


def m_amount_099(d):
    d["declaration"]["total_amount"] = round(d["declaration"]["total_amount"] * 0.991, 2)


def m_amount_098(d):
    d["declaration"]["total_amount"] = round(d["declaration"]["total_amount"] * 0.98, 2)


def m_amount_9995(d):
    d["declaration"]["total_amount"] = round(d["declaration"]["total_amount"] * 0.9995, 2)


def m_qty_900(d):
    for it in _decl_items(d):
        it["qty"] = 900
    d["declaration"]["qty_total"] = 900


def m_qty_980(d):
    for it in _decl_items(d):
        it["qty"] = 980
    d["declaration"]["qty_total"] = 980


def m_qty_990(d):
    for it in _decl_items(d):
        it["qty"] = 990
    d["declaration"]["qty_total"] = 990


def m_gross_108(d):
    d["bl"]["gross_weight"] = round(d["bl"]["gross_weight"] * 1.08, 2)


def m_gross_1028(d):
    d["bl"]["gross_weight"] = round(d["bl"]["gross_weight"] * 1.028, 2)


def m_net_105(d):
    d["declaration"]["net_weight"] = round(d["declaration"]["net_weight"] * 1.05, 2)


def m_pkg_48(d):
    d["bl"]["packages"] = 48


def m_cur_eur(d):
    d["invoice"]["currency"] = "EUR"


def m_name_pvc(d):
    for it in d["bl"]["items"]:
        it["name"] = "PVC管件"


def m_consignee(d):
    d["declaration"]["consignee"] = "宁波另一家贸易有限公司"


def m_origin_vn(d):
    d["declaration"]["origin_country"] = "VN"


def m_marks_port(d):
    d["packing_list"]["marks"]["port"] = "SHANGHAI"


def m_cif_freight(d):
    d["invoice"]["incoterm"] = "CIF"
    d["declaration"]["incoterm"] = "CIF"
    d["declaration"]["freight"] = 1200.0
    d["declaration"]["insurance"] = 60.0


def m_fob_no_freight(d):
    d["declaration"]["freight"] = 0.0
    d["declaration"]["insurance"] = 0.0


def m_no_contract_no(d):
    d["declaration"]["contract_no"] = ""


def m_amount_math(d):
    d["invoice"]["items"][0]["amount"] = round(d["invoice"]["items"][0]["amount"] * 1.02, 2)


def m_blno(d):
    d["declaration"]["bl_no"] = "BL-2026-9999"


def m_no_cert(d):
    d["declaration"]["cert_no"] = ""


def m_license_expired(d):
    d["declaration"]["license_no"] = "LIC-2025-001"
    d["declaration"]["license_expiry"] = "2026-08-01"


def m_license_ok(d):
    d["declaration"]["license_no"] = "LIC-2026-001"
    d["declaration"]["license_expiry"] = "2027-08-01"


def m_agreement_no_cert(d):
    d["declaration"]["agreement_rate"] = True
    d["declaration"]["cert_origin"] = ""


def m_old_machine(d):
    _set_items(d, hs="8471300000", name="旧机电（笔记本电脑）")


def m_solid_waste(d):
    _set_items(d, hs="3915100000", name="固体废物（废塑料）")


def m_food(d):
    _set_items(d, hs="1905310000", name="饼干")


def m_food_no_reg(d):
    _set_items(d, hs="1905310000", name="饼干")
    d["declaration"]["overseas_reg_no"] = ""


def m_food_no_label(d):
    _set_items(d, hs="1905310000", name="饼干")
    d["declaration"]["label_filed"] = False


def m_dual_anti(d):
    _set_items(d, hs="7210490000", name="镀锌钢板")


def m_royalty(d):
    d["invoice"]["royalty"] = 5000.0
    d["declaration"]["royalty_declared"] = False


def m_hs_conflict(d):
    _set_items(d, hs="3917400000")


def m_late_declare(d):
    d["declaration"]["declare_date"] = "2026-10-15"


def m_wood(d):
    d["packing_list"]["wood_packaging"] = True


def m_wood_ok(d):
    d["packing_list"]["wood_packaging"] = True
    d["packing_list"]["ippc_mark"] = True


def m_wood_no_ippc(d):
    d["packing_list"]["wood_packaging"] = True
    d["packing_list"]["ippc_mark"] = False


def m_packing_name(d):
    for it in d["packing_list"]["items"]:
        it["name"] = "塑料玩具配件"


def m_unit_pack(d):
    for it in d["packing_list"]["items"]:
        it["unit"] = "件"


def m_no_legal_unit1(d):
    for it in _decl_items(d):
        it["legal_unit1"] = ""


def m_set_tshirt(d):
    _set_items(d, hs="6109100021", name="棉制针织T恤")


def m_name_polyester(d):
    _set_items(d, name="化纤制T恤", refill=False)


def m_name_stainless(d):
    _set_items(d, name="不锈钢塑料制玩具配件", refill=False)


def m_drop_material(d):
    for it in _decl_items(d):
        it["elements"].pop("material", None)


def m_drop_use(d):
    for it in _decl_items(d):
        it["elements"].pop("use", None)


def m_drop_brand_type(d):
    for it in _decl_items(d):
        it["elements"].pop("brand_type", None)


def m_drop_process(d):
    for it in _decl_items(d):
        it["elements"].pop("process", None)


def _scale_composition(d, ratio):
    for it in _decl_items(d):
        comp = it["elements"].get("composition")
        if comp:
            for c in comp:
                c["pct"] = round(c["pct"] * ratio, 2)


def m_composition_95(d):
    _scale_composition(d, 0.95)


def m_composition_90(d):
    _scale_composition(d, 0.90)


MUTATORS = {k[2:]: v for k, v in list(globals().items()) if k.startswith("m_")}


def build_case(case: dict) -> dict:
    docs = make_docs(**case.get("params", {}))
    for name in case.get("mutations", []):
        MUTATORS[name](docs)
    for name in case.get("extra", []):
        MUTATORS[name](docs)
    return {
        "case_id": case["id"],
        "title": case["title"],
        "tags": case.get("tags", []),
        "noise": case.get("noise", []),
        "requires": case.get("requires", []),
        "docs": docs,
        "injected_defects": case.get("defects", []),
        "expected": {"verdict": case["expected"],
                     "basis": case.get("basis", "public")},
    }
