# examples/raw · 合成原始单证

> 用途：在没有真实业务文件的情况下，验证「原始文件 → 抽取 → 五单 JSON → 审核」这条链路。
> **全部为合成数据**，不含任何真实企业名、单号、个人信息。

## 合成样本

| 文件 | 格式 | 对应单证 | 说明 |
|---|---|---|---|
| `合成发票-INV-2026-0901.xlsx` | Excel | 商业发票 | 表头 + 商品行 + 折扣/佣金/特许权使用费 + 总额（含合并单元格） |
| `合成五单-2026-0901.xlsx` | Excel（5 个 sheet） | 合同 / 发票 / 装箱单 / 提单 / 报关单 | 一个工作簿装五单，验证「逐 sheet 判类型」与纯 Excel 端到端 |
| `合成报关单-DEC-2026-0901.pdf` | PDF（文字层） | 进口货物报关单 | 17 个表头字段 + 商品行 + 合计；可直接抽文本 |
| `合成扫描件-多页.pdf` | PDF（图片型，2 页，无文字层） | 装箱单 + 报关单 | 模拟纸质件扫描；验证「扫描件检测 + OCR 路由」 |
| `合成扫描件-五单.pdf` | PDF（图片型，5 页，无文字层） | 合同 / 发票 / 装箱单 / 提单 / 报关单 | 一份扫描件出五单；验证 OCR 端到端 |
| `合成装箱单-PL-2026-0901.png` | 图片（扫描件风格） | 装箱单 | 带轻微旋转、噪点、灰底，用于验证 OCR 路径 |

## 数据来源

取自 `examples/realistic/REAL-002-amount-mismatch-FIX.json`，并**故意保留原始缺陷**：

- 发票总额 `10000.00`，报关单总价 `9975.00` → 差 25 USD（约 0.25%），
  会触发 L2-13（金额一致，容差 0.1%）→ 结论 `FIX`。

这样抽取完成后，可以直接用现有审核引擎验证"链路是否真的通"。

## 重新生成

```powershell
python scripts/gen_synthetic_rawdocs.py
```

依赖：`openpyxl`、`Pillow`，以及本机 Edge（无头转 PDF / 截图）。
脚本会把中间 HTML 与截图放在系统临时目录，不污染仓库。

## 类型检测

```powershell
python -m src.ingest.detect examples/raw/合成发票-INV-2026-0901.xlsx examples/raw/合成报关单-DEC-2026-0901.pdf examples/raw/合成扫描件-多页.pdf examples/raw/合成装箱单-PL-2026-0901.png
```

输出里的 `kind` / `route` 决定走哪条链路：

| kind | route | 下一步 |
|---|---|---|
| `excel` | `table` | 单元格/表头映射 |
| `text_pdf` | `text` | 直接抽文本 |
| `scan_pdf` | `ocr` | 光栅化 + OCR |
| `image` | `ocr` | OCR |
| `mixed_pdf` | `ocr` | 部分页有文字层，整体走 OCR |

装了 `pypdf` 时逐页统计字符数（精确）；没装时用 PDF 字节特征兜底（有 `/Font` 视为文字层，有 `/Image` 且无 `/Font` 视为扫描件）。

## 五单成套 PDF → 审核（文字层路径）

`pdf/` 下是同一票的五份文字层 PDF（合同 / 发票 / 装箱单 / 提单 / 报关单），用于端到端验证：

```powershell
python -m src.ingest.pipeline `
  examples/raw/pdf/合同-HT-2026-0901.pdf `
  examples/raw/pdf/发票-INV-2026-0901.pdf `
  examples/raw/pdf/装箱单-PL-2026-0901.pdf `
  examples/raw/pdf/提单-SYN-2026-0901.pdf `
  examples/raw/pdf/报关单-DEC-2026-0901.pdf
```

预期输出：

- 五单全部识别，`missing_docs` 为空；
- `verdict = FIX`；
- 仅 1 条问题 `L2-13`（报关单总价 9975 vs 发票总额 10000）。

需要 `pypdf`（`pip install pypdf`）；未安装时管线会提示"需要安装 pypdf"，不会中断。

## Excel 单证 → 审核（表格路径）

Excel 走 `route=table`（`src/ingest/excel.py`），只需要 `openpyxl`，不需要 `pypdf`。
单头字段按「标签 + 值」找，明细表按**表头同义词**映射，列顺序打乱也能抽。

```powershell
# 1) 只抽一份 Excel 发票，看字段与置信度
python -m src.ingest.excel examples/raw/合成发票-INV-2026-0901.xlsx

# 2) 纯 Excel 端到端：一个工作簿五个 sheet → 五单 → 审核
python -m src.ingest.pipeline examples/raw/合成五单-2026-0901.xlsx

# 3) 混合：xlsx 发票 + 其余四份文字层 PDF（需要 pypdf）
python -m src.ingest.pipeline `
  examples/raw/合成发票-INV-2026-0901.xlsx `
  examples/raw/pdf/合同-HT-2026-0901.pdf `
  examples/raw/pdf/装箱单-PL-2026-0901.pdf `
  examples/raw/pdf/提单-SYN-2026-0901.pdf `
  examples/raw/pdf/报关单-DEC-2026-0901.pdf
```

预期（2、3 都是）：

- 五单全部识别，`missing_docs` 为空；
- `verdict = FIX`；
- 仅 1 条问题 `L2-13`（报关单总价 9975 vs 发票总额 10000）。

抽取结果自带 `confidence` / `missing` / `needs_human` / `checks`：

- 必填字段缺失 → 降置信；
- 明细行「数量 × 单价 ≠ 金额」→ 降置信并写入 `checks`；
- 公式单元格没有缓存值（`data_only=True` 读不到）→ 计入 `checks`，不静默当有值。

## 扫描件 / 图片 → 审核（OCR 路径）

OCR 走 `route=ocr`（`src/ingest/ocr.py` + `src/ingest/ocr_pdf.py`）。
依赖：`pypdf` + `Pillow` + `pip install -r requirements-ocr.txt`（RapidOCR）。
无 OCR 依赖时管线会明确提示「未安装 OCR 引擎」，不会静默放行。

```powershell
# 1) 只抽扫描件：每页打印类型/字段/置信度/checks
python -m src.ingest.ocr_pdf examples/raw/合成扫描件-多页.pdf

# 2) 五页扫描件 → 五单 → 审核
python -m src.ingest.pipeline examples/raw/合成扫描件-五单.pdf

# 3) 混合：2 页扫描件（装箱单+报关单）+ 合同/发票/提单三份文字层 PDF
python -m src.ingest.pipeline `
  examples/raw/合成扫描件-多页.pdf `
  examples/raw/pdf/合同-HT-2026-0901.pdf `
  examples/raw/pdf/发票-INV-2026-0901.pdf `
  examples/raw/pdf/提单-SYN-2026-0901.pdf
```

预期（2、3 都是）：

- 五单全部识别，`missing_docs` 为空；
- `verdict = FIX`；
- 仅 1 条问题 `L2-13`。

OCR 结果额外带 `engine` / `ocr_confidence` / `page` / `locators`：

- 字段置信度 = `min(解析置信度, OCR 平均置信度)`；
- OCR 平均置信度 < 0.6、必填缺失、行金额不符、总价缺失 → `needs_human=true`；
- 代码表字段（贸易方式/币制/成交方式）做最近邻纠正并留痕（如「般贸易」→「一般贸易」）。

抽取层指标（字段准确率 + 字段 CER）：

```powershell
python evals/extraction.py      # 或 make extraction
```

## 已知局限

- 版式是自拟的，不代表任何真实报关行/船司模板；真实版式的准确率必须用脱敏样本另行评测。
- 三条链路（文字层 PDF / Excel / OCR）的「检测 → 抽取 → 审核」都已打通；
  MinerU 后端未接（RapidOCR 已够用）。
- Excel 版式是自拟的；真实业务同一类单证可能有几十种表头，靠同义词表 + 低置信转人工，
  **不要硬编码列号**（新增表头请改 `src/ingest/excel.py` 的 `LABELS` / `ITEM_HEADERS`）。
- OCR 对印章、手写、背面透印、严重倾斜没有专项处理；低置信一律转人工。
