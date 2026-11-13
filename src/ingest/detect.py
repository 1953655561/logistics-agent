"""原始文件类型检测：决定走表格解析、文本抽取还是 OCR。

判定顺序：
1. 扩展名能直接判的（xlsx / 图片）直接返回；
2. PDF 先判断有没有文字层：
   - 装了 ``pypdf``：逐页抽文本，按每页字符数判断（准确）；
   - 没装 ``pypdf``：用 PDF 字节特征兜底（有 /Font 视为文字层，
     有 /Image 且无 /Font 视为扫描件）。

输出统一为 ``DetectResult``，其中 ``route`` 是下一步该走哪条抽取链路：
``table``（表格解析）/ ``text``（文本抽取）/ ``ocr``（OCR）。
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

# 每页少于这么多字符，视为"没有文字层"
TEXT_MIN_CHARS = 20

EXCEL_EXTS = {".xlsx", ".xlsm"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


@dataclass
class DetectResult:
    path: str
    ext: str
    kind: str            # excel / text_pdf / scan_pdf / mixed_pdf / image / unsupported
    route: str           # table / text / ocr / unsupported
    pages: int = 0
    text_chars: int = 0
    has_text_layer: bool = False
    method: str = ""     # ext / pypdf / bytes
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def detect(path) -> DetectResult:
    """检测一份原始文件，返回类型与建议的抽取链路。"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(str(p))
    ext = p.suffix.lower()

    if ext in EXCEL_EXTS:
        return DetectResult(str(p), ext, "excel", "table", method="ext",
                            note="按单元格/表头映射抽取")
    if ext in IMAGE_EXTS:
        return DetectResult(str(p), ext, "image", "ocr", pages=1, method="ext",
                            note="单张图片，走 OCR")
    if ext == ".xls":
        return DetectResult(str(p), ext, "unsupported", "unsupported", method="ext",
                            note="旧版 .xls：请先另存为 .xlsx，或接入 xlrd")
    if ext == ".pdf":
        return detect_pdf(p)
    return DetectResult(str(p), ext, "unsupported", "unsupported", method="ext",
                        note="暂不支持该格式")


def detect_pdf(path) -> DetectResult:
    p = Path(path)
    try:
        return _detect_pdf_pypdf(p)
    except ImportError:
        return _detect_pdf_bytes(p)


def _detect_pdf_pypdf(p: Path) -> DetectResult:
    from pypdf import PdfReader  # 可选依赖；未安装时由调用方兜底

    reader = PdfReader(str(p))
    per_page: list[int] = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        per_page.append(len(text.strip()))
    kind, route, has_text = _classify(len(per_page), per_page)
    return DetectResult(
        str(p), ".pdf", kind, route,
        pages=len(per_page), text_chars=sum(per_page), has_text_layer=has_text,
        method="pypdf", note=f"每页字符数：{per_page[:8]}",
    )


def _detect_pdf_bytes(p: Path) -> DetectResult:
    """没有 pypdf 时的兜底：靠 PDF 里有没有字体/图片对象判断。"""
    raw = p.read_bytes()
    has_font = b"/Font" in raw or b"/FontFile" in raw
    has_image = b"/Image" in raw or b"/XObject" in raw
    m = re.search(rb"/Type\s*/Pages\b.{0,300}?/Count\s+(\d+)", raw, re.S)
    pages = int(m.group(1)) if m else 1

    if has_image and not has_font:
        kind, route, has_text = "scan_pdf", "ocr", False
    elif has_font:
        kind, route, has_text = "text_pdf", "text", True
    else:
        kind, route, has_text = "unknown_pdf", "ocr", False
    return DetectResult(
        str(p), ".pdf", kind, route, pages=pages, text_chars=0,
        has_text_layer=has_text, method="bytes",
        note="未安装 pypdf，使用 PDF 对象特征兜底",
    )


def _classify(pages: int, per_page: list[int]) -> tuple[str, str, bool]:
    if pages == 0:
        return "empty_pdf", "unsupported", False
    text_pages = sum(1 for n in per_page if n >= TEXT_MIN_CHARS)
    if text_pages == pages:
        return "text_pdf", "text", True
    if text_pages == 0:
        return "scan_pdf", "ocr", False
    return "mixed_pdf", "ocr", True


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("用法: python -m src.ingest.detect <文件> [<文件> ...]")
        return 2
    for item in argv:
        try:
            print(json.dumps(detect(item).to_dict(), ensure_ascii=False, indent=2))
        except Exception as exc:
            print(json.dumps({"path": item, "error": f"{type(exc).__name__}: {exc}"},
                             ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
