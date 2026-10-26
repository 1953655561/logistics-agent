# 03 · 架构与实现说明（W2 现状）

## 0. 技术栈与分层（D11/D12）

**原则：核心零依赖，框架只在边缘。** 依赖方向单向，`domain` 不认识任何框架。

```
app/       组装根：CLI、FastAPI、兜底 HTTP 服务      ← 可以 import 一切
adapters/  llm_mock / llm_openai / sqlite_repo / jsonl_tracer / fastapi_api
ports/     接口协议：LLMPort / RepositoryPort / TracerPort / RetrieverPort
application/ 用例编排：audit_case / approve / recheck   ← 只依赖 domain + ports
domain/    实体、值对象、规则、结论聚合               ← 零依赖
```

| 层 | 选型 | 说明 |
|---|---|---|
| 语言 | Python 3.11+（本机 3.12） | `tomllib`、`dataclass`、`sqlite3` 都是标准库 |
| 核心逻辑 | 纯标准库 | 规则、归一化、聚合、评测 |
| 配置 | TOML（`tomllib`） | 阈值、开关、模型参数；不引入 YAML |
| 持久化 | SQLite（`sqlite3`） | 审核单状态机、审批记录、trace 索引 |
| Trace | JSONL 文件 + SQLite 索引 | 每单一个 `.jsonl`，可回放 |
| Web 后端 | FastAPI + uvicorn | 只做 DTO 转换与路由；**不在 core 里 import** |
| Web 兜底 | `http.server` | 无第三方依赖也能起服务、跑演示 |
| 前端 | **Ant Design 5** + React 18 + TS + Vite + TanStack Query + CSS Modules | 后台审核台，Table/Descriptions/Timeline/Tag 直接覆盖主场景；**不引 Tailwind**，避免 preflight 覆盖 AntD 样式 |
| 前端兜底 | 单页 HTML + 原生 JS | 不装 Node 也能看审核结果与审批 |
| RAG | 自研 BM25 + 特征哈希向量；可选 bge-m3 / Qdrant | `RetrieverPort` 可换实现 |
| 测试 | unittest（`make test`），CI 里 pytest 兼容 | 不强制依赖 pytest |
| 静态检查 | ruff + mypy（dev 依赖） | CI 卡门禁 |
| 部署 | Docker 多阶段（node 构建 → python 运行时） | `make demo` 单机起兜底服务 |

**依赖预算**：核心 0 个第三方包；Web 层 6 个（fastapi/uvicorn/pydantic 及其传递依赖按需）；前端 6 个；
dev 4 个（ruff/mypy/pytest/httpx）。任何新增依赖必须能在 `docs/03` 第 5 节说明“为什么不能用标准库”。

### 前端组件映射（AntD）

| 页面/区域 | 组件 | 说明 |
|---|---|---|
| 审核单列表 | `Table` + `Form`（筛选） | 支持排序、状态 Tag、分页 |
| 单票详情 | `Descriptions` + `Tabs` | 五个页签：合同/发票/箱单/提单/报关单 |
| 差异对比 | `Table` 的 `rowClassName` + `Tag` | 不一致字段整行高亮，hover 显示两侧取值 |
| 问题清单 | `List` + `Collapse` + `Tag` | 按 L1–L4 分组，每条带引用来源 |
| 审批 | `Drawer` + `Form` + `Modal.confirm` | 通过 / 退回 / 补正，必填审批意见 |
| 处理轨迹 | `Timeline` | 每一步工具调用、耗时、结论 |
| 评测指标 | `Statistic` + `Progress` | 不引图表库，需要时再上 ECharts |
| 全局主题 | `ConfigProvider` + `theme.token` | 不用全局 CSS 覆盖，避免升级痛 |

**注意**：AntD v5 用 CSS-in-JS，不要同时引入 Tailwind/其他全局 reset，否则样式互相打架。

## 数据流

```
scenarios.py (用例定义)
      │  build_case()
      ▼
generator.py ──► docs = {contract, invoice, packing_list, bl, declaration}
      │
      ▼
application.CaseService.run(case_id, docs)
      │  DRAFT → REVIEWING
      ▼
harness.AuditLoop ──工具调用──► doc.summary / rules.audit / rule.search / case.draft
      │  每步 emit trace（JSONL）
      ▼
LoopResult{verdict, issues, citations, steps, degraded}
      │
      ├─ 需人工审批 → PENDING_APPROVAL → ApproverPort → APPROVED / RETURNED
      └─ 无需审批   → APPROVED
      ▼
SqliteRepo（cases + events）        JsonlTracer（var/traces/*.jsonl）
      │
      ▼
CLI / 将来的 FastAPI / AntD 审核台
```

`engine.audit` 现在是 `rules.audit` 工具的实现；评测器仍直接调用它，保持毫秒级速度。

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
| `src/ports.py` | 端口协议：LLM / 仓储 / Trace / 审批 | 核心只认识协议 |
| `src/harness/tools.py` | 工具注册、参数校验、超时、重试 | 校验失败不执行；超时/异常自动重试 |
| `src/harness/loop.py` | Plan→Tool→Observe→Reflect | 步数预算 8，超预算降级为 REVIEW |
| `src/harness/approval.py` | 审批策略与审批人实现 | REJECT/REVIEW 必审；FIX 含高危必审 |
| `src/harness/state.py` | 六态状态机 | 非法流转直接抛错 |
| `src/harness/tracing.py` | JSONL trace | 每步一条，可回放 |
| `src/adapters/sqlite_repo.py` | 审核单 + 事件持久化 | 标准库 sqlite3 |
| `src/adapters/llm_*.py` | mock / OpenAI 兼容 | 没配 key 自动降级 mock |
| `src/application/audit_case.py` | 用例编排：跑循环 → 审批 → 落库 | 不含框架、不直接读文件 |
| `src/app/cli.py` | 组装根与命令行 | `audit / resume / list / show` |
| `src/rules/l3_elements.py` | 申报要素与归类（10 条） | 目录驱动；L3-29 只建议不改判 |
| `src/domain/elements.py` | 要素目录加载与默认填充 | 生成器与规则共用，避免两处漂移 |
| `src/rag/tokenize.py` | CJK 二元组 + 英文词 | 无第三方分词 |
| `src/rag/corpus.py` | 从规则文档与要素目录切 chunk | 产出 `chunk_id`，可回查原文 |
| `src/rag/index.py` | BM25 + 特征哈希向量 + 重排 | md5 定桶，跨进程可复现 |
| `src/rag/retriever.py` | `search()` / `cite()` | 实现 `ports.RetrieverPort` |

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

## 6. Harness 与审批状态机（W3）

**循环**（`harness/loop.py`，预算 8 步）：

```
doc.summary ──缺单证?──► REVIEW（降级，停）
     │
     ▼
rules.audit ──► verdict + issues
     │
     ├─ 高危问题 top2 → rule.search 补引用
     ├─ LLM 生成一句话摘要（失败降级，不改变结论）
     └─ case.draft 生成草稿
```

**降级策略**（都写进 trace，不静默）：
| 情况 | 处理 |
|---|---|
| 单证缺失 | 直接 REVIEW，`degraded=True` |
| 工具超时/异常 | 重试 1 次；仍失败则该步 `ok=False`，循环继续 |
| LLM 不可用 | 用模板摘要兜底，`degraded=True` |
| 步数超预算 | 停止，已有结论保留 |

**状态机**（`harness/state.py`）：

```
DRAFT ──► REVIEWING ──┬──► APPROVED
                      ├──► PENDING_APPROVAL ──┬──► APPROVED
                      └──► RETURNED ◄─────────┘
RETURNED ──► REVIEWING（补正后重审）
任意 ──► FAILED（不可恢复错误）
```

审批策略（`approval.py`）：`REJECT`/`REVIEW` 必审；`FIX` 且含 high 问题必审；其余自动通过。
审批人可换实现：`AutoApprover`（演示）、`ScriptedApprover`（测试）、`CliApprover`（交互）。

## 7. RAG 设计（W4）

```
corpus.py   规则文档表格行 + 要素目录 → 64 个 chunk（每个带 chunk_id / section / rule_id）
   │
index.py    tokenize(CJK 二元组) → BM25(0.65) + 特征哈希向量(0.35) → 重排
   │        —— 规则编号/编码精确命中 +1.0/+0.8
retriever   search(query, top_k) → [{chunk_id, section, text, score}]
   │        cite(chunk_id) → 回查原文
tool        rule.search  →  Agent 循环调它补引用
```

**为什么不用真 embedding**：当前约束是零依赖、断网可跑。特征哈希 + BM25 在“规则条款”这种
短文本、术语密集的语料上召回够用（评测里 100% 覆盖）。真要换 bge-m3，实现一个
`RetrieverPort` 即可，上层不动。

**重排为什么必须有**：纯 BM25 搜 “L4-41” 会召回 “L4-40”，因为分词后只是 `l4` + `41`。
加“编号精确命中”后第一条才是对的——这是实测出来的，不是设计出来的。

## 已知限制

- 语料是 **64 个 chunk 的小库**，只覆盖规则与要素，没有真实法规全文。
- 名录表是缩小版（3C/禁限/双反各十来条），只够跑评测。
- 没有并发与性能测试（W5 补）；当前 60 条用例 0.09s，单票毫秒级。
- Web 层未开始（W5）；目前只有 CLI。
- 成本统计只留了字段，mock 模型下无 token 成本，接真实模型后才准。

## 5. 扩展点（改这些不用动核心）

| 想换的东西 | 改哪里 | 不用碰 |
|---|---|---|
| 换 LLM 供应商 | `adapters/llm_openai.py`（OpenAI 兼容即可接 DeepSeek/Qwen） | domain、rules |
| 换向量库 | 实现 `ports.RetrieverPort` | rules、engine |
| 换存储 | 实现 `ports.RepositoryPort` | 审核逻辑 |
| 加一条规则 | `src/rules/*.py` + `docs/01` 登记 + 用例 | 引擎、API |
| 加一个前端页面 | `web/src/routes/` + 生成的 TS 类型 | 后端（接口不变） |
| 换部署方式 | `docker/`、`Makefile` | 代码 |

**前后端契约**：FastAPI 自动出 OpenAPI → `openapi-typescript` 生成前端类型，
禁止手写 DTO，避免字段漂移。
