# 接入新业务检查清单（new business checklist）

> 用途：把「关务智能审核 Agent」接到一个新业务（新品类 / 新贸易方式 / 新口岸 /
> 新客户单证格式）时，用本清单逐项准备与验收。
> 用法：复制成需求单或 PR 描述，每勾一项都附证据（文件、命令输出、报告链接）。
> **指标数字一律由脚本生成**，不手写；阈值以 `scripts/gate.py` 为单一事实源。

## 0. 先定义「审什么、不审什么」

- [ ] 一句话业务定义：进口 / 出口、一般贸易 / 其他贸易方式、主要商品章节。
- [ ] 监管特征：是否涉及 3C、许可证、两用物项、食品化妆品、濒危、旧机电、双反。
- [ ] 明确不做的部分：扫描件 OCR、自动归类改判、代替报关员改单、外部系统直连。
- [ ] 结论口径确认：`PASS` / `FIX` / `REVIEW` / `REJECT` 在本业务里的处理人是谁。
- [ ] 数据合规确认：全部合成数据，不出现真实企业名、真实单号、个人信息（D9）。

**证据**：需求说明或 `docs/07` 下新增的业务说明，含范围与假设（D4：期望值来源要标注“假设”）。

## 1. 单证字段清单

### 1.1 五单键不可改名

工具 `doc.get` 的 `doc` 枚举与 `doc.summary` 的缺件判断都固定为
`contract` / `invoice` / `packing_list` / `bl` / `declaration`。新业务只能
**扩字段**，不能改键名；确需第六种单证时，必须同步改 `src/tools/audit_tools.py`
的 schema、`doc.summary` 的 `missing` 列表、示例数据与相关测试。

| 单证 | 本业务是否提供 | 必填字段是否齐全 | 额外字段（列出） | 由哪条规则消费 |
|---|---|---|---|---|
| `contract` | [ ] | [ ] | | |
| `invoice` | [ ] | [ ] | | |
| `packing_list` | [ ] | [ ] | | |
| `bl` | [ ] | [ ] | | |
| `declaration` | [ ] | [ ] | | |

### 1.2 字段接入四步

- [ ] 字段写进合成数据与示例：`data/synth/generator.py`、`examples/`（或本业务的样例目录）。
- [ ] 金额用 `number`、日期用 `YYYY-MM-DD`、币制/成交方式用大写代码（`USD` / `FOB`）。
- [ ] 商品项字段：`name` / `name_en` / `hs_code` / `qty` / `unit` / `unit_price` /
      `amount` / `origin` / `legal_unit1` / `legal_unit2` / `qty_legal1`，申报要素在
      `elements`（`brand_type` / `material` / `use` 等）；10 位编码未收录时走
      `data/rules/elements.json` 的通用要素兜底。
- [ ] 缺失值策略写清楚：**有值但非法要报，不能静默跳过**（参考 L1-02、L4-42 的教训）；
      字段真的没有时，规则要么跳过并说明，要么转 `REVIEW`，不允许默认 `PASS`。

## 2. 规则清单

- [ ] 先盘现有 46 条（L1 10 / L2 14 / L3 10 / L4 12），逐条标记：
      **直接复用 / 需要参数化 / 不适用 / 需要新增**。
- [ ] 新增规则按 [`add-rule-sop.md`](add-rule-sop.md) 执行，编号不得复用。
- [ ] 同一缺陷不要被两条规则重复上报（L3-23 与 L3-27/28/31 是分工范例；
      L2-24 只在双方都有值时比对）。
- [ ] 归类类需求只到「6 位建议 + 人工确认」，不得新增自动改判 HS 的规则（D3）。
- [ ] 每条新规则写明：编号、分层、判定逻辑、容差、违反结论、来源、依赖字段、负责人。

**证据**：规则清单表（可放本清单附录）+ `docs/01-rule-library.md` 的变更记录与表格。

## 3. 评测集

- [ ] 数据全合成、可复现（生成器无随机；用例固定 ID）。
- [ ] 用例覆盖四种结论，每类至少 1 条；每个高风险监管点至少 1 条；
      另加脏数据（空值、单位混用、中英混写、格式错误）。
- [ ] 每条用例带 `expected.verdict`、`expected.issues`（规则编号 + `field_path` +
      `severity`）、`injected_defects`，以及**误报闸门** `must_not`。
- [ ] 引用期望：非 `PASS` 用例要有可回查的 `citations`（`chunk_id`）。
- [ ] 新用例进入 `data/synth/scenarios.py` 与 `docs/02-eval-spec.md` 的分布说明。
- [ ] 跑 `python evals/runner.py --json`，报告由脚本生成到 `evals/report/`，不手改。

**证据**：`evals/report/report.md` 与用例 diff。

## 4. 验收门槛

| 项 | 门槛 | 命令 | 证据 |
|---|---|---|---|
| 单元测试 | 全绿，且总数不低于基线 | `python -m unittest discover -s tests` | 末行 `Ran N tests ... OK` |
| 基线回归 | 未退化 | `python scripts/baseline_check.py` | `✅ 未发现退化` |
| 指标门禁 | 全项通过（当前 `scripts/gate.py` 共 11 项） | `make gate` 或 `python scripts/gate.py` | 逐项 ✅ |
| 主评测 | 准确率 ≥ 95%、召回 ≥ 95%、误报 ≤ 1%、引用覆盖 ≥ 95% | `python evals/runner.py --json` | `result.json` / `report.md` |
| 成本与性能 | 单票成本 ≤ ¥0.1、并发 10 的 P95 ≤ 5s、错误 0 | `python evals/perf.py` | `perf.json` |
| 红队 | 10/10 拦截或降级，`auto_change_hs = 0` | `python evals/redteam.py --json` | `redteam.json` |
| 幻觉指标 | 无引用断言率 0%、引用不可回查率 0% | `make gate` | `hallucination.json` |
| 回归集 | 原 60 条仍 100% / 100% / 0 / 100% | `python evals/runner.py --json` | 同一份报告 |
| 手改单 | 问题数不低于基线（下降视为漏报） | `python scripts/baseline_check.py` | `hand_doc.issue_count` |
| 干净样例 | 规则集合不变（变了要解释是误报还是口径变化） | `python scripts/baseline_check.py` | `clean_doc.rules` |

- [ ] 以上全部通过后，才允许更新基线（`make baseline`），并在变更说明里写清
      “为什么这次变化是预期的”。
- [ ] 文档同步：`docs/01`（规则与变更记录）、`docs/00` 第 12 节（交付记录与实测数字）、
      `AGENTS.md` / `README.md` 的状态与指标（由维护者确认后再改）。
- [ ] 新增技能的，同步按 [`skill-authoring.md`](skill-authoring.md) 自检。

## 5. 交付物清单

- [ ] 代码：规则实现、必要的领域代码表、工具（若扩了单证键）。
- [ ] 数据：合成单证生成器 / 示例 / 新评测用例。
- [ ] 测试：新增单测与回归用例，数量只增不减。
- [ ] 报告：`evals/report/` 下由脚本生成的报告。
- [ ] 文档：`docs/01` 规则行、`docs/02` 分布、`docs/00` 交付记录、本清单勾选结果。
- [ ] 回滚方案：新增规则可独立 revert；基线只在验收通过后刷新。

## 6. 风险与未覆盖（必须如实记录）

| 风险 | 处理 |
|---|---|
| 无真实税则 / 监管条件库 | `src/domain/codes.py` 是小样本，文档标注“生产应换真实库” |
| 合成数据太干净 | 主动注入噪声，脏数据单独统计 |
| 代码表字段未覆盖（运输方式 / 包装种类 / 关区 / 证件号格式） | 列为已知待办，不假装已实现 |
| 规则冲突 | 取最严重结论并注明冲突，不静默合并 |
| LLM 不可用 | 确定性规则兜底；mock 可复现；不得因此伪造 `PASS` |
| 自由文本（条款、备注） | 明确“不覆盖”，避免把不可判说成已判 |

## 7. 一页勾选汇总

- [ ] 业务边界与结论处理人已确认
- [ ] 五单字段契约已核对，缺失值策略明确
- [ ] 46 条规则盘点完成，新增规则走完 SOP
- [ ] 评测集含四结论、`must_not`、脏数据
- [ ] 单测 / 基线 / 门禁 / 评测 / 性能 / 红队全部通过
- [ ] 文档与假设已同步，未覆盖项已如实记录
- [ ] 回滚与基线刷新策略已确认
