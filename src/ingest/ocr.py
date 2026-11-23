"""OCR 端口：扫描 PDF / 图片 → 文本块。

设计同 LLM Provider：**默认 mock，不装 OCR 依赖也能跑测试**；真正识别由
可选适配器提供（当前接 RapidOCR），通过 ``LOGIAGENT_OCR`` 选择：

    LOGIAGENT_OCR=auto      # 默认：有 RapidOCR 就用，没有退回 mock
    LOGIAGENT_OCR=rapidocr  # 强制 RapidOCR（未安装时抛 ImportError）
    LOGIAGENT_OCR=mock      # 强制 mock（测试 / 离线演示）

约定：``recognize`` 返回 :class:`OcrResult`，其中 ``text`` 是按阅读顺序拼好的
文本，``blocks`` 保留每块的坐标与置信度（用于按列切表与 locator）。
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Protocol

DEFAULT_LOW_CONFIDENCE = 0.6


@dataclass
class OcrBlock:
    text: str
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1（像素）
    confidence: float = 0.0
    page: int = 1

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OcrResult:
    text: str = ""
    blocks: list[OcrBlock] = field(default_factory=list)
    engine: str = "mock"
    confidence: float = 0.0
    page: int = 1

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "blocks": [b.to_dict() for b in self.blocks],
            "engine": self.engine,
            "confidence": self.confidence,
            "page": self.page,
            "chars": len(self.text),
        }


class OcrPort(Protocol):
    """识别一页图片；实现必须给出 ``name`` 与置信度。"""

    name: str

    def recognize(self, image, page: int = 1) -> OcrResult: ...


class MockOcr:
    """默认后端：可注入文本用于测试；没有文本时置信度为 0，由上层转人工。"""

    name = "mock"

    def __init__(self, texts=None, confidence: float = 0.0):
        self._texts = texts
        self._confidence = float(confidence)

    def recognize(self, image, page: int = 1) -> OcrResult:
        if isinstance(self._texts, str):
            text = self._texts if page == 1 else ""
        elif isinstance(self._texts, (list, tuple)):
            text = self._texts[page - 1] if 0 <= page - 1 < len(self._texts) else ""
        else:
            text = ""
        text = str(text or "")
        blocks = []
        if text:
            for i, line in enumerate(line for line in text.splitlines() if line.strip()):
                blocks.append(OcrBlock(line.strip(), (0.0, float(i * 20), 0.0, float(i * 20 + 18)),
                                       self._confidence, page))
        return OcrResult(text=text, blocks=blocks, engine=self.name,
                         confidence=self._confidence if text else 0.0, page=page)


class RapidOcrEngine:
    """RapidOCR（onnxruntime）适配器：装 ``rapidocr_onnxruntime`` 即可离线跑。"""

    name = "rapidocr"

    def __init__(self, **kwargs):
        try:
            from rapidocr_onnxruntime import RapidOCR  # 可选依赖
        except ImportError as exc:  # pragma: no cover - 取决于环境
            raise ImportError(
                "需要 RapidOCR（pip install -r requirements-ocr.txt）") from exc
        self._engine = RapidOCR(**kwargs)

    def recognize(self, image, page: int = 1) -> OcrResult:
        import numpy as np

        array = np.array(image.convert("RGB"))
        try:
            result, _ = self._engine(array)
        except Exception as exc:  # noqa: BLE001 - 单页失败不拖垮整份
            raise RuntimeError(f"RapidOCR 识别失败：{exc}") from exc
        blocks: list[OcrBlock] = []
        for item in result or []:
            if not item or len(item) < 2:
                continue
            box, text = item[0], str(item[1])
            score = float(item[2]) if len(item) > 2 and item[2] is not None else 0.0
            if not text.strip():
                continue
            xs = [float(point[0]) for point in box]
            ys = [float(point[1]) for point in box]
            blocks.append(OcrBlock(text.strip(), (min(xs), min(ys), max(xs), max(ys)),
                                   round(score, 4), page))
        text = "\n".join(block.text for block in sort_blocks(blocks))
        confidence = round(sum(b.confidence for b in blocks) / len(blocks), 4) if blocks else 0.0
        return OcrResult(text=text, blocks=blocks, engine=self.name,
                         confidence=confidence, page=page)


class MinerUEngine:
    """MinerU 后端（P1.3 可选）：包体 GB 级，先明确“未接入”，不假装可用。"""

    name = "mineru"

    def __init__(self, **kwargs):
        raise ImportError(
            "MinerU 后端是 P1.3 可选项，当前版本未接入；请用 LOGIAGENT_OCR=rapidocr")


_ENGINES: dict[str, OcrPort] = {}


def get_ocr(engine: str | None = None) -> OcrPort:
    """按 ``LOGIAGENT_OCR`` / 参数取 OCR 后端；auto 时找不到 RapidOCR 退回 mock。"""
    name = (engine or os.environ.get("LOGIAGENT_OCR") or "auto").strip().lower()
    if name in ("", "auto"):
        try:
            return _cached("rapidocr", RapidOcrEngine)
        except ImportError:
            return _cached("mock", MockOcr)
    if name == "mock":
        return _cached("mock", MockOcr)
    if name == "rapidocr":
        return _cached("rapidocr", RapidOcrEngine)
    if name == "mineru":
        return MinerUEngine()
    raise ValueError(f"未知 OCR 后端：{engine}（可选 auto / mock / rapidocr / mineru）")


def _cached(key: str, factory):
    if key not in _ENGINES:
        _ENGINES[key] = factory()
    return _ENGINES[key]


def group_rows(blocks: list[OcrBlock], tolerance: float | None = None) -> list[list[OcrBlock]]:
    """把文本块聚成行：返回 top→bottom 的行，每行内按 x 从左到右。"""
    if not blocks:
        return []
    heights = sorted(max(1.0, b.bbox[3] - b.bbox[1]) for b in blocks)
    if tolerance is None:
        tolerance = max(6.0, heights[len(heights) // 2] * 0.6)
    ordered = sorted(blocks, key=lambda b: ((b.bbox[1] + b.bbox[3]) / 2, b.bbox[0]))
    rows: list[dict] = []
    for block in ordered:
        center = (block.bbox[1] + block.bbox[3]) / 2
        if rows and abs(center - rows[-1]["center"]) <= tolerance:
            row = rows[-1]
            count = len(row["blocks"])
            row["center"] = (row["center"] * count + center) / (count + 1)
            row["blocks"].append(block)
        else:
            rows.append({"center": center, "blocks": [block]})
    for row in rows:
        row["blocks"].sort(key=lambda b: b.bbox[0])
    return [row["blocks"] for row in rows]


def sort_blocks(blocks: list[OcrBlock]) -> list[OcrBlock]:
    """按阅读顺序排序：先按行（y 中心），同一行再按 x。"""
    return [block for row in group_rows(blocks) for block in row]
