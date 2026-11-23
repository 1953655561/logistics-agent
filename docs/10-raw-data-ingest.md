# 10 · 原始数据接入（W7）交接与实施计划

> 读法：第 2 节现状；第 4 节（Excel）与第 5 节（OCR）**均已完成**，实现记录见 4.7 / 5.6。
> 新会话可先跑验收三件套，再按第 9 节决定下一步（真实脱敏样本评测 / MinerU 可选后端）。

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
| **Excel 抽取** | 表头同义词 + 合并单元格 + 明细停止 + 置信度（P0 已完成） | `src/ingest/excel.py` |
| **OCR 抽取** | 扫描 PDF/图片 → 文本块 → 表格按坐标切列（P1 已完成） | `src/ingest/ocr.py`、`src/ingest/ocr_pdf.py` |
| 端到端管线 | 文件 → 五单 JSON → `engine.audit()`（`table` / `text` / `ocr` 三路） | `src/ingest/pipeline.py` |
| **HTTP 上传** | `POST /api/ingest`（multipart）→ 建审核单；`GET /api/cases/{id}/ingest` 回查 | `web_api.py`、`fastapi_api.py`、`fallback_server.py` |
| **Web 入口** | 「导入单证」新增原始文件页签；详情页「原始单证」展示置信度/缺字段 | `web/src/components/ImportCaseModal.tsx`、`CaseDetailPage.tsx` |
| **Docker** | 默认装 `requirements-ingest.txt`；compose 默认 `WITH_OCR=1`（含 RapidOCR），裸 build 用 `--build-arg WITH_OCR=1` | `Dockerfile`、`docker-compose.yml` |
| 合成样本 | 单件样本 + 五单 PDF + 五单 Excel + 2 页/5 页扫描件 | `examples/raw/`、`examples/raw/pdf/` |
| 样本生成器 | 可复现生成全部样本（含五 sheet 工作簿与五页扫描件） | `scripts/gen_synthetic_rawdocs.py` |

### 实测

五份文字层 PDF（合同/发票/装箱单/提单/报关单）→

```
missing_docs = []
verdict = FIX
issue_count = 1
issue = L2-13（报关单总价 9975 vs 发票总额 10000）
```

一个 Excel 工作簿五个 sheet（`examples/raw/合成五单-2026-0901.xlsx`）→ 同上：
`missing_docs=[]`、`FIX`、仅 `L2-13`；「xlsx 发票 + 其余四份 PDF」混跑结果也一致。

扫描件（`合成扫描件-多页.pdf`：装箱单 + 报关单）+ 合同/发票/提单三份文字层 PDF →
五单齐套、`FIX`、仅 `L2-13`；五页扫描件 `合成扫描件-五单.pdf` 单独跑也是 `FIX` + 仅 `L2-13`。

HTTP 上传（`POST /api/ingest`）用同一批文件建单：Excel 发票单独上传 → 建单成功（缺单转 REVIEW）；
xlsx 发票 + 四份 PDF 混传 → 五单齐套、`FIX`、仅 `L2-13`。

### 验证

| 项 | 结果 |
|---|---|
| 单元测试 | **343 条 OK**（缺 `pypdf` / OCR 依赖时相关用例 skip） |
| `scripts/gate.py` | **12/12**（第 12 项：抽取字段准确率 ≥ 90%） |
| `scripts/baseline_check.py` | **未发现退化**（含抽取字段准确率） |
| `evals/extraction.py` | 四条路由字段准确率 **100%**，字段 CER 0.000 |
| `pnpm build`（AntD） | 通过 |

### 未接 / 未做

- **MinerU 后端**（可选，P1.3）——RapidOCR 已够用，MinerU 留接口位置；
- **真实脱敏扫描件评测**——当前只有合成样本（含旋转/噪点），真实版式需另测。

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

- [x] `合成发票.xlsx` → `invoice_no / total_amount / items[]` 全部正确；
- [x] 表头**换序**仍能抽（用同义词映射而非列号）；
- [x] `pipeline` 跑「xlsx 发票 + 其余四份 PDF」→ `FIX` + 仅 `L2-13`；
- [x] 新增测试 ≥ 8 条；全量测试、gate、baseline 全绿；
- [x] `examples/raw/README.md` 更新用法。

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

### 4.7 实现记录（2026-11-13，P0 完成）

| 项 | 落地 |
|---|---|
| 抽取器 | `src/ingest/excel.py`：`extract` / `extract_workbook` / `extract_sheet` |
| 单证类型 | 标题关键词打分 + 标签命中数；报关单/发票/装箱单/提单/合同互不误判 |
| 表头 | `LABELS`（单头字段）与 `ITEM_HEADERS`（明细列）两组同义词，长标签优先 |
| 合并单元格 | `ws.merged_cells.ranges` 展开，整个区域取左上角值 |
| 数值/日期 | 全角转半角、去千分位/货币符号；日期兼容 `datetime` 与 Excel 序列号 |
| 明细 | 从表头行向下读，遇到合计/折扣/佣金/特许权/备注等停止 |
| 置信度 | 必填缺失、`数量×单价≠金额`、公式无缓存值 → 降置信并写 `checks` |
| 多 sheet | 一个工作簿逐 sheet 判类型，可同时产出多份单证 |
| 样本 | 新增 `examples/raw/合成五单-2026-0901.xlsx`（五 sheet，生成器可复现） |
| 测试 | `tests/test_ingest_excel.py` 17 条（1 条需 `pypdf`） |

**已知取舍**：`openpyxl` 是可选依赖（未装时管线提示安装，不中断）；
`.xls` 旧格式仍按 `detect.py` 提示另存 `.xlsx`；真实表头需要往同义词表里补，
补不动时靠低置信转人工，不硬编码列号。

## 5. P1：OCR 适配器（已完成，2026-11-13）

### 5.1 目标

`src/ingest/ocr.py` + `src/ingest/ocr_pdf.py`：扫描 PDF / 图片 → 文本块 → 复用 `pdf_text`
的字段解析；明细表用 OCR 块坐标切列，输出与 PDF/Excel 同一套字段名。

### 5.2 方案拍板

| 方案 | 结论 |
|---|---|
| **RapidOCR** | **已采用（默认）**：pip 安装、自带中英模型、离线、CPU 可跑 |
| MinerU | 接受但暂不接（P1.3）：GB 级依赖 + 许可证附加条件；接口已留 |
| PaddleOCR | 备选，不默认 |
| Tesseract | 不采用：需要外部 exe/语言包，pip 不可复现 |
| 视觉大模型 | 不作唯一路径（不可复现/成本高） |

### 5.3 设计要点（落地版）

- `OcrPort` 协议 + **默认 mock**：`LOGIAGENT_OCR=auto|mock|rapidocr`，无依赖也能跑测试；
- 取页图：扫描 PDF 用 `pypdf` 读嵌入图（不需要 PyMuPDF）；文字层页直接用文本；
- 预处理：灰度 + 小图放大；**不做中值滤波**（实测会把 8–10px 小字糊掉）；
- 文本归一：按行重排块 → 一行多标签拆成「一行一个标签」→ 复用 `parse_document`；
- 明细表：用表头块坐标切列，不靠正则猜列序；合计行回填 `total_amount` / `qty_total`；
- 置信度：`min(解析置信度, OCR 平均置信度)`；必填缺失、行金额不符、总价缺失 → 转人工；
- 代码表纠错：贸易方式/币制/成交方式做最近邻纠正并留痕（如「般贸易」→「一般贸易」）；
- `locators`：字段 → 页码 + bbox + 块文本 + 置信度（不进 `docs`，引擎零改动）。

### 5.4 验收标准

- [x] `examples/raw/合成扫描件-多页.pdf` → 装箱单 + 报关单字段；
- [x] 五页扫描件 `合成扫描件-五单.pdf` → 五单 → `FIX` + 仅 `L2-13`；
- [x] 字段级准确率 + 字段 CER 指标（`evals/extraction.py`，四条路由均 100% / 0.000）；
- [x] 无 OCR 依赖时测试 skip，`requirements-ocr.txt` 可装；
- [x] 与文字层 PDF 走同一套字段名 / 同一套审核。

### 5.5 风险

- 印章、手写、背面透印、多页联单、倾斜；
- MinerU 许可证是 Apache 2.0 + 附加条件，**商用前要确认**；
- 离线包体积：RapidOCR 几十 MB 级；MinerU 会到 GB 级；
- 合成样本不能代表真实版式，真实脱敏样本必须另测。

### 5.6 实现记录（2026-11-13）

| 项 | 落地 |
|---|---|
| 端口 | `src/ingest/ocr.py`：`OcrResult` / `OcrBlock` / `OcrPort` / `MockOcr` / `RapidOcrEngine` |
| 页面 | `src/ingest/ocr_pdf.py`：取页图、预处理、逐页解析、表头坐标切列、locator |
| 管线 | `pipeline.py` 支持 `route=ocr`，逐页抽取并按置信度合并 |
| 依赖 | `requirements-ocr.txt`（`rapidocr_onnxruntime` + `onnxruntime`） |
| 样本 | `合成扫描件-多页.pdf`（2 页）、`合成扫描件-五单.pdf`（5 页），生成器可复现 |
| 测试 | `tests/test_ingest_ocr.py` 15 条（真实 OCR 用例无依赖时 skip） |
| 评测 | `evals/extraction.py`：Excel / 文字 PDF / 2 页扫描 / 5 页扫描 → 字段准确率 100%、CER 0.000 |
| 产品化 | `POST /api/ingest` + Web 上传页签 + 详情「原始单证」页签；Docker 默认装 ingest 依赖、OCR 可选构建 |
| 门禁 | extraction 进 gate 第 12 项（≥90%）与 baseline 回归 |

**已知取舍**：OCR 平均置信度低于 0.6、必填缺失、行金额不符或总价缺失时 `needs_human=true`；
识别文本里的表头残留会做“无数值就丢弃”，不静默当字段值。

## 6. 评测（两层都要）

| 层 | 指标 | 建议位置 |
|---|---|---|
| 抽取层 | 字段准确率、置信度校准、转人工率 | `evals/extraction.py`（已实现，四条路由 100%） |
| 端到端 | 结论一致率、`rule_id` 集合一致 | 复用 `evals/runner.py` 口径 |

**不要只看端到端**：OCR 错一个 0 导致结论变 REVIEW，必须能分清是"抽错"还是"判错"。
`evals/extraction.py` 已进 `gate` 第 12 项（字段准确率 ≥ 90%，且至少 Excel + 文字 PDF 两条路由），
并纳入 `baseline_check` 回归；OCR 依赖缺失时对应路由 skip，但不会让门禁"假绿"。

## 7. 环境与命令（Windows 坑）

### Python

- 系统 `python`（当前已装）：`pypdf` 7.0 + `openpyxl` + `Pillow` + `rapidocr_onnxruntime`；
- bundled Python（有 `openpyxl` / `Pillow` / `pypdf` 7.0，**没有** RapidOCR）：
  `C:\Users\HHK2023\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe`
- OCR 依赖按需安装：`pip install -r requirements-ocr.txt`。

### Edge（无头 PDF / 截图）

`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`

### 坑

- **PowerShell 的 `cd` 不会同步 .NET 当前目录**：`[IO.File]::ReadAllText("相对路径")` 会失败，一律用绝对路径；
- 中文文件名在 Edge 输出里可用，但中间 HTML 建议放临时目录；
- 生成样本需要 `openpyxl` + `Pillow` + Edge。

### 常用命令

```powershell
# 生成全部合成样本（单件 + 五单 PDF/Excel + 2 页/5 页扫描件）
python scripts/gen_synthetic_rawdocs.py

# 类型检测
python -m src.ingest.detect examples/raw/pdf/*.pdf

# Excel 抽取（只需要 openpyxl）
python -m src.ingest.excel examples/raw/合成发票-INV-2026-0901.xlsx

# OCR 抽取（需要 pypdf + requirements-ocr.txt）
python -m src.ingest.ocr_pdf examples/raw/合成扫描件-多页.pdf

# 端到端
python -m src.ingest.pipeline examples/raw/pdf/*.pdf
python -m src.ingest.pipeline examples/raw/合成五单-2026-0901.xlsx
python -m src.ingest.pipeline examples/raw/合成扫描件-五单.pdf
python -m src.ingest.pipeline examples/raw/合成扫描件-多页.pdf `
  examples/raw/pdf/合同-HT-2026-0901.pdf `
  examples/raw/pdf/发票-INV-2026-0901.pdf `
  examples/raw/pdf/提单-SYN-2026-0901.pdf

# 抽取层评测（字段准确率 + CER）
python evals/extraction.py

# Web 上传（起服务后页面上传，或直接 curl）
make api                                    # 或 make demo（无依赖兜底）
curl.exe -F "files=@examples/raw/合成发票-INV-2026-0901.xlsx" ^
         -F "case_id=UPLOAD-001" http://127.0.0.1:8000/api/ingest
curl.exe http://127.0.0.1:8000/api/cases/UPLOAD-001/ingest

# Docker：默认含 Excel/PDF 依赖；compose 默认 WITH_OCR=1（含扫描件 OCR）
docker compose up --build
# 裸 docker build 要 OCR 时显式加参数；compose 想省体积用 WITH_OCR=0
docker build --build-arg WITH_OCR=1 -t logistics-agent:ocr .
WITH_OCR=0 docker compose up --build

# 验收三件套
python -m unittest discover -s tests
python scripts/gate.py
python scripts/baseline_check.py
```

上传后留档位置：`var/uploads/<case_id>/`（原始文件）、`var/docs/<case_id>.ingest.json`
（逐文件/页识别记录，含置信度/缺字段/checks）。

## 8. 硬约束（继承 `AGENTS.md`）

- 离线可跑；核心逻辑只用标准库，`pypdf` / OCR 是可选依赖；
- 结论必须带引用；
- 只读输入，只出补正建议；
- 归类只给 6 位建议，不自动改判；
- **数据全合成**，不引入真实企业名/单号/个人信息；真实样本必须脱敏。

## 9. 已拍板 / 仍待定

**已拍板（2026-11-13）**

1. OCR 依赖已装：`requirements-ocr.txt`（RapidOCR + onnxruntime，几十 MB 级）；MinerU 接受但暂不接。
2. 没有真实**脱敏**样本：先用合成样本（含旋转/噪点/五页扫描）跑通，真实版式另测。
3. Excel 不支持 `.xls`：提示另存 `.xlsx`。
4. 抽取出错兜底：**规则 + 交叉校验 → 低置信转人工**，不接 LLM 猜字段、不静默放行。
5. `evals/extraction.py` 已实现并进 gate（字段准确率 ≥ 90%）+ baseline；OCR 路由缺依赖时 skip，
   但要求至少 Excel + 文字 PDF 两条路由。

**仍待定**

- 真实脱敏扫描件（最好 200–300 DPI）与字段准确率/转人工率目标；
- MinerU 是否值得为复杂表格引入（许可证、包体、CPU 成本）；
- 红章/手写/多栏等难样本的专项处理优先级。

## 10. 与既有文档的关系

- `AGENTS.md`：入口与硬约束；
- `docs/00` 第 12 节 W7：里程碑记录；
- `docs/02`：评测口径（端到端），抽取层评测需要新增；
- `examples/raw/README.md`：样本说明与命令。

**变更纪律**：如果本计划与用户最新说法冲突，以用户为准，并回来改本文件。
