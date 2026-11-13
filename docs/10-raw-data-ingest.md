# 10 · 原始数据接入（W7）交接与实施计划

> 读法：先看第 2 节现状，再按第 4 节（Excel）开工；第 5 节是 OCR。
> 新会话第一条消息：**「读 `AGENTS.md` 和 `docs/10-raw-data-ingest.md`，按第 4 节做 Excel 适配器。」**

## 1. 目标

把「原始文件（Excel / 文字层 PDF / 扫描 PDF / 图片）→ 五单 JSON → 审核结论」打通。

优先级（用户已确认）：

1. **Excel 先做**：确定性最高、零模型，能先把"抽取 → 归一 → 审核"的骨架和评测跑通；
2. **OCR 后做**：最难、最不确定的一层。

目标：常态零人工；异常自动降级/拒收，而不是静默放行。

## 2. 当前状态（2026-11-13）

### 已实现

| 模块 | 作用 | 文件 |
|---|---|---|
| 类型检测 | Excel / 文字层 PDF / 扫描 PDF / 图片 → `route` | `src/ingest/detect.py` |
| 文字层 PDF 抽取 | 五单标签表 + 明细正则 + 置信度 | `src/ingest/pdf_text.py` |
| 端到端管线 | 文件 → 五单 JSON → `engine.audit()` | `src/ingest/pipeline.py` |
| 合成样本 | 单件样本 + 五单成套 PDF | `examples/raw/`、`examples/raw/pdf/` |
| 样本生成器 | 可复现生成全部样本 | `scripts/gen_synthetic_rawdocs.py` |

### 实测

五份文字层 PDF（合同/发票/装箱单/提单/报关单）→

```
missing_docs = []
verdict = FIX
issue_count = 1
issue = L2-13（报关单总价 9975 vs 发票总额 10000）
```

与 `REAL-002-amount-mismatch-FIX.json` 的期望一致。

### 验证

| 项 | 结果 |
|---|---|
| 单元测试 | **303 条 OK**（6 条 PDF 用例需 `pypdf`，未装则 skip） |
| `scripts/gate.py` | **11/11** |
| `scripts/baseline_check.py` | **未发现退化** |

### 未接

- **Excel**（`route=table`）——本阶段 P0；
- **OCR**（`route=ocr`，扫描 PDF / 图片）——P1。

## 3. 关键设计原则

1. **统一出口**：所有抽取器都输出同一套五单字段名（与 `examples/docs.example.json` 一致），
   审核引擎零改动；
2. **带置信度**：`confidence` / `missing` / `needs_human`，低置信不静默通过；
3. **带出处**：字段能指回"哪个文件、第几页/哪个单元格"（目前 PDF 已留 `text_chars`，OCR 需补 locator）；
4. **可评测**：抽取层单独算字段准确率，不和审核指标混在一起；
5. **可复现**：样本由脚本生成，不依赖真实数据。

## 4. P0：Excel 适配器（先做这个）

### 4.1 目标

`src/ingest/excel.py`：`.xlsx` → 单证 dict；`pipeline.py` 支持 `route=table`。

### 4.2 已有样本

`examples/raw/合成发票-INV-2026-0901.xlsx`（17 行 × 8 列）：
表头（发票号/日期/合同号/币制/卖方/买方/成交方式/付款方式）+ 商品行 + 折扣/佣金/特许权使用费 + 总额。

### 4.3 设计要点

- 遍历所有 sheet，用**标题/表头关键词**判断单证类型（发票/箱单/合同/提单/报关单）；
- **表头同义词表**：`发票号 / Invoice No. / INV NO`，`数量 / Qty / 件数`，`单价 / Unit Price` …
- 合并单元格：`ws.merged_cells.ranges` 展开，取左上角值；
- 数值清洗：去千分位、货币符号、全角字符；日期兼容 Excel 序列号与字符串；
- 明细表：从表头行向下读，遇到「合计/折扣/佣金/特许权」停止；
- 输出字段名与 `pdf_text.py` 完全一致，保证两类文件可混跑；
- `confidence`：必填字段缺失、或「数量×单价≠金额」时降置信。

### 4.4 验收标准

- [ ] `合成发票.xlsx` → `invoice_no / total_amount / items[]` 全部正确；
- [ ] 表头**换序**仍能抽（用同义词映射而非列号）；
- [ ] `pipeline` 跑「xlsx 发票 + 其余四份 PDF」→ `FIX` + 仅 `L2-13`；
- [ ] 新增测试 ≥ 8 条；全量测试、gate、baseline 全绿；
- [ ] `examples/raw/README.md` 更新用法。

### 4.5 风险

| 风险 | 说明 | 应对 |
|---|---|---|
| 表头千变万化 | 真实业务同一类单证可能有几十种表头（参考桌面 21 份船司运价表） | 同义词表 + 低置信转人工，**不要硬编码列号** |
| 多 sheet / 隐藏 sheet | 发票可能和箱单在同一个工作簿 | 逐 sheet 判类型 |
| 公式单元格 | `openpyxl` 默认读公式不读值 | `data_only=True` + 读不到时降置信 |
| 旧版 `.xls` | `openpyxl` 不支持 | 先明确提示另存为 `.xlsx`（`detect.py` 已这么处理） |

### 4.6 步骤

1. `excel.py` 骨架：读 workbook、判类型、表头定位；
2. 发票解析 + 单测（现有样本）；
3. 合同 / 装箱单 / 提单 / 报关单解析（可用生成器补样本）；
4. `pipeline.py` 接入 `route=table`；
5. 端到端验证 + 更新文档。

## 5. P1：OCR 适配器（Excel 之后再动）

### 5.1 目标

`src/ingest/ocr.py`：扫描 PDF / 图片 → 文本或块 → 复用 `pdf_text` 的字段解析（或专用解析）。

### 5.2 方案候选（开工前拍板）

| 方案 | 优点 | 代价 |
|---|---|---|
| **MinerU**（推荐） | 扫描 PDF 原生支持；输出 Markdown/JSON + `page/block` locator；与文字层同一入口 | 模型依赖重、安装包大、CPU 慢 |
| PaddleOCR / RapidOCR | 轻、可控 | 需自建版面/表格结构识别 |
| 视觉大模型 | 上手快 | 不可复现、成本高，审计不接受作唯一路径 |

### 5.3 设计要点

- `OcrPort` 接口 + **默认 mock**（无 OCR 依赖也能跑测试）；
- 预处理：200–300 DPI、纠偏、去噪、红章通道分离、去空白页；
- 置信度 + 交叉校验（数量×单价≈金额、总额≈明细合计）→ 低置信转人工；
- `provenance`：文件名 + 页码 + 块号（MinerU 的 locator 可直接用）。

### 5.4 验收标准

- [ ] `examples/raw/合成扫描件-多页.pdf` → 五单字段；
- [ ] 字段级准确率 + CER（字符错误率）指标；
- [ ] 无 OCR 依赖时测试 skip，CI 可装；
- [ ] 与文字层 PDF 走同一套字段名 / 同一套审核。

### 5.5 风险

- 印章、手写、背面透印、多页联单、倾斜；
- MinerU 许可证是 Apache 2.0 + 附加条件，**商用前要确认**；
- 离线包体积可能从 MB 级涨到 GB 级。

## 6. 评测（两层都要）

| 层 | 指标 | 建议位置 |
|---|---|---|
| 抽取层 | 字段准确率、置信度校准、转人工率 | 新增 `evals/extraction.py` |
| 端到端 | 结论一致率、`rule_id` 集合一致 | 复用 `evals/runner.py` 口径 |

**不要只看端到端**：OCR 错一个 0 导致结论变 REVIEW，必须能分清是"抽错"还是"判错"。

## 7. 环境与命令（Windows 坑）

### Python

- 系统 `python`：**没有** `pypdf`；
- bundled Python（有 `openpyxl` / `Pillow` / `pypdf` 7.0）：
  `C:\Users\HHK2023\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe`

### Edge（无头 PDF / 截图）

`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`

### 坑

- **PowerShell 的 `cd` 不会同步 .NET 当前目录**：`[IO.File]::ReadAllText("相对路径")` 会失败，一律用绝对路径；
- 中文文件名在 Edge 输出里可用，但中间 HTML 建议放临时目录；
- 生成样本需要 `openpyxl` + `Pillow` + Edge。

### 常用命令

```powershell
# 生成全部合成样本（4 个单件 + 五单成套 PDF）
python scripts/gen_synthetic_rawdocs.py

# 类型检测
python -m src.ingest.detect examples/raw/pdf/*.pdf

# 端到端（需要 pypdf）
python -m src.ingest.pipeline examples/raw/pdf/*.pdf

# 验收三件套
python -m unittest discover -s tests
python scripts/gate.py
python scripts/baseline_check.py
```

## 8. 硬约束（继承 `AGENTS.md`）

- 离线可跑；核心逻辑只用标准库，`pypdf` / OCR 是可选依赖；
- 结论必须带引用；
- 只读输入，只出补正建议；
- 归类只给 6 位建议，不自动改判；
- **数据全合成**，不引入真实企业名/单号/个人信息；真实样本必须脱敏。

## 9. 待确认（开工前问用户或自行决定）

1. OCR 依赖可以装吗？离线包多大能接受？
2. 有没有真实**脱敏**样本？没有就用合成数据先跑通。
3. Excel 需要支持 `.xls` 旧格式吗？（建议先不做，提示另存）
4. 抽取出错时的兜底顺序：规则 → LLM → 人工？还是直接拒收？
5. `evals/extraction.py` 是否进 `gate`（建议进，但先跑通再加）。

## 10. 与既有文档的关系

- `AGENTS.md`：入口与硬约束；
- `docs/00` 第 12 节 W7：里程碑记录；
- `docs/02`：评测口径（端到端），抽取层评测需要新增；
- `examples/raw/README.md`：样本说明与命令。

**变更纪律**：如果本计划与用户最新说法冲突，以用户为准，并回来改本文件。
