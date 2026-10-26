"""工具层：JSON Schema 校验 + 超时 + 重试 + 统一返回。

工具是 Agent 唯一能触碰外部世界的地方，所以在这一层做参数校验与失败收敛。
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
from dataclasses import dataclass, field
from typing import Any, Callable


class ToolError(Exception):
    pass


def _type_ok(t: str, v: Any) -> bool:
    if t == "string":
        return isinstance(v, str)
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if t == "boolean":
        return isinstance(v, bool)
    if t == "array":
        return isinstance(v, list)
    if t == "object":
        return isinstance(v, dict)
    return True


def validate_args(schema: dict, args: dict) -> list[str]:
    """校验 JSON Schema 子集：type/required/properties/enum/min/max/additionalProperties。"""
    errs: list[str] = []
    props = schema.get("properties", {})
    for key in schema.get("required", []):
        if key not in args:
            errs.append(f"缺少必填参数: {key}")
    if schema.get("additionalProperties") is False:
        for key in set(args) - set(props):
            errs.append(f"不允许的参数: {key}")
    for key, val in args.items():
        rule = props.get(key)
        if not rule:
            continue
        t = rule.get("type")
        if t and not _type_ok(t, val):
            errs.append(f"参数 {key} 类型应为 {t}")
            continue
        if "enum" in rule and val not in rule["enum"]:
            errs.append(f"参数 {key} 取值不在枚举内")
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            if "minimum" in rule and val < rule["minimum"]:
                errs.append(f"参数 {key} 小于最小值")
            if "maximum" in rule and val > rule["maximum"]:
                errs.append(f"参数 {key} 大于最大值")
    return errs


@dataclass
class ToolResult:
    ok: bool
    value: Any = None
    error: str = ""
    attempts: int = 1
    ms: float = 0.0

    def to_dict(self) -> dict:
        return {"ok": self.ok, "value": self.value, "error": self.error,
                "attempts": self.attempts, "ms": round(self.ms, 2)}


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    fn: Callable[..., Any]
    timeout_s: float = 2.0
    retries: int = 1
    dangerous: bool = False

    def __call__(self, **kwargs) -> Any:
        return self.fn(**kwargs)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ToolError(f"工具重复注册: {tool.name}")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise ToolError(f"未知工具: {name}")
        return self._tools[name]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def specs(self) -> list[dict]:
        return [{"name": t.name, "description": t.description, "schema": t.schema}
                for t in self._tools.values()]

    def call(self, name: str, **kwargs) -> ToolResult:
        t0 = time.perf_counter()
        try:
            tool = self.get(name)
        except ToolError as exc:
            return ToolResult(False, error=str(exc), ms=(time.perf_counter() - t0) * 1000)
        errs = validate_args(tool.schema, kwargs)
        if errs:
            return ToolResult(False, error="参数校验失败: " + "; ".join(errs),
                              ms=(time.perf_counter() - t0) * 1000)
        attempts = 0
        last = ""
        for i in range(tool.retries + 1):
            attempts = i + 1
            try:
                value = self._run_with_timeout(tool, kwargs)
                return ToolResult(True, value=value, attempts=attempts,
                                  ms=(time.perf_counter() - t0) * 1000)
            except Exception as exc:  # 超时/业务异常都走重试
                last = f"{type(exc).__name__}: {exc}"
                if i < tool.retries:
                    time.sleep(0.01 * (i + 1))
        return ToolResult(False, error=last, attempts=attempts,
                          ms=(time.perf_counter() - t0) * 1000)

    @staticmethod
    def _run_with_timeout(tool: Tool, kwargs: dict) -> Any:
        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(tool.fn, **kwargs)
            try:
                return fut.result(timeout=tool.timeout_s)
            except FutTimeout:
                raise ToolError(f"工具超时 {tool.timeout_s}s")
