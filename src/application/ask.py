"""追问服务：把「为什么报这条 / 该改哪一处」变成一次可验证的取证据过程。

设计要点：
- **离线可跑**：没配模型时走关键词路由 + 模板拼装，答案完全由单证证据生成；
- **无证据不硬答**：回答里的每个结论都要挂到 evidence 上，缺证据就回「无法从单证确认」；
- **注入防护**：问题文本一律当数据，命中注入特征只告警、不执行其中指令；
- **不改结论**：追问只读，不写回审核单。
"""
from __future__ import annotations

import re

from ..common import get
from ..harness.guardrails import detect_injection
from ..harness.planner import VERIFY_TARGETS
from ..rag.retriever import default_retriever

RULE_RE = re.compile(r"L\d-\d{2}")

# 关键词 → 规则号：让「币制怎么不一致」这类问题也能落到具体规则上
KEYWORD_RULES = {
    "币制": ["L2-14", "L1-03"],
    "金额": ["L2-13", "L2-23"],
    "总价": ["L2-13", "L2-23"],
    "合同": ["L2-21", "L2-23"],
    "品名": ["L2-11"],
    "收货人": ["L2-18"],
    "发货人": ["L2-18"],
    "唛头": ["L2-22"],
    "提单号": ["L4-40"],
    "要素": ["L2-24"],
    "单位": ["L1-04"],
    "成交方式": ["L2-19"],
    "日期": ["L1-02", "L4-42"],
    "申报期限": ["L4-42"],
    "滞报": ["L4-42"],
    "超期": ["L4-42"],
    "贸易方式": ["L4-35"],
}

# 与单证相关的词：命中任意一个才认为"这个问题在问本票单证"。
# 刻意不含"怎么/哪里/为什么"这类纯疑问词，否则"今天天气怎么样"会被误判成相关问题。
RELEVANT_TERMS = set(KEYWORD_RULES) | {
    "金额", "总价", "单价", "数量", "重量", "毛重", "净重", "件数", "包装",
    "编码", "税号", "归类", "原产地", "运保费", "运费", "保险", "折扣", "佣金",
    "特许权", "许可证", "3c", "证书", "木包装", "ippc", "申报期限", "滞报",
    "报关单", "发票", "箱单", "装箱单", "提单", "合同", "单证", "字段",
    "该改", "怎么改", "改哪", "抄错", "哪份", "哪个错", "不一致", "差异", "依据",
}

UNKNOWN_ANSWER = ("这个问题和本票单证无关，或单证里没有能支撑它的字段；"
                  "我只依据本票的五份单证回答，建议人工确认。")

# 只有这类键的 evidence 说的是"规则参数"，不是"单证里的值"
CONFIG_ONLY_KEYS = {"allowed", "tol", "suggestions", "license_qty"}

# 规则没给 suggestion 时，用行业通行做法兜底（标明是通用做法）
GENERIC_FIX = {
    "L2-13": "以发票总额为准核对报关单总价，差 0.1% 以内视为舍入。",
    "L2-18": "统一主体名称写法：合同/发票/提单/报关单四处用同一简称与后缀。",
    "L2-21": "合同号在合同、发票、报关单三处保持一致。",
    "L2-22": "唛头目的港与提单卸货港写法统一（如 NINGBO）。",
    "L4-40": "报关单提运单号与提单号逐字符核对。",
    "L2-24": "品牌类型/材质/用途在发票与报关单上用同一口径。",
    "L1-10": "商品编号统一 10 位数字，字符集非法时回原单重抄。",
    "L1-02": "日期统一 YYYY-MM-DD。",
}


class AskService:
    def __init__(self, llm=None, retriever=None, max_evidence: int = 6):
        self.llm = llm
        self.retriever = retriever or default_retriever()
        self.max_evidence = max_evidence

    # ---------- 意图 ----------
    @staticmethod
    def _intent(question: str) -> str:
        q = question.lower()
        # "为什么…该怎么改" 同时出现时按"解释"处理，解释完再补一句建议
        asks_why = any(k in q for k in ("为什么", "依据", "凭什么", "原因"))
        if asks_why:
            return "explain"
        if any(k in q for k in ("该改", "怎么改", "改哪", "如何改", "怎么补")):
            return "fix"
        if any(k in q for k in ("哪个错", "是不是抄", "哪份", "对比", "四单")):
            return "diff"
        return "explain"

    def _pick_issues(self, question: str, issues: list) -> list:
        def by_severity(items):
            return sorted(items, key=lambda i: {"high": 0, "mid": 1, "low": 2}
                          .get(i.get("severity"), 3))

        def dedupe_by_rule(items):
            """同一规则只留一条，避免"建议"重复两遍。"""
            seen, out = set(), []
            for it in items:
                rid = it.get("rule_id")
                if rid in seen:
                    continue
                seen.add(rid)
                out.append(it)
            return out

        mentioned = RULE_RE.findall(question)
        if mentioned:
            picked = [i for i in issues if i.get("rule_id") in mentioned]
            if picked:
                return dedupe_by_rule(by_severity(picked))
        for kw, rids in KEYWORD_RULES.items():
            if kw in question:
                picked = [i for i in issues if i.get("rule_id") in rids]
                if picked:
                    return dedupe_by_rule(by_severity(picked))
        # 兜底：优先挑"带证据"的最严重问题；都没证据就取前两条并如实说无法确认
        with_ev = [i for i in issues if i.get("evidence")]
        pool = with_ev or issues
        return dedupe_by_rule(by_severity(pool))[:2]

    # ---------- 主流程 ----------
    def ask(self, case_id: str, question: str, docs: dict,
            issues: list, history_hints: list | None = None) -> dict:
        question = str(question or "").strip()
        if not question:
            raise ValueError("问题不能为空")
        guard = detect_injection(question)
        intent = self._intent(question)
        relevant = self._relevant(question, issues)
        picked = self._pick_issues(question, issues) if relevant else []

        tools_called, evidence, citations = [], [], []
        lines = []

        if intent == "diff":
            lines.append(self._diff_answer(picked, docs, evidence, tools_called))
        else:
            for issue in picked[:2]:
                rid = str(issue.get("rule_id", ""))
                ev = dict(issue.get("evidence") or {})
                # 规则给的 evidence 有时只是"规则参数"（allowed/tol），不是单证实值；
                # 这种情况下改成从单证里取当前值，否则用户看不到"错在哪"
                doc_ev = self._evidence_from_docs(rid, docs,
                                                  str(issue.get("field_path", "")))
                if not ev or set(ev) <= CONFIG_ONLY_KEYS:
                    ev = doc_ev or ev
                if ev:
                    evidence.append({"rule_id": rid, "field_path": issue.get("field_path", ""),
                                     "evidence": ev,
                                     "fields": [{"path": k, "value": v} for k, v in ev.items()]})
                tools_called.append("rules.audit()")
                # 规则原文只在"引用"区出现一次，答案里不再抄，避免同一句话讲两遍
                cite = self._cite(rid) if ev else None
                if cite:
                    citations.append(cite)
                if intent == "fix":
                    fix = issue.get("suggestion") or GENERIC_FIX.get(rid, "")
                    if fix:
                        lines.append(f"{rid}：建议 {fix}")
                else:
                    line = self._explain_line(issue, ev)
                    # 问句里同时问"为什么"和"该怎么改"时，解释完补一句建议
                    if any(k in question for k in ("该改", "怎么改", "改哪", "怎么补")):
                        fix = issue.get("suggestion") or GENERIC_FIX.get(rid, "")
                        if fix:
                            line += f" 建议：{fix}"
                    lines.append(line)

        # 历史提示只在"问的是历史"或"与本条问题同规则"时才进答案，否则只留在详情页提示条
        picked_ids = {str(i.get("rule_id", "")) for i in picked}
        if history_hints and self._hint_relevant(question, history_hints, picked_ids):
            tools_called.append("memory.hints()")
            lines.append(f"历史：{history_hints[0]['note']}。")

        answer = " ".join(x for x in lines if x).strip()
        if not relevant or not answer or not evidence:
            answer = UNKNOWN_ANSWER if not relevant else (
                "单证里没有能支撑该结论的字段或规则，建议人工核对；"
                "如果是归类/税号问题，请以税则与预裁定为准。")
            confidence, uncited = "low", True
        else:
            confidence, uncited = "high", False

        # 有真模型时再让模型润色，但只允许引用已取到的证据
        if relevant and self.llm is not None and getattr(self.llm, "name", "") != "mock":
            answer, uncited = self._polish(question, answer, evidence, uncited)

        if guard:
            # 命中注入特征：不执行问题里的指令，只提示已按数据处理
            answer = "（问题里检测到疑似注入指令，已按数据处理、不执行。）" + answer

        return {
            "case_id": case_id,
            "question": question,
            "intent": intent if relevant else "unrelated",
            "answer": answer,
            "evidence": evidence,
            "citations": citations,
            "tools_called": sorted(set(tools_called)),
            "confidence": confidence,
            "uncited": uncited,
            "guard": guard,
        }

    @staticmethod
    def _hint_relevant(question: str, hints: list, picked_ids: set[str]) -> bool:
        """历史提示该不该进这次的答案。

        两种情况下才相关：问题本身在问历史（"以前/之前/老问题"），
        或提示里反复出现的规则正好是这次被问到的规则。
        否则绝不要塞进答案——问 L1-10 却回一段 L1-02/03/04 的提醒就是噪声。
        """
        if any(k in question for k in ("历史", "以前", "之前", "老问题", "老毛病", "上次")):
            return True
        for hint in hints:
            rid = {r.get("rule_id") for r in (hint.get("top_rules") or [])}
            if rid & picked_ids:
                return True
        return False

    @staticmethod
    def _relevant(question: str, issues: list) -> bool:
        """问题是否在问本票单证：命中规则号、领域词，或明确指向某条问题。"""
        if RULE_RE.search(question):
            return True
        q = question.lower()
        if any(term in q for term in RELEVANT_TERMS):
            return True
        # 直接复述了某条问题的关键词（例如"塑料制玩a具配件"）
        for issue in issues[:20]:
            msg = str(issue.get("message", ""))
            for token in re.findall(r"[\u4e00-\u9fa5A-Za-z]{3,}", msg):
                if token in question:
                    return True
        return False

    @staticmethod
    def _evidence_from_docs(rule_id: str, docs: dict, field_path: str = "") -> dict:
        """规则没带 evidence 时，按 VERIFY_TARGETS 从单证里取当前值补上。

        兜底：规则不在表里但 issue 有 field_path（如 L3-24 的 elements.brand_type），
        就直接读这个字段——总比「没有证据」好。
        """
        out = {}
        for doc, path in VERIFY_TARGETS.get(rule_id, []):
            value = get(docs, f"{doc}.{path}")
            if value not in (None, ""):
                out[f"{doc}.{path}"] = value
        if not out and field_path:
            value = get(docs, field_path)
            if value not in (None, ""):
                out[field_path] = value
        return out

    # ---------- 片段 ----------
    def _cite(self, rule_id: str) -> dict | None:
        try:
            hits = self.retriever.search(rule_id, top_k=1)
        except Exception:
            return None
        if not hits:
            return None
        h = hits[0]
        return {"rule_id": rule_id, "chunk_id": h.get("chunk_id", ""),
                "section": h.get("section", ""),
                "excerpt": (h.get("text") or "")[:120]}

    @staticmethod
    def _explain_line(issue: dict, ev: dict) -> str:
        """一句话说清「哪条规则、报了什么、证据是什么」；规则原文交给引用区。"""
        rid = issue.get("rule_id")
        msg = issue.get("message", "")
        ev_text = "、".join(f"{k}={v}" for k, v in ev.items())
        return f"{rid}：{msg}；证据 {ev_text}。"

    def _diff_answer(self, picked: list, docs: dict, evidence: list,
                     tools_called: list) -> str:
        if not picked:
            return ""
        issue = picked[0]
        rid = str(issue.get("rule_id", ""))
        parts = []
        for doc, path in VERIFY_TARGETS.get(rid, []):
            value = get(docs, f"{doc}.{path}")
            tools_called.append(f"doc.get({doc}.{path})")
            if value is None:
                continue
            parts.append(f"{doc}.{path}={value}")
            evidence.append({"rule_id": rid, "field_path": f"{doc}.{path}",
                             "evidence": {"value": value}})
        if not parts:
            return ""
        return (f"{rid} 涉及的字段取值：{'；'.join(parts)}。"
                f"判断口径是 {issue.get('message', '')}。")

    def _polish(self, question: str, draft: str, evidence: list,
                uncited: bool) -> tuple[str, bool]:
        """模型润色：只允许引用已取到的证据，引用不到就标 uncited。"""
        ids = [f"{e['rule_id']}#{e.get('field_path', '')}" for e in evidence]
        schema = {
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
                "evidence_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["answer", "evidence_ids"],
            "additionalProperties": False,
        }
        try:
            out = self.llm.complete([
                {"role": "system", "content":
                 "你只能基于给定证据回答，不得引入证据之外的事实。证据 id 必须原样引用。"},
                {"role": "user", "content":
                 f"【数据开始】问题：{question}；证据草稿：{draft}；可用证据 id：{ids}【数据结束】"},
            ], schema=schema, max_tokens=400)
            data = (out or {}).get("data") or (out or {})
            text = str(data.get("answer") or "").strip()
            used = [str(x) for x in (data.get("evidence_ids") or [])]
            if text and any(u in ids for u in used):
                return text, False
            return text or draft, True
        except Exception:
            return draft, uncited
