# 复核对照报告（自动生成）

> 双链路 = 主链路 + 独立复核 Agent；复核只看 `verdict / issues / citations`，不接触原始单证。离线 mock 模型，结论可复现。

## 汇总

| 指标 | 单链路 | 双链路 |
|---|---|---|
| 结论准确率 | 100.0% | 100.0% |
| PASS 用例误报（规则条数） | 0 | 0 |
| REVIEW 占比 | 30.0% | 30.0% |
| 复核异议（未完全同意） | — | 3/60（5.0%） |
| 复核推翻（结论改变） | — | 0/60（0.0%） |
| 过判观察（≥3 为验收线） | — | **3** |

> 说明：复核的“推翻”包含两个方向——原结论 PASS/FIX 存疑时升为 REVIEW；原结论 REJECT 存疑时降为 REVIEW（由人决定是否退回）。过判观察只标记、不改问题列表，避免破坏可追溯性。

## 复核异议明细

| 用例 | 标题 | 单链路 | 双链路 | 建议 | 意见 |
|---|---|---|---|---|---|
| IMP-0026 | 收货人不一致 | REVIEW | REVIEW | advisory | repeat_rule：过判观察：规则 L2-18 在字段 declaration.consignee 上以相同证据重复上报 2 次，疑似过判 |
| IMP-0048 | 旧机电 | REJECT | REJECT | advisory | keyword_only_prohibition：过判观察：仅凭关键词「旧机电」判禁限，建议人工确认 |
| IMP-0049 | 固体废物 | REJECT | REJECT | advisory | keyword_only_prohibition：过判观察：仅凭关键词「固体废物」判禁限，建议人工确认 |

## 过判观察（复核指出主链路可能过判）

| 用例 | 单链路 | 观察 | 说明 |
|---|---|---|---|
| IMP-0026 | REVIEW | repeat_rule | 规则 L2-18 在字段 declaration.consignee 上以相同证据重复上报 2 次，疑似过判 |
| IMP-0048 | REJECT | keyword_only_prohibition | 仅凭关键词「旧机电」判禁限，建议人工确认 |
| IMP-0049 | REJECT | keyword_only_prohibition | 仅凭关键词「固体废物」判禁限，建议人工确认 |

## 复核路径自检（合成探针）

| 场景 | 主链路 | 复核建议 | 最终结论 | 是否推翻 | 期望 | 结果 |
|---|---|---|---|---|---|---|
| 证据缺口 · 升级 | PASS | escalate | REVIEW | 是 | REVIEW | ✅ |
| 证据缺口 · 降级 | REJECT | downgrade | REVIEW | 是 | REVIEW | ✅ |
| 重复上报 · 只提示 | FIX | advisory | FIX | 否 | FIX | ✅ |

> 探针说明：60 条回归集上主链路证据完整，复核只提观察；这三条合成探针专门验证“升级 / 降级 / 只提示”三条路径都真实生效。

## 结论改变明细

无（本次 60 条回归集上复核只提意见、不改变结论）。