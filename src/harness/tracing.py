"""Tracing：每步一次事件，落 JSONL，可回放。"""
from __future__ import annotations

import json
import os
from datetime import datetime


def _now() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


class JsonlTracer:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        self._fh = open(path, "a", encoding="utf-8")
        self._events: list[dict] = []

    def emit(self, event: dict) -> None:
        rec = {"ts": _now(), **event}
        self._events.append(rec)
        self._fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._fh.flush()

    def events(self) -> list[dict]:
        return list(self._events)

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass


class MemoryTracer:
    def __init__(self):
        self._events: list[dict] = []

    def emit(self, event: dict) -> None:
        self._events.append({"ts": _now(), **event})

    def events(self) -> list[dict]:
        return list(self._events)

    def close(self) -> None:
        pass


def summarize(steps: list[dict]) -> dict:
    """聚合 trace：步数、工具调用、失败数、耗时。"""
    ok = [s for s in steps if s.get("ok")]
    return {
        "steps": len(steps),
        "tool_calls": len([s for s in steps if s.get("tool")]),
        "failed": len(steps) - len(ok),
        "ms": round(sum(s.get("ms", 0) or 0 for s in steps), 2),
    }
