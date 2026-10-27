"""模型路由：按任务类型选模型档位（cheap / strong）。

设计原则：
- **默认可离线**：没配 key 时所有档位退化为 MockLLM，结论与改动前一致（可复现是硬约束）。
- **只切模型，不改 Prompt/规则**：路由不参与业务判断，成本差异由评测报告给出。
- **可配置**：模型名走环境变量，路由表可在代码里覆盖，便于做 A/B。

环境变量：
    LOGIAGENT_LLM_API_KEY      统一 key（未配置则全部走 mock）
    LOGIAGENT_MODEL_CHEAP      便宜档模型名（默认 gpt-4o-mini）
    LOGIAGENT_MODEL_STRONG     强档模型名（默认 gpt-4o）
    LOGIAGENT_LLM_BASE_URL     网关地址（可选）
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from ..adapters.llm_mock import MockLLM
from ..adapters.llm_openai import OpenAICompatLLM

TASK_TYPES = ("summarize", "classify", "extract", "review", "ask")

# 谁用便宜档、谁用强档：摘要/分类/抽取不值得用强模型，复核与追问要
DEFAULT_ROUTES = {
    "summarize": "cheap",
    "classify": "cheap",
    "extract": "cheap",
    "review": "strong",
    "ask": "strong",
}

DEFAULT_MODELS = {"cheap": "gpt-4o-mini", "strong": "gpt-4o"}

# 参考价（¥/1k tokens），仅用于报告里的成本对比，真实账单请按供应商调整
DEFAULT_PRICES = {
    "cheap": (0.0011, 0.0044),
    "strong": (0.0180, 0.0720),
}


@dataclass(frozen=True)
class ModelSpec:
    tier: str
    model: str
    base_url: str = ""
    api_key: str = ""
    price_in: float = 0.0      # ¥/1k input tokens
    price_out: float = 0.0     # ¥/1k output tokens

    def estimate(self, tokens_in: int, tokens_out: int) -> float:
        return round(tokens_in / 1000 * self.price_in
                     + tokens_out / 1000 * self.price_out, 6)


@dataclass
class ModelRouter:
    """路由表 + 模型档位。llm(task_type) 返回可用实例（离线天然降级）。"""

    routes: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_ROUTES))
    models: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_MODELS))
    prices: dict[str, tuple[float, float]] = field(
        default_factory=lambda: dict(DEFAULT_PRICES))
    api_key: str = ""
    base_url: str = ""

    @classmethod
    def from_env(cls) -> "ModelRouter":
        env = os.environ
        models = {
            "cheap": env.get("LOGIAGENT_MODEL_CHEAP", DEFAULT_MODELS["cheap"]),
            "strong": env.get("LOGIAGENT_MODEL_STRONG", DEFAULT_MODELS["strong"]),
        }
        return cls(models=models,
                   api_key=env.get("LOGIAGENT_LLM_API_KEY", ""),
                   base_url=env.get("LOGIAGENT_LLM_BASE_URL", ""))

    def tier_for(self, task_type: str) -> str:
        return self.routes.get(task_type, "cheap")

    def spec(self, task_type: str) -> ModelSpec:
        tier = self.tier_for(task_type)
        pin, pout = self.prices.get(tier, (0.0, 0.0))
        return ModelSpec(tier=tier, model=self.models.get(tier, ""),
                         base_url=self.base_url, api_key=self.api_key,
                         price_in=pin, price_out=pout)

    def llm(self, task_type: str):
        """返回该任务可用的 LLM；没配 key 时统一退回 mock（离线可跑）。"""
        if not self.api_key:
            return MockLLM()
        return OpenAICompatLLM(base_url=self.base_url or None,
                               api_key=self.api_key,
                               model=self.models.get(self.tier_for(task_type)))

    def describe(self) -> list[dict]:
        return [{"task_type": t, "tier": self.tier_for(t),
                 "model": self.models.get(self.tier_for(t), ""),
                 "offline": not self.api_key} for t in TASK_TYPES]


def default_router(offline: bool = True) -> ModelRouter:
    router = ModelRouter.from_env()
    if offline:
        router.api_key = ""
    return router
