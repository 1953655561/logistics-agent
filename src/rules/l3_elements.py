"""L3 申报要素与归类（10 条）。

确定性规则为主；L3-25/26 的判定用关键词表，LLM 只用于生成解释（可降级）。
"""
from __future__ import annotations

from ..common import get, norm_unit, num
from ..domain.elements import catalog, elements_def
from ..issue import Issue, RuleResult
from ..registry import rule

L = "L3"

SPECIAL = {"material", "use", "process", "composition"}
PLACEHOLDERS = {"", "未知", "其他", "待定", "-", "n/a", "na", "无"}

# 品名关键词 → (章, 具体度)
KEYWORDS = [
    ("玩具", "95", 5), ("玩偶", "95", 5), ("积木", "95", 5),
    ("t恤", "61", 5), ("衬衫", "62", 4), ("针织", "61", 3), ("机织", "62", 3),
    ("塑料管", "39", 5), ("管件", "39", 5), ("钢管", "73", 5),
    ("钢板", "72", 5), ("钢材", "72", 4),
    ("饼干", "19", 5), ("奶粉", "04", 5), ("饮料", "22", 5), ("护肤", "33", 5),
    ("台灯", "94", 5), ("吊灯", "94", 5), ("灯", "94", 3),
    ("手机", "85", 5), ("电脑", "84", 5), ("笔记本", "84", 5),
    ("燃气灶", "73", 5), ("烤箱", "85", 4), ("研磨机", "85", 4),
    ("塑料", "39", 2),
]

CONTRADICTIONS = [
    ("不锈钢", "塑料"), ("棉", "化纤"), ("棉", "涤纶"),
    ("真皮", "人造革"), ("实木", "人造板"),
]


def _items(ctx):
    return get(ctx, "declaration.items", []) or []


def _value(item, key):
    v = (item.get("elements") or {}).get(key)
    return v


def _bad_text(v) -> bool:
    if v is None:
        return True
    s = str(v).strip().lower()
    return s in PLACEHOLDERS


def _mk(rid, title, issues, source, conclusion="FIX"):
    return RuleResult(rid, L, title, conclusion if issues else "PASS", issues, source)


@rule("L3-23", L, "要素齐全", "规范申报目录")
def check_required_elements(ctx):
    issues = []
    for i, item in enumerate(_items(ctx)):
        for d in elements_def(str(item.get("hs_code", ""))):
            if not d.get("required") or d["type"] != "text":
                continue
            if d["key"] in SPECIAL:
                continue
            key = d["key"]
            if _bad_text(_value(item, key)):
                issues.append(Issue("L3-23", f"declaration.items[{i}].elements.{key}", "high",
                                    f"缺申报要素：{d['name']}",
                                    suggestion=f"补充{d['name']}"))
    return _mk("L3-23", "要素齐全", issues, "规范申报目录")


@rule("L3-24", L, "枚举要素", "规范申报目录")
def check_enum(ctx):
    issues = []
    for i, item in enumerate(_items(ctx)):
        for d in elements_def(str(item.get("hs_code", ""))):
            if d["type"] != "enum":
                continue
            v = _value(item, d["key"])
            if v is None or str(v).strip() == "":
                issues.append(Issue("L3-24", f"declaration.items[{i}].elements.{d['key']}", "high",
                                    f"缺申报要素：{d['name']}",
                                    suggestion=f"从 {d.get('values', [])} 中选一个"))
            elif d.get("values") and v not in d["values"]:
                issues.append(Issue("L3-24", f"declaration.items[{i}].elements.{d['key']}", "mid",
                                    f"{d['name']}取值不合法：{v}",
                                    {"allowed": d["values"]}))
    return _mk("L3-24", "枚举要素", issues, "规范申报目录")


@rule("L3-27", L, "材质要素", "规范申报目录")
def check_material(ctx):
    issues = []
    for i, item in enumerate(_items(ctx)):
        keys = [d["name"] for d in elements_def(str(item.get("hs_code", "")))
                if d["key"] == "material"]
        if not keys:
            continue
        v = _value(item, "material")
        if _bad_text(v):
            issues.append(Issue("L3-27", f"declaration.items[{i}].elements.material", "high",
                                "材质要素缺失或无效", suggestion="按税则要求填写具体材质"))
    return _mk("L3-27", "材质要素", issues, "规范申报目录")


@rule("L3-28", L, "用途要素", "规范申报目录")
def check_use(ctx):
    issues = []
    for i, item in enumerate(_items(ctx)):
        if not any(d["key"] == "use" for d in elements_def(str(item.get("hs_code", "")))):
            continue
        v = _value(item, "use")
        if _bad_text(v):
            issues.append(Issue("L3-28", f"declaration.items[{i}].elements.use", "high",
                                "用途要素缺失或无效", suggestion="填写具体用途"))
    return _mk("L3-28", "用途要素", issues, "规范申报目录")


@rule("L3-31", L, "工艺要素", "规范申报目录")
def check_process(ctx):
    issues = []
    for i, item in enumerate(_items(ctx)):
        if not any(d["key"] == "process" for d in elements_def(str(item.get("hs_code", "")))):
            continue
        if _bad_text(_value(item, "process")):
            issues.append(Issue("L3-31", f"declaration.items[{i}].elements.process", "high",
                                "缺工艺要素（如是否漂白、是否成型）"))
    return _mk("L3-31", "工艺要素", issues, "规范申报目录")


@rule("L3-32", L, "成分合计", "规范申报目录")
def check_composition(ctx):
    issues = []
    for i, item in enumerate(_items(ctx)):
        if not any(d["type"] == "composition"
                   for d in elements_def(str(item.get("hs_code", "")))):
            continue
        comp = _value(item, "composition")
        if not isinstance(comp, list) or not comp:
            issues.append(Issue("L3-32", f"declaration.items[{i}].elements.composition", "high",
                                "缺成分含量"))
            continue
        total = sum(num(c.get("pct")) for c in comp)
        if abs(total - 100) > 0.5:
            issues.append(Issue("L3-32", f"declaration.items[{i}].elements.composition", "high",
                                f"成分合计 {total:g}%，应为 100%",
                                {"items": comp}))
    return _mk("L3-32", "成分合计", issues, "规范申报目录")


@rule("L3-30", L, "法定单位换算", "税则")
def check_unit_conv(ctx):
    issues = []
    for i, item in enumerate(_items(ctx)):
        unit = norm_unit(item.get("unit"))
        legal = norm_unit(item.get("legal_unit1"))
        if unit and legal and unit != legal and num(item.get("qty_legal1")) <= 0:
            issues.append(Issue("L3-30", f"declaration.items[{i}].qty_legal1", "mid",
                                f"成交单位 {unit} 与法定单位 {legal} 不同，缺换算数量"))
    return _mk("L3-30", "法定单位换算", issues, "税则")


def _best_chapter(name: str) -> tuple[str, int] | None:
    text = str(name).lower()
    best = None
    for kw, chapter, spec in KEYWORDS:
        if kw in text and (best is None or spec > best[1]):
            best = (chapter, spec)
    return best


def _similar_hs6(name: str, top: int = 3) -> list[dict]:
    def grams(s):
        s = str(s)
        return {s[i:i + 2] for i in range(max(1, len(s) - 1))}
    target = grams(name)
    out = []
    for hs, spec in catalog().items():
        if hs.startswith("_"):
            continue
        g = grams(spec.get("name", ""))
        if not g:
            continue
        sim = len(target & g) / max(1, len(target | g))
        out.append({"hs6": hs[:6], "name": spec.get("name", ""), "confidence": round(sim, 2)})
    out.sort(key=lambda x: -x["confidence"])
    return [x for x in out[:top] if x["confidence"] > 0]


@rule("L3-25", L, "品名-编码冲突", "税则")
def check_chapter(ctx):
    issues = []
    for i, item in enumerate(_items(ctx)):
        hs = str(item.get("hs_code", ""))
        best = _best_chapter(item.get("name", ""))
        if not best:
            continue
        chapter, spec = best
        if spec >= 4 and hs[:2] != chapter:
            sug = _similar_hs6(item.get("name", ""))
            issues.append(Issue("L3-25", f"declaration.items[{i}].hs_code", "high",
                                f"品名「{item.get('name')}」与编码章节 {hs[:2]} 不符，"
                                f"更像第 {chapter} 章",
                                {"suggestions": sug},
                                "确认归类，必要时申请预裁定"))
    return _mk("L3-25", "品名-编码冲突", issues, "税则", "REVIEW")


@rule("L3-26", L, "型号规格矛盾", "规范申报目录")
def check_contradiction(ctx):
    issues = []
    for i, item in enumerate(_items(ctx)):
        elems = item.get("elements") or {}
        text = str(item.get("name", "")) + " " + str(elems.get("spec", "")) + " " + \
            str(elems.get("material", ""))
        for a, b in CONTRADICTIONS:
            if a in text and b in text and a != b:
                issues.append(Issue("L3-26", f"declaration.items[{i}].name", "high",
                                    f"描述自相矛盾：同时出现「{a}」与「{b}」",
                                    suggestion="确认材质后统一表述"))
    return _mk("L3-26", "型号规格矛盾", issues, "规范申报目录", "REVIEW")


@rule("L3-29", L, "归类建议", "相似品名库")
def check_suggestion(ctx):
    """只给建议、不改判：仅当同章内出现高置信度不同子目时以低危提示。"""
    issues = []
    for i, item in enumerate(_items(ctx)):
        hs = str(item.get("hs_code", ""))
        sug = _similar_hs6(item.get("name", ""))
        if not sug:
            continue
        top = sug[0]
        if top["hs6"] != hs[:6] and top["hs6"][:2] == hs[:2] and top["confidence"] >= 0.75:
            issues.append(Issue("L3-29", f"declaration.items[{i}].hs_code", "low",
                                f"相似品名建议归类 {top['hs6']}（置信度 {top['confidence']}），仅供参考",
                                {"suggestions": sug}))
    return _mk("L3-29", "归类建议", issues, "相似品名库")
