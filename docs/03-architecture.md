# 03 · 架构与实现说明（W2 现状）

## 数据流

```
scenarios.py (用例定义)
      │  build_case()
      ▼
generator.py ──► docs = {contract, invoice, packing_list, bl, declaration}
      │
      ▼
engine.audit(docs)
      │  registry.run_all()   ← 34 条规则（L1/L2/L4）
      ▼
RuleResult[] ──► worst(conclusion) ──► Report{verdict, issues, by_layer}
      │
      ▼
evals/runner.py ──► evals/report/report.md
```

## 模块职责

| 文件 | 职责 | 关键约定 |
|---|---|---|
| `src/common.py` | 容差、名称/单位归一化、路径取值 | 容差常量集中在此，改阈值只改一处 |
| `src/issue.py` | `Issue` / `RuleResult` / `worst()` | 结论强弱 `PASS<FIX<REVIEW<REJECT` |
| `src/registry.py` | `@rule` 装饰器 + 规则执行 | 规则抛异常 → 降级为 `REVIEW` + `error`，不中断整单 |
| `src/engine.py` | 聚合、排序、生成报告 | 每个 issue 带 `citation`（规则来源） |
| `src/rules/l1_*` | 完整性与格式 | 纯确定性 |
| `src/rules/l2_*` | 单证一致性 | 纯确定性 |
| `src/rules/l4_*` | 监管与合规 | 纯确定性 + 名录表 |
| `src/domain/codes.py` | 币制/国别/3C/禁限/双反/食品章 表 | 小样本，生产应换真实税则库 |
| `data/synth/generator.py` | 基线单证 + 缺陷注入 | 无随机，完全可复现 |
| `data/synth/scenarios.py` | 60 条用例定义 | 与 `docs/02` 第 6 节索引对应 |
| `evals/runner.py` | 评测与报告生成 | 报告自动写 `evals/report/report.md` |

## 为什么规则函数签名是 `(ctx) -> RuleResult`

- 规则之间不共享状态，可并行、可单测；
- 需要跨单证信息时从 `ctx` 取，不靠参数堆叠；
- 新增规则 = 新建一个函数 + 一个装饰器，不改引擎。

## 新增一条规则的步骤

1. 在 `docs/01-rule-library.md` 登记编号、判定逻辑、结论、来源；
2. 在对应 `src/rules/lX_*.py` 加 `@rule("L?-??", ...)`；
3. 在 `data/synth/generator.py` 加一个 `m_xxx` 缺陷注入函数；
4. 在 `scenarios.py` 加用例（含 `defects` 与 `expected`）；
5. `make test && make eval`，确认召回和误报都没退化。

## 已知限制

- `L3` 未实现：申报要素目录、归类相似库、LLM 判断都在 W4。
- 名录表是缩小版（3C/禁限/双反各十来条），只够跑评测。
- 没有并发与性能测试（W5 补）；当前 60 条用例 0.08s，单票毫秒级。
- 没有持久化（W3 加 sqlite 状态机）。
