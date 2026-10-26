"""端口定义：核心只依赖这些协议，不依赖任何框架/第三方库。"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LLMPort(Protocol):
    name: str

    def complete(self, messages: list[dict], *, schema: dict | None = None,
                 max_tokens: int = 512) -> dict:
        """返回 {"text": str, "usage": {...}, "model": str}。"""
        ...


@runtime_checkable
class RepositoryPort(Protocol):
    def save_case(self, case: dict) -> None: ...
    def load_case(self, case_id: str) -> dict | None: ...
    def list_cases(self, limit: int = 20) -> list[dict]: ...
    def append_event(self, case_id: str, event: dict) -> None: ...
    def events(self, case_id: str) -> list[dict]: ...


@runtime_checkable
class TracerPort(Protocol):
    def emit(self, event: dict) -> None: ...
    def events(self) -> list[dict]: ...
    def close(self) -> None: ...


@runtime_checkable
class ApproverPort(Protocol):
    def request(self, request: Any) -> Any:
        """返回 Decision(approved, comment, approver)。"""
        ...


@runtime_checkable
class RetrieverPort(Protocol):
    def search(self, query: str, top_k: int = 3) -> list[dict]: ...
    def cite(self, chunk_id: str) -> dict | None: ...
