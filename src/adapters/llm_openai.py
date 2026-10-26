"""OpenAI 兼容 LLM 适配器：DeepSeek / Qwen / OpenAI 都走这套。

只用 urllib，不引 requests。没配 key 时抛 LLMNotConfigured，由上层降级到 mock。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


class LLMNotConfigured(RuntimeError):
    pass


class LLMUnavailable(RuntimeError):
    pass


class OpenAICompatLLM:
    def __init__(self, base_url: str | None = None, api_key: str | None = None,
                 model: str | None = None, timeout: float = 30.0):
        self.base_url = (base_url or os.environ.get("LOGIAGENT_LLM_BASE_URL")
                         or "https://api.deepseek.com/v1").rstrip("/")
        self.api_key = api_key or os.environ.get("LOGIAGENT_LLM_API_KEY") or ""
        self.model = model or os.environ.get("LOGIAGENT_LLM_MODEL") or "deepseek-chat"
        self.timeout = timeout
        self.name = f"openai-compat:{self.model}"

    def complete(self, messages: list[dict], *, schema: dict | None = None,
                 max_tokens: int = 512) -> dict:
        if not self.api_key:
            raise LLMNotConfigured("未配置 LOGIAGENT_LLM_API_KEY")
        body = {"model": self.model, "messages": messages,
                "max_tokens": max_tokens, "temperature": 0}
        if schema:
            body["response_format"] = {"type": "json_object"}
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise LLMUnavailable(str(exc)) from exc
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return {"text": content, "model": data.get("model", self.model),
                "usage": {"input_tokens": usage.get("prompt_tokens", 0),
                          "output_tokens": usage.get("completion_tokens", 0)}}
