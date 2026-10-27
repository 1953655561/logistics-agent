"""令牌桶限流：默认 60 次/分钟，超限由调用方降级。"""
from __future__ import annotations

import threading
import time

DEFAULT_RATE_PER_MIN = 60


class TokenBucket:
    """固定速率 + 突发容量的令牌桶。

    - rate_per_min：每分钟补充的令牌数
    - capacity：桶容量（允许的瞬时突发），默认等于每分钟速率
    - clock：可注入的单调时钟，方便测试
    """

    def __init__(self, rate_per_min: int = DEFAULT_RATE_PER_MIN,
                 capacity: int | None = None, clock=None):
        if rate_per_min <= 0:
            raise ValueError("rate_per_min 必须大于 0")
        self.rate_per_min = int(rate_per_min)
        self.rate_per_sec = self.rate_per_min / 60.0
        self.capacity = float(capacity if capacity is not None
                              else self.rate_per_min)
        self._clock = clock or time.monotonic
        self._tokens = self.capacity
        self._last = self._clock()
        self._lock = threading.Lock()

    def allow(self, tokens: float = 1.0) -> bool:
        """尝试取 tokens 个令牌；不够则返回 False（不阻塞）。"""
        if tokens <= 0:
            return True
        with self._lock:
            now = self._clock()
            elapsed = max(0.0, now - self._last)
            self._last = now
            self._tokens = min(self.capacity,
                               self._tokens + elapsed * self.rate_per_sec)
            if self._tokens + 1e-9 >= tokens:
                self._tokens -= tokens
                return True
            return False

    @property
    def tokens(self) -> float:
        with self._lock:
            return round(self._tokens, 3)

    def snapshot(self) -> dict:
        with self._lock:
            return {"rate_per_min": self.rate_per_min,
                    "capacity": self.capacity,
                    "tokens": round(self._tokens, 3)}
