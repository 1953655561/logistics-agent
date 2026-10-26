"""通用工具：数值容差、名称/单位归一化、字段访问。

离线可跑：只依赖标准库。
"""
from __future__ import annotations

import re
import unicodedata

# ---- 容差（v1.1，属"假设"参数，见 docs/02 第 5 节）----
WEIGHT_TOL = 0.03
AMOUNT_TOL = 0.01
QTY_TOL = 0.01
BULK_QTY_TOL = 0.03


def num(x, default=0.0) -> float:
    try:
        if x is None or x == "":
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


def rel_diff(a, b) -> float:
    a, b = num(a), num(b)
    denom = max(abs(a), abs(b))
    if denom == 0:
        return 0.0
    return abs(a - b) / denom


def within(a, b, tol) -> bool:
    return rel_diff(a, b) <= tol


def money(x) -> float:
    return round(num(x), 2)


def get(obj, path, default=None):
    """读取 "items[0].name" 形式的路径。"""
    cur = obj
    for part in path.split("."):
        if cur is None:
            return default
        m = re.match(r"^([^\[\]]+)((?:\[\d+\])*)$", part)
        if not m:
            return default
        key, idx = m.group(1), m.group(2)
        if isinstance(cur, dict):
            cur = cur.get(key)
        else:
            return default
        for i in re.findall(r"\[(\d+)\]", idx):
            if not isinstance(cur, list):
                return default
            i = int(i)
            if i >= len(cur):
                return default
            cur = cur[i]
    return default if cur is None else cur


# ---- 名称归一化：中英混写、去规格、去标点 ----
# 只收高频词，够用即可；后续可换成可配置词典。
_ZH_EN = {
    "塑料": "plastic", "聚乙烯": "pe", "聚丙烯": "pp", "聚氯乙烯": "pvc",
    "玩具": "toy", "配件": "part", "零件": "part", "组件": "part",
    "管件": "fitting", "管子": "pipe", "管": "pipe",
    "棉": "cotton", "棉制": "cotton", "化纤": "polyester", "涤纶": "polyester",
    "不锈钢": "stainless", "钢": "steel", "铁": "iron", "铝": "aluminium",
    "制": "", "的": "", "用": "", "型": "", "号": "",
    "男式": "men", "女式": "women", "儿童": "children",
    "衬衫": "shirt", "衣服": "garment", "服装": "garment",
    "鞋": "shoe", "靴": "boot",
    "食品": "food", "饮料": "beverage", "酒": "wine",
    "机械": "machine", "电机": "motor", "电器": "appliance",
    "灯": "lamp", "灯具": "lamp",
}

_SPEC_RE = re.compile(
    r"\d+(\.\d+)?\s*(kg|g|mm|cm|m|ml|l|pcs|pc|个|只|件|套|片|台|箱|包|卷)"
)
_PUNCT_RE = re.compile(r"[\(\)（）\[\]【】,，、;；:：\-_/\\|!！?？'\"“”‘’·\s]+")


def normalize_name(s) -> list[str]:
    """返回归一化 token 列表，用于跨语言/跨写法的名称比对。"""
    if not s:
        return []
    s = unicodedata.normalize("NFKC", str(s)).lower()
    s = _SPEC_RE.sub(" ", s)
    s = _PUNCT_RE.sub(" ", s)
    tokens = []
    i = 0
    # 先做中文词替换，再切分
    for zh, en in sorted(_ZH_EN.items(), key=lambda kv: -len(kv[0])):
        if zh and zh in s:
            s = s.replace(zh, " " + en + " ")
    for t in s.split():
        t = t.strip()
        if not t or t.isdigit():
            continue
        tokens.append(t)
    return tokens


def name_match(a, b) -> bool:
    ta, tb = set(normalize_name(a)), set(normalize_name(b))
    if not ta or not tb:
        return False
    inter = ta & tb
    if not inter:
        return False
    jaccard = len(inter) / len(ta | tb)
    return jaccard >= 0.5 or ta <= tb or tb <= ta


# ---- 单位归一化 ----
_UNIT = {
    "kg": "kg", "千克": "kg", "公斤": "kg", "kgs": "kg",
    "g": "g", "克": "g",
    "t": "t", "吨": "t",
    "pcs": "pcs", "pc": "pcs", "个": "pcs", "只": "pcs", "件": "pcs",
    "set": "set", "套": "set",
    "m": "m", "米": "m",
    "m2": "m2", "平方米": "m2",
    "m3": "m3", "立方米": "m3", "方": "m3",
    "l": "l", "升": "l", "ml": "ml",
    "箱": "ctn", "ctn": "ctn", "carton": "ctn",
}


def norm_unit(u) -> str:
    if not u:
        return ""
    return _UNIT.get(str(u).strip().lower(), str(u).strip().lower())
