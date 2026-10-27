"""生成 5 票更接近真实业务的合成单证，并校验期望结论。

字段参考：
- 海关总署 2019 年第 18 号公告《进出口货物报关单填制规范》
- UPS《商业发票填写指南》

运行：
    python examples/realistic/build.py
"""
from __future__ import annotations

import copy
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from data.synth.generator import make_docs              # noqa: E402
from src.engine import audit                            # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)))

BUYER = "宁波合成进出口有限公司"
SELLER = "GLOBAL TOYS PTE LTD"
CONTRACT_NO = "HT-2026-0901"

EN_NAMES = {
    "塑料制玩具配件": "PLASTIC TOY PARTS",
    "食品研磨机": "FOOD GRINDER",
    "旧机电（二手笔记本电脑）": "USED LAPTOP COMPUTER",
}


def polish(docs: dict) -> dict:
    """补上真实单证常见但评测规则不强制要求的字段（UPS/报关单风格）。"""
    docs = copy.deepcopy(docs)
    for doc in ("invoice", "packing_list", "bl", "declaration"):
        for item in docs[doc]["items"]:
            item["name_en"] = EN_NAMES.get(item["name"], item.get("name_en") or item["name"])
    docs["contract"].update({
        "seller": SELLER, "buyer": BUYER,
        "contract_no": CONTRACT_NO, "date": "2026-08-28",
        "terms": "FOB SINGAPORE", "payment": "T/T 30 days",
    })
    docs["invoice"].update({
        "invoice_no": "INV-2026-0901", "contract_no": CONTRACT_NO,
        "seller": SELLER, "buyer": BUYER,
        "reason_for_export": "sale", "terms": "FOB SINGAPORE",
    })
    docs["packing_list"].update({"pl_no": "PL-2026-0901"})
    docs["bl"].update({
        "bl_no": "SYN-2026-0901", "shipper": SELLER,
        "consignee": BUYER, "notify": BUYER,
        "vessel": "SYNTHETIC VESSEL", "voyage": "V001",
        "pol": "SINGAPORE", "pod": "NINGBO",
        "place_of_receipt": "SINGAPORE", "port_of_discharge": "NINGBO",
    })
    docs["declaration"].update({
        "decl_no": "DEC-2026-0901", "consignee": BUYER,
        "contract_no": CONTRACT_NO, "bl_no": "SYN-2026-0901",
        "customs_office": "宁波海关", "declaration_type": "进口货物报关单",
        "transport_mode": "水路运输", "trade_mode": "一般贸易",
        "exemption_nature": "照章征税", "destination": "宁波",
        "loading_port": "SINGAPORE",
    })
    return docs


def case_standard() -> dict:
    return polish(make_docs(
        items_spec=[("塑料制玩具配件", "9503008900", 800, 12.5)],
        incoterm="FOB", freight=850.0, insurance=45.0,
        packages=40, gross=960.4, net=920.0, ptype="纸箱",
        origin="CN",
    ))


def case_amount_mismatch() -> dict:
    docs = case_standard()
    docs["declaration"]["total_amount"] = round(docs["invoice"]["total_amount"] * 0.9975, 2)
    return docs


def case_missing_3c() -> dict:
    docs = polish(make_docs(
        items_spec=[("食品研磨机", "8509400000", 120, 65.0)],
        incoterm="CIF", packages=20, gross=780.0, net=720.0, ptype="纸箱",
        origin="CN",
    ))
    docs["declaration"]["cert_no"] = ""
    return docs


def case_old_machinery() -> dict:
    return polish(make_docs(
        items_spec=[("旧机电（二手笔记本电脑）", "8471300000", 50, 220.0)],
        incoterm="FOB", freight=600.0, insurance=30.0,
        packages=10, gross=260.0, net=240.0, ptype="木箱",
        origin="CN",
    ))


def case_multi_defect() -> dict:
    docs = polish(make_docs(
        items_spec=[("塑料制玩具配件", "9503008900", 1000, 48.0)],
        incoterm="FOB", freight=0.0, insurance=0.0,
        packages=50, gross=1200.5, net=1150.0, ptype="纸箱",
        origin="VN", declare="2026-10-15",
    ))
    return docs


CASES = [
    ("REAL-001-standard-toys-PASS.json", case_standard, "PASS",
     "标准进口玩具：四单一致、FOB 运保费已申报、3C 证书齐全"),
    ("REAL-002-amount-mismatch-FIX.json", case_amount_mismatch, "FIX",
     "报关单总价少报 0.25%（超过 0.1% 总额容差）"),
    ("REAL-003-missing-3c-REVIEW.json", case_missing_3c, "REVIEW",
     "食品研磨机属 3C 品类但未申报证书号"),
    ("REAL-004-old-machinery-REJECT.json", case_old_machinery, "REJECT",
     "品名含“旧机电”，属禁限类目"),
    ("REAL-005-multi-defect-REVIEW.json", case_multi_defect, "REVIEW",
     "FOB 漏报运保费 + 原产国不一致 + 申报超期，按最严重项定 REVIEW"),
]


def main() -> int:
    index = []
    ok = True
    for filename, builder, expected, note in CASES:
        docs = builder()
        path = os.path.join(OUT, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(docs, f, ensure_ascii=False, indent=2)
        report = audit(docs)
        got = report["verdict"]
        rules = sorted({i["rule_id"] for i in report["issues"]})
        passed = got == expected
        ok = ok and passed
        print(f"{'✅' if passed else '❌'} {filename}: {got}（期望 {expected}）"
              f" rules={rules}")
        index.append({
            "file": filename, "case_id": filename.rsplit(".", 1)[0],
            "expected": expected, "got": got, "rules": rules, "note": note,
        })
    with open(os.path.join(OUT, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    print(f"\n共 {len(CASES)} 票，全部符合期望：{ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
