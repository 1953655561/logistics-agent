# AGENTS.md — 交接入口

这个仓库是「关务智能审核 Agent」项目（进口一般贸易单证审核）。**新会话开始前，按顺序读：**

1. `docs/00-project-context.md` —— 背景、决策记录、范围、里程碑、待办（**必读，5 分钟）**
2. `docs/01-rule-library.md` —— 46 条审核规则（v1.6，已做业务验收修正）
3. `docs/02-eval-spec.md` —— 评测集规范、分布、评分口径
4. `README.md` —— 对外说明
5. `docs/03-architecture.md` —— 架构、Web、Docker/CI（深入时读）
6. `docs/04` 使用手册 · `docs/05` 演示脚本 · `docs/06` 面试问答卡（交付/面试时读）
7. `docs/09` 岗位对标汇报（对领导/面试时读；含 JD 逐条对照与边界）
8. `docs/10-raw-data-ingest.md` —— 原始数据接入（W7）交接与计划：**先 Excel，后 OCR**（做 W7 时必读）

## 硬约束（改代码前先确认没违背）

- **离线可跑**：核心逻辑只用 Python 标准库；LLM 走 Provider 抽象，mock 必须能跑通全部评测。
- **结论必须带引用**：任何 `FIX` / `REVIEW` / `REJECT` 都要能指回规则条目或法规原文。
- **只读输入**：Agent 不得修改原始单证，只出补正建议。
- **归类只给 6 位建议**：不得自动改判商品编码，必须人工确认。
- **数据全合成**：不得引入真实企业名、真实单号、个人信息。

## 当前状态

- 阶段：**W6.6 完成**（W6.5 + Skill 接线 + 工具白名单下沉），**303 条测试全绿**（6 条 PDF 用例需 `pypdf`，未装则 skip）；**W7 原始数据接入进行中**。
- 决策：D1–D13 已锁定，见 `docs/00-project-context.md` 第 5 节。
- 规则库：v1.6，46 条（L1 10 / L2 14 / L3 10 / L4 12）；变更记录 20–32 见 `docs/01`。
- 指标：主评测 100% / 100% / 0 / 100%；`make gate` **11/11**（含无引用断言率、引用不可回查率）；
  检索 recall@1 93.3% / recall@3 100% / MRR 0.961；模式对比结论一致率 100%（3.7→4.4 步）；
  ASGI 并发 10 P95 约 49ms；单票成本 ¥0.0002（mock 估算，非真实账单）。
- W6.6 接线：Agent Skill 默认注入说明文本（`LOGIAGENT_SKILL=off` 可关）、
  工具白名单下沉到 `ToolRegistry`（越权调用在工具层拒绝）；`/api/health` 增加 `skill{name,enabled}`。
- W7 原始数据接入（进行中）：`src/ingest/` 已有类型检测（`detect.py`，Excel / 文字层 PDF / 扫描 PDF / 图片，
  pypdf 可选 + 字节特征兜底）、文字层 PDF 抽取（`pdf_text.py`）与端到端管线
  （`pipeline.py`：文件 → 五单 JSON → 审核）；`examples/raw/` 有 4 份单件样本 + `pdf/` 五单成套样本。
  实测：五份 PDF → `FIX`，仅 `L2-13` 一条问题。**Excel 与 OCR（扫描件）抽取适配器尚未接**；
  先 Excel 后 OCR，计划与验收标准见 `docs/10-raw-data-ingest.md`。
- 新增入口：`make baseline` / `baseline-check`（回归门槛）、`make ask CASE=xxx Q="..."`（追问）、
  `make retrieval|modes|vectors|hallucination|shadow|async`（各项评测）、`python -m src.rag.reindex`（增量索引）。
  HTTP：`POST /api/cases/{id}/ask`、`POST /api/extract`、`GET /api/health`（含 `model{offline,routes,tiers}`）；
  UI 有「为什么？」按钮、历史提示条、右上角模型标签（读 health，不写死）。
- 能力边界：`README` 能力矩阵按「已实现 / 未实现 / 接口预留」三态标注；OCR、pgvector/Milvus、
  A2A/OAuth、云平台与 Secrets 未做；现场采用记录见 `docs/08`（1/5）。
- Web 审核台：`make demo`（无依赖兜底）或 `make api`（FastAPI）；前端 `make web-dev` / `make web-build`。
- 交付：`make docker-build` / `docker-up`；`make gate`；`make demo-script`；文档见 `docs/04`–`06`。
- 跑单票：`python -m src.app.cli audit IMP-0043 --auto --offline`
- 一键评测：`make eval`（主评测 + 复核 + Judge + 红队 + 性能 + 幻觉 + 模式 + 检索 + 影子）
- MCP：`python -m src.mcp.server --case IMP-0001`（stdio JSON-RPC）

## 新会话从这里开始（2026-10-27 交接）

**先跑这三条，确认基线没坏**：

```bash
python -m unittest discover -s tests        # 应 303 条 OK（6 条 PDF 用例需 pypdf，未装则 skip）
python scripts/gate.py                      # 应 11/11 全绿
python scripts/baseline_check.py            # 应「未发现退化」
```

**做 W7（原始数据接入）**：读 `docs/10-raw-data-ingest.md`，按第 4 节先做 Excel 适配器，
第 5 节再做 OCR；验收标准在该文档里。

**当前跑的是离线 mock**（`/api/health` 的 `model.offline=true`）：`gpt-4o-mini` / `gpt-4o`
只是路由表里的名字，仓库里没有任何模型权重，也没花过钱。接真模型只需设
`LOGIAGENT_LLM_API_KEY` + `LOGIAGENT_MODEL_*`（走 OpenAI 兼容协议，Ollama 也能接），改完重启。

**待办清单（按性价比排序，都不是"继续加功能"）**：

1. **价目表两套且默认价不一致** —— `cost.py`（¥0.002/¥0.008，实际记账）vs `router.py`
   （cheap ¥0.0011/¥0.0044、strong ¥0.018/¥0.072，只用于对比报告）。接真模型后会对不上账，应单源化。
2. **追问/抽取不计成本** —— `AskService` 与 `extract` 没接 `CostMeter`，页面连点追问成本仍是 0。
3. **真模型质量无评测覆盖** —— `evals/*` 显式用 `MockLLM()`，`make gate` 全绿不代表真模型可用；
   需补在线/影子评测（v1.7）。
4. **影子评测只有对账没有评分** —— `evals/golden/human-labelled.json` 29 条仍是 `unreviewed`，
   需要真人逐条标 correct/wrong（这是唯一无法用代码补齐的部分）。
5. **采用记录 1/5** —— `docs/08-adoption-log.md` 只有一条内部自测；要找 4 个真实业务方试用。
6. **v1.7 规则** —— 装货港一致（提单 POL vs 报关单装货港）、代码表字段（运输方式/包装种类/关区/证件号）。
7. 可选：`python -m src.app.smoke_llm`（发一句 hello，打印真实模型名/usage/成本）——尚未创建。

## 风格约定

- 文档与注释用中文；代码标识符用英文。
- 每个模块配单元测试；评测报告自动生成 Markdown，不手写数字。
