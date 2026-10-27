"""记忆：单票 scratchpad + 跨票主体历史（SQLite，标准库）。

硬约束（面试会被追问的那条）：
**记忆只进提示，不进 issues、不改 verdict。** 结论必须能只凭本票单证复现，
否则审计性就没了；跨票记忆只用来"提醒"，由人判断。

存什么：主体归一化名（去 LTD/PTE 等法律形式词）+ 命中规则号 + 一句话摘要 + 时间。
不存：金额、单号原文、联系人 —— 隐私和体积都可控。
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
from datetime import datetime, timedelta

from ..common import _LEGAL_TOKENS, get, normalize_name

# 参与记忆的主体字段：(doc, path, 中文名)
PARTY_FIELDS = (
    ("declaration", "consignee", "收货人"),
    ("invoice", "seller", "卖方"),
    ("invoice", "buyer", "买方"),
)

DEFAULT_TTL_DAYS = 90
DEFAULT_MIN_REPEAT = 2

# 与「交易主体」强相关的规则：只有这些反复出现才值得提醒。
# 其余规则（日期、单位、HS 格式……）每票都可能命中，放进提示就是噪声。
PARTY_RELATED_RULES = {"L2-11", "L2-13", "L2-14", "L2-18", "L2-21", "L2-23", "L1-03"}


def _rule_titles() -> dict:
    """规则号 → 中文标题（懒加载，避免 harness 依赖 engine 的循环导入）。"""
    try:
        from ..engine import TITLES
        return TITLES
    except Exception:
        return {}


def party_key(name) -> str:
    """主体归一化：与 party_match 同口径（去法律形式词），再拼成稳定 key。"""
    tokens = sorted(t for t in set(normalize_name(name)) if t not in _LEGAL_TOKENS)
    if not tokens:
        return ""
    raw = "|".join(tokens)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]


SCHEMA = """
CREATE TABLE IF NOT EXISTS party_history (
    party_key  TEXT NOT NULL,
    kind       TEXT NOT NULL,
    case_id    TEXT NOT NULL,
    rules      TEXT NOT NULL,
    summary    TEXT NOT NULL,
    seen_at    TEXT NOT NULL,
    PRIMARY KEY (party_key, case_id)
);
CREATE INDEX IF NOT EXISTS idx_party_seen ON party_history (party_key, seen_at);

CREATE TABLE IF NOT EXISTS case_memory (
    case_id    TEXT NOT NULL,
    key        TEXT NOT NULL,
    value      TEXT NOT NULL,
    tokens     INTEGER NOT NULL DEFAULT 0,
    ts         TEXT NOT NULL,
    PRIMARY KEY (case_id, key)
);
"""


class MemoryStore:
    def __init__(self, path: str = ":memory:"):
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        self.path = path
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    # ---------- 单票 scratchpad ----------
    def remember_case(self, case_id: str, key: str, value: str, tokens: int = 0) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO case_memory (case_id, key, value, tokens, ts) "
            "VALUES (?, ?, ?, ?, ?)",
            (case_id, key, str(value), int(tokens),
             datetime.now().isoformat(timespec="seconds")))
        self._conn.commit()

    def scratch(self, case_id: str, max_tokens: int = 400) -> dict:
        """取回单票草稿，超出 token 预算的部分按写入顺序丢弃（最新的优先保留）。"""
        rows = self._conn.execute(
            "SELECT key, value, tokens FROM case_memory WHERE case_id=? "
            "ORDER BY rowid DESC", (case_id,)).fetchall()
        out, used = {}, 0
        for key, value, tokens in rows:
            if used + tokens > max_tokens:
                break
            out[key] = value
            used += tokens
        return out

    # ---------- 跨票主体历史 ----------
    def remember(self, case_id: str, docs: dict, issues: list) -> dict:
        """审核结束后写入：每个主体一行，记录本票命中的规则。"""
        rules = sorted({str(i.get("rule_id", "")) for i in issues})
        if not rules:
            return {"written": 0}
        summary = "、".join(rules[:4])
        now = datetime.now().isoformat(timespec="seconds")
        written = 0
        for doc, path, _label in PARTY_FIELDS:
            key = party_key(get(docs, f"{doc}.{path}"))
            if not key:
                continue
            self._conn.execute(
                "INSERT OR REPLACE INTO party_history "
                "(party_key, kind, case_id, rules, summary, seen_at) VALUES (?, ?, ?, ?, ?, ?)",
                (key, doc, case_id, ",".join(rules), summary, now))
            written += 1
        self._conn.commit()
        return {"written": written}

    def hints(self, docs: dict, limit: int = 3,
              ttl_days: int = DEFAULT_TTL_DAYS,
              min_repeat: int = DEFAULT_MIN_REPEAT) -> list[dict]:
        """本票主体的历史提示。

        只保留「与主体强相关」的规则（名称/合同号/金额/币制这类跟交易双方绑定的），
        否则一份 29 条问题的手改单里几乎所有规则都出现 2 次，挑出来的三条等于随机，
        提示就成了噪声。规则标题用 engine 的 TITLES 渲染，人读得懂才叫提示。
        """
        titles = _rule_titles()
        since = (datetime.now() - timedelta(days=ttl_days)).isoformat(timespec="seconds")
        out: list[dict] = []
        for doc, path, label in PARTY_FIELDS:
            name = get(docs, f"{doc}.{path}")
            key = party_key(name)
            if not key:
                continue
            rows = self._conn.execute(
                "SELECT case_id, rules, summary, seen_at FROM party_history "
                "WHERE party_key=? AND seen_at>=? ORDER BY seen_at DESC",
                (key, since)).fetchall()
            if len(rows) < min_repeat:
                continue
            counter: dict[str, int] = {}
            for _cid, rules, _s, _t in rows:
                for rid in str(rules).split(","):
                    if rid:
                        counter[rid] = counter.get(rid, 0) + 1
            repeated = {r: n for r, n in counter.items()
                        if n >= min_repeat and r in PARTY_RELATED_RULES}
            if not repeated:
                continue
            top = sorted(repeated.items(), key=lambda kv: (-kv[1], kv[0]))[:2]
            cases = [r[0] for r in rows][:3]
            names = "、".join(f"「{titles.get(r, r)}」" for r, _n in top)
            out.append({
                "kind": doc,
                "label": label,
                "party": str(name),
                "seen_cases": len(rows),
                "cases": cases,
                "top_rules": [{"rule_id": r, "count": n,
                               "title": titles.get(r, r)} for r, n in top],
                "note": f"该{label}近 {len(rows)} 票都出现{names}，"
                        f"建议核对客户档案，而不是每票手改",
                "last_seen": rows[0][3],
            })
        return out[:limit]

    def close(self) -> None:
        self._conn.close()
