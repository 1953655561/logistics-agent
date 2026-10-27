"""成本核算：token 用量 → 金额。

价格表可配置（环境变量或构造参数），默认值只是演示用的小额单价；
真实模型请按供应商账单调整，避免把 mock 的估算值当成真实成本。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_INPUT_PER_1K = 0.002   # 元 / 千 input token
DEFAULT_OUTPUT_PER_1K = 0.008  # 元 / 千 output token


@dataclass(frozen=True)
class PriceTable:
    """单价表：按千 token 计价，币种可换。"""

    input_per_1k: float = DEFAULT_INPUT_PER_1K
    output_per_1k: float = DEFAULT_OUTPUT_PER_1K
    currency: str = "CNY"

    def cost(self, usage: dict | None) -> float:
        usage = usage or {}
        try:
            i = float(usage.get("input_tokens", 0) or 0)
            o = float(usage.get("output_tokens", 0) or 0)
        except (TypeError, ValueError):
            return 0.0
        return round(i / 1000.0 * self.input_per_1k
                     + o / 1000.0 * self.output_per_1k, 6)

    def as_dict(self) -> dict:
        return {"input_per_1k": self.input_per_1k,
                "output_per_1k": self.output_per_1k,
                "currency": self.currency}


def price_from_env() -> PriceTable:
    """用环境变量覆盖单价；非法值回退默认，不让计价错误中断审核。"""
    def _f(name: str, default: float) -> float:
        raw = os.environ.get(name)
        if not raw:
            return default
        try:
            v = float(raw)
        except ValueError:
            return default
        return v if v >= 0 else default

    return PriceTable(
        input_per_1k=_f("LOGIAGENT_PRICE_INPUT_PER_1K", DEFAULT_INPUT_PER_1K),
        output_per_1k=_f("LOGIAGENT_PRICE_OUTPUT_PER_1K", DEFAULT_OUTPUT_PER_1K),
        currency=os.environ.get("LOGIAGENT_CURRENCY", "CNY") or "CNY",
    )


@dataclass
class CostEntry:
    case_id: str
    model: str
    input_tokens: int
    output_tokens: int
    cost: float

    def to_dict(self) -> dict:
        return {"case_id": self.case_id, "model": self.model,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens, "cost": self.cost}


class CostMeter:
    """累加每次模型调用的成本；既能做单票成本，也能做整批成本。"""

    def __init__(self, price: PriceTable | None = None):
        self.price = price or price_from_env()
        self.entries: list[CostEntry] = []

    def record(self, usage: dict | None, *, model: str = "",
               case_id: str = "") -> float:
        usage = usage or {}
        try:
            i = int(usage.get("input_tokens", 0) or 0)
            o = int(usage.get("output_tokens", 0) or 0)
        except (TypeError, ValueError):
            i = o = 0
        cost = self.price.cost({"input_tokens": i, "output_tokens": o})
        self.entries.append(CostEntry(case_id, model, i, o, cost))
        return cost

    @property
    def total(self) -> float:
        return round(sum(e.cost for e in self.entries), 6)

    @property
    def total_input_tokens(self) -> int:
        return sum(e.input_tokens for e in self.entries)

    @property
    def total_output_tokens(self) -> int:
        return sum(e.output_tokens for e in self.entries)

    def summary(self) -> dict:
        return {
            "calls": len(self.entries),
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "total_cost": self.total,
            "currency": self.price.currency,
            "price": self.price.as_dict(),
        }


@dataclass
class UsageLog:
    """一次审核内的累计用量（放进 payload / trace）。"""

    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    calls: int = 0
    details: list[dict] = field(default_factory=list)

    def add(self, usage: dict | None, cost: float, *, model: str = "") -> None:
        usage = usage or {}
        try:
            i = int(usage.get("input_tokens", 0) or 0)
            o = int(usage.get("output_tokens", 0) or 0)
        except (TypeError, ValueError):
            i = o = 0
        self.input_tokens += i
        self.output_tokens += o
        self.cost = round(self.cost + cost, 6)
        self.calls += 1
        self.details.append({"model": model, "input_tokens": i,
                             "output_tokens": o, "cost": cost})

    def to_dict(self) -> dict:
        return {"input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "cost": self.cost, "calls": self.calls,
                "details": list(self.details)}
