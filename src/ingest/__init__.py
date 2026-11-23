"""原始文件接入层：类型检测 + 三路抽取（文字层 PDF / Excel / OCR）。

- :mod:`src.ingest.detect`：Excel / 文字层 PDF / 扫描 PDF / 图片 → route
- :mod:`src.ingest.pdf_text`：文字层 PDF（`route=text`）
- :mod:`src.ingest.excel`：Excel（`route=table`）
- :mod:`src.ingest.ocr` + :mod:`src.ingest.ocr_pdf`：扫描件 OCR（`route=ocr`，可选依赖）
- :mod:`src.ingest.pipeline`：文件 → 五单 JSON → 审核
"""
