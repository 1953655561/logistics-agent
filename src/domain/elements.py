"""申报要素目录：加载 10 位编码对应的要素定义，并提供兜底。"""
from __future__ import annotations

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PATH = os.path.join(ROOT, "data", "rules", "elements.json")

_CACHE: dict | None = None

GENERIC = [
    {"key": "brand_type", "name": "品牌类型", "type": "enum", "required": True,
     "values": ["无品牌", "境内自主品牌", "境内收购品牌", "境外品牌(贴牌生产)", "境外品牌(其他)"],
     "value": "无品牌"},
    {"key": "material", "name": "材质", "type": "text", "required": True, "value": "塑料"},
    {"key": "use", "name": "用途", "type": "text", "required": True, "value": "工业用途"},
]


def catalog() -> dict:
    global _CACHE
    if _CACHE is None:
        with open(_PATH, encoding="utf-8") as f:
            _CACHE = json.load(f)
    return _CACHE


def spec_for(hs10: str) -> dict | None:
    return catalog().get(str(hs10))


def elements_def(hs10: str) -> list[dict]:
    spec = spec_for(hs10)
    if spec and spec.get("elements"):
        return spec["elements"]
    return GENERIC


def fill(item: dict) -> dict:
    """按编码补全默认要素（就地修改并返回）。"""
    hs = str(item.get("hs_code", ""))
    elems = {}
    for d in elements_def(hs):
        v = d.get("value")
        if isinstance(v, list):
            v = [dict(x) for x in v]
        elems[d["key"]] = v
    item["elements"] = elems
    if not item.get("qty_legal1"):
        item["qty_legal1"] = item.get("qty", 0)
    return item
