# examples/raw · 合成原始单证

> 用途：在没有真实业务文件的情况下，验证「原始文件 → 抽取 → 五单 JSON → 审核」这条链路。
> **全部为合成数据**，不含任何真实企业名、单号、个人信息。

## 三份文件

| 文件 | 格式 | 对应单证 | 说明 |
|---|---|---|---|
| `合成发票-INV-2026-0901.xlsx` | Excel | 商业发票 | 表头 + 商品行 + 折扣/佣金/特许权使用费 + 总额 |
| `合成报关单-DEC-2026-0901.pdf` | PDF（文字层） | 进口货物报关单 | 17 个表头字段 + 商品行 + 合计；可直接抽文本 |
| `合成扫描件-多页.pdf` | PDF（图片型，2 页，无文字层） | 装箱单 + 报关单 | 模拟纸质件扫描；验证「扫描件检测 + OCR 路由」 |
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

## 已知局限

- 报关单 PDF 是**文字层 PDF**，不是扫描件；扫描件路径由 `合成扫描件-多页.pdf` 和装箱单 PNG 验证。
- 版式是自拟的，不代表任何真实报关行/船司模板。
- 真实版式的准确率必须用脱敏样本另行评测。
- 目前文字层 PDF 的「检测 → 抽取 → 审核」已通；Excel 与 OCR（扫描件）抽取适配器尚未接。
