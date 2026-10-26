"""Mock LLM：确定性输出，保证评测可复现、断网可跑。"""
from __future__ import annotations

import hashlib


class MockLLM:
    name = "mock"

    def complete(self, messages: list[dict], *, schema: dict | None = None,
                 max_tokens: int = 512) -> dict:
        user = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user = str(m.get("content", ""))
                break
        digest = hashlib.sha256(user.encode("utf-8")).hexdigest()[:8]
        if schema and schema.get("type") == "object":
            # 返回符合 schema 的桩：只填 required 字段
            props = schema.get("properties", {})
            out = {}
            for key in schema.get("required", []):
                t = props.get(key, {}).get("type", "string")
                out[key] = {"string": f"mock-{digest}", "number": 0,
                            "integer": 0, "boolean": False,
                            "array": [], "object": {}}.get(t, "")
            text = out
        else:
            text = f"[mock:{digest}] 已根据规则引擎结论生成说明（离线模式）"
        return {"text": text, "model": "mock", "usage": {"input_tokens": len(user) // 2,
                                                         "output_tokens": 20}}
