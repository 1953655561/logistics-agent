# 关务智能审核 Agent

进口一般贸易报关单证的智能审核：四单一致性、申报要素、归类建议、监管证件，输出「可申报 / 可补正 / 需复核 / 不可申报」。

> 状态：W4 完成 —— 44 条规则 + RAG 混合检索 + 引用链 + Agent 循环 + 六态审批；56 条测试全绿。
> 交接入口：[`AGENTS.md`](AGENTS.md) → [`docs/00-project-context.md`](docs/00-project-context.md)

## 为什么做这个

对接「AI 单证识别」之后的决策环节：识别只解决“单子读没读出来”，本项目解决“这张单能不能报、缺什么、该找谁补”。

## 设计要点

- **四层校验**：完整性 / 单证一致 / 申报要素与归类 / 监管合规
- **四分类结论**：PASS / FIX / REVIEW / REJECT
- **只给建议不给判决**：归类只到 6 位，强制人工确认
- **确定性优先**：字段比对走规则，不让 LLM 猜
- **离线可跑**：mock 模型可复现全部评测

## 数据与合规

- 全部单证数据为**合成数据**，不含任何真实企业名、单号或个人信息。
- 规则依据来自公开的报关单填制规范、税则、监管条件表；企业内审阈值属**假设**，在评测报告中标注。

## 目录

```
docs/   00 上下文 · 01 规则库 · 02 评测规范 · 03 架构(待) · 04 使用手册(待)
src/    harness · rules · rag · domain · tools · app
data/   synth（数据生成）· rules（规则 yaml）
evals/  cases · runner · report
```

## 快速开始

无需第三方依赖，Python 3.9+ 即可：

```bash
make test        # 单元测试（37 条）
make eval        # 跑 60 条评测，生成 evals/report/report.md
make show ID=IMP-0019   # 看单条用例的规则明细

# 跑一票单证的完整流程（含工具调用、trace、审批）
python -m src.app.cli audit IMP-0025 --auto --offline
python -m src.app.cli audit IMP-0025 --pause     # 挂起在待审批
python -m src.app.cli resume IMP-0025 --auto     # 续跑审批
python -m src.app.cli list
python -m src.app.cli show IMP-0025
```

接真实模型：设置 `LOGIAGENT_LLM_API_KEY` / `LOGIAGENT_LLM_BASE_URL` / `LOGIAGENT_LLM_MODEL`，
去掉 `--offline` 即可；未配置时自动降级到 mock。

当前指标（W4）：

| 指标 | 数值 |
|---|---|
| 结论准确率 | **100%**（60 条） |
| 缺陷召回率 | **100%** |
| 误报用例率 | **0%** |
| 引用覆盖率（非 PASS 高危问题） | **100%** |
| 规则数 / 语料 chunk | 44 / 64 |
| 单票耗时 | 毫秒级（60 条共 0.09s） |
