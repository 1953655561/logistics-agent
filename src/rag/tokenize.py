"""中文友好的轻量分词：CJK 二元组 + 英文/数字词。"""
from __future__ import annotations

import re
import unicodedata

_ASCII = re.compile(r"[a-z0-9]+")
_CJK = re.compile(r"[\u4e00-\u9fff]+")


def tokenize(text: str) -> list[str]:
    if not text:
        return []
    s = unicodedata.normalize("NFKC", str(text)).lower()
    tokens: list[str] = _ASCII.findall(s)
    for seg in _CJK.findall(s):
        if len(seg) == 1:
            tokens.append(seg)
        else:
            tokens.extend(seg[i:i + 2] for i in range(len(seg) - 1))
    return tokens
