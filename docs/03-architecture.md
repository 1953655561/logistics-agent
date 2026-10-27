# 03 · 架构与实现说明（W6 现状）

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
| 审核单列表 | `Table` + `Select`（选用例） | 状态/结论 Tag、分页、按合成用例新建审核 |
| 单票详情 | `Descriptions` + `Tabs` | 问题清单 / 五份单证 / 处理轨迹 / 复核与护栏 |
| 差异对比 | `List` + `Tag` + `evidence` | 问题条目直接列出两侧取值、引用与补正建议 |
| 问题清单 | `List` + `Tag` | 按规则编号与严重度展示，每条带引用来源 |
| 审批 | `Drawer` + `Radio` + `Input.TextArea` | 通过 / 退回补正；退回必填理由 |
| 处理轨迹 | `Timeline` | 每一步工具调用、耗时、失败标记 |
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
      ├─ 独立复核（H1）→ 存疑升 REVIEW，不改问题列表
      │
      ├─ 需人工审批 → PENDING_APPROVAL → ApproverPort → APPROVED / RETURNED
      └─ 无需审批   → APPROVED
      ▼
SqliteRepo（cases + events）        JsonlTracer（var/traces/*.jsonl）
      │
      ├─ CLI（python -m src.app.cli）
      └─ WebApi（application/web_api.py）
            ├─ FastAPI 适配器（adapters/fastapi_api.py）
            └─ 无依赖兜底 HTTP（app/fallback_server.py）
                  └─ AntD 审核台（web/dist）/ 无构建页（web/fallback）
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
| `src/application/web_api.py` | Web 审核台应用服务（框架无关） | 列表/详情/审核/审批/单证/trace/指标 |
| `src/adapters/fastapi_api.py` | FastAPI 路由与 DTO | 只 import 框架；业务在 `WebApi` |
| `src/app/wiring.py` | 依赖组装（不 import Web 框架） | CLI / FastAPI / 兜底服务共用 |
| `src/app/api.py` | FastAPI 启动入口 | `--dump-openapi` 导出契约 |
| `src/app/fallback_server.py` | stdlib HTTP 兜底 | 无第三方依赖；服务 AntD 构建或兜底页 |
| `web/` | AntD 审核台 | React 18 + TS + Vite + TanStack Query + CSS Modules |
| `evals/perf.py` | 并发/延迟评测 | 串行 vs 并发 10；P95/成本/错误率 |
| `src/app/cli.py` | 组装根与命令行 | `audit / resume / list / show` |
| `src/rules/l3_elements.py` | 申报要素与归类（10 条） | 目录驱动；L3-29 只建议不改判 |
| `src/domain/elements.py` | 要素目录加载与默认填充 | 生成器与规则共用，避免两处漂移 |
| `src/rag/tokenize.py` | CJK 二元组 + 英文词 | 无第三方分词 |
| `src/rag/corpus.py` | 从规则文档与要素目录切 chunk | 产出 `chunk_id`，可回查原文 |
| `src/rag/index.py` | BM25 + 特征哈希向量 + 重排 | md5 定桶，跨进程可复现 |
| `src/rag/retriever.py` | `search()` / `cite()` | 实现 `ports.RetrieverPort` |
| `src/agents/reviewer.py` | 独立复核 Agent | 只看 `verdict/issues/citations`；`doubts` 阻断、`observations` 只提示 |
| `src/harness/guardrails.py` | 输入隔离 / 注入检测 / 输出校验 / 工具白名单 | 单证内容一律当数据；禁止 `auto_change_hs` |
| `src/harness/cost.py` | token → 金额 | 单价可配置，trace 记录 usage/cost |
| `src/harness/ratelimit.py` | 令牌桶 | 默认 60 次/分；超限降级 REVIEW 并写 trace |
| `src/mcp/server.py` | MCP stdio JSON-RPC | `initialize` / `tools/list` / `tools/call`，5 工具复用 schema |
| `evals/review_compare.py` | 单/双链路对照 | 复核异议率、推翻率、过判观察、误报变化 |
| `evals/judge.py` | LLM-as-Judge | rubric 与 LLM 同构 `{score, reasons}` |
| `evals/redteam.py` | 红队执行器 | 10 条攻击拦截判定，`auto_change_hs` 判 0 分 |

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

## 8. 多 Agent 复核（W4.5 H1）

```
主链路 AuditLoop ──verdict + issues + citations──► ReviewAgent（独立上下文）
                                                      │
                        ┌─────────────────────────────┴──────────────────┐
                        ▼                                                ▼
                 doubts（阻断性）                               observations（过判观察）
    证据缺口 / 未知规则号 / 结论与问题不匹配            同一规则重复上报 / 仅凭关键词判禁限
                        │                                                │
           PASS/FIX → REVIEW；REJECT → REVIEW                 只记录，不改结论、不改问题列表
```

- 复核 Agent **不接触原始单证**，避免被单证里的文字注入带偏；
- 冲突处理只调整结论、不覆盖主链路问题列表，保证可追溯；
- 可接 LLM（`ReviewAgent(llm=...)`），离线 mock 下自动走确定性检查。

**对照实验**（`evals/review_compare.py`）：60 条用例跑单链路/双链路两遍，报告
复核异议率、推翻率、过判观察、误报变化。W4.5 实测：异议 5/60、推翻 0/60、过判观察 5 条、
误报 0 → 0、准确率 100% → 100%。

## 9. MCP 服务（H2）

`src/mcp/server.py` 用 **stdio + JSON-RPC 2.0** 暴露 5 个工具：
`doc.get / doc.summary / rules.audit / rule.search / case.draft`。

- 工具 schema 直接来自 `ToolRegistry.specs()`，不手写第二份，避免漂移；
- 工具名先过白名单，再走统一的参数校验/超时/重试；
- `tools/call` 返回 MCP 的 `content[{type:text}]` 包装，`isError` 与工具结果一致；
- 集成测试用子进程 + 管道输入，验证 `initialize` / `tools/list` / `tools/call` 三段。

## 10. 红队与护栏（H3）

`src/harness/guardrails.py` 做四件事：

| 能力 | 实现 | 触发后 |
|---|---|---|
| 输入隔离 | `sanitize_docs` 清洗控制字符/零宽字符，超长字段截断 | 至少 REVIEW |
| 注入检测 | 中英日俄模式 + 角色覆盖 + `system prompt` 等 | 至少 REVIEW，且不把可疑文本送 LLM |
| 伪造引用 | `rules#L9-99` 这类不存在的规则号 | 至少 REVIEW |
| 输出校验 | 结论枚举 / severity / 引用可回查 / 禁用动作 | 至少 REVIEW；出现 `auto_change_hs` 该条判 0 |

10 条攻击用例在 `data/synth/redteam.py`，执行器在 `evals/redteam.py`：
W4.5 实测 **10/10 拦截或降级**，`auto_change_hs` 出现 0 次。

## 11. LLM-as-Judge（H4）

`evals/judge.py` 输出统一结构 `{score, reasons}`：

- 评分：结论正确 50% + 缺陷召回 35% + 引用完整 15%，PASS 用例每多报 1 条中高危扣 10 分；
- 默认确定性 rubric（零 token、可复现）；接真实模型走 LLM 打分，失败回退 rubric 并标 `degraded`；
- 与 60 条 `expected` 比对，报告一致率、不一致清单、扣分明细。W4.5 实测一致率 100%。

## 12. 成本 / 限流 / 幂等（H5）

- **成本**：`AuditLoop._summarize` 记录每次 LLM 的 `usage`，`CostMeter` 按 `PriceTable`
  折算；trace 写 `llm.usage`，payload 写 `usage/cost`，主评测报告出“单票成本”。
- **限流**：`TokenBucket(60/min)` 只拦 LLM 调用（本地确定性工具不是外部依赖）。
  超限 → `rate_limited=True`、结论降 REVIEW、trace 写 `ratelimit.exceeded`。
- **幂等**：`CaseService.submit(case_id, docs)` 以 `case_id` 为幂等键；命中终态/在途单
  直接返回已有记录，不重跑、不重复计费，并记录 `idempotent.hit` 与 `digest_matches`。

## 13. Web 审核台（W5）

```
web/（AntD + TanStack Query）
      │ fetch /api
      ▼
FastAPI 适配器 ──► application.WebApi ──► CaseService ──► AuditLoop
      ▲                  ▲
      └── 兜底 HTTP ─────┘（同一份 WebApi，无第三方依赖）
```

- **一份业务入口**：`WebApi` 提供列表、详情、单证、trace、审核、审批、指标；FastAPI 与
  stdlib 兜底服务只是传输层，DTO 只做转换，不放业务判断。
- **页面**：审核单列表（筛选/新建/导入）、单票详情（问题清单 / 五单证 / 处理轨迹 / 复核与护栏）、
  审批 Drawer、评测指标（准确率/召回/误报/成本/P95/逐条结果）。
- **单证导入**：`POST /api/cases/import`（`{case_id?, docs}`）做结构校验、`sanitize_docs`、
  落盘 `var/docs/{case_id}.json`，并自动处理编号冲突；Web 端支持粘贴/上传/载入示例。
- **契约驱动**：FastAPI 自动出 OpenAPI → `openapi-typescript` 生成 `web/src/types/api.ts`，
  前端不手写 DTO。
- **兜底**：`make demo` 用 `http.server` 起服务；有 `web/dist` 就服务 AntD 构建，没有就服务
  `web/fallback/index.html`，客户现场不装 Node 也能演示。
- **截图**：`docs/images/w5-console.png`、`w5-metrics.png`、`w5-approval.png`。

**W5 关键修正**：`SqliteRepo` 连接加 `check_same_thread=False` + `RLock`。FastAPI 的同步路由跑在
线程池里、兜底服务也是多线程，不修会直接报 `SQLite objects created in a thread can only be used
in that same thread`；这是 W5 实测暴露出来的，不是设计出来的。

## 已知限制

- 语料是 **64 个 chunk 的小库**，只覆盖规则与要素，没有真实法规全文。
- 名录表是缩小版（3C/禁限/双反各十来条），只够跑评测。
- 并发/延迟评测已补（`evals/perf.py`），但仍是单进程内存压测，没有真实网络与数据库开销。
- Web 层已交付；未做移动端适配、鉴权与多租户（生产落地再补）。
- 成本已按可配置单价折算；mock 模型的 token 是按字符估算，只有接真实模型后才准确。
- 限流是**单进程内存令牌桶**，多实例部署需要换成 Redis 等共享计数（接口已隔离在 `ratelimit.py`）。
- 复核 Agent 的 LLM 路径未做大规模人工评估；当前报告基于确定性检查 + mock。

## 14. 扩展点（改这些不用动核心）

| 想换的东西 | 改哪里 | 不用碰 |
|---|---|---|
| 换 LLM 供应商 | `adapters/llm_openai.py`（OpenAI 兼容即可接 DeepSeek/Qwen） | domain、rules |
| 换向量库 | 实现 `ports.RetrieverPort` | rules、engine |
| 换存储 | 实现 `ports.RepositoryPort` | 审核逻辑 |
| 加一条规则 | `src/rules/*.py` + `docs/01` 登记 + 用例 | 引擎、API |
| 加一个前端页面 | `web/src/pages/` + 生成的 TS 类型 | 后端（接口不变） |
| 换部署方式 | `docker/`、`Makefile` | 代码 |

**前后端契约**：FastAPI 自动出 OpenAPI → `openapi-typescript` 生成前端类型，
禁止手写 DTO，避免字段漂移。

## 15. 部署与 CI（W6）

### 15.1 Docker（多阶段）

```
node:24-alpine ──pnpm build──► /app/web/dist
                                   │
python:3.12-slim ──COPY────────────┘
  ├─ pip install -r requirements-web.txt
  ├─ COPY src / data / evals
  ├─ 非 root 用户 appuser
  └─ CMD python -m src.app.api --host 0.0.0.0 --port 8000
```

- `Dockerfile`：前端构建与 Python 运行时分离，运行镜像不带 Node；
- `docker-compose.yml`：映射 8000、挂 `./var`（审核单与 trace 持久化）、healthcheck；
- `.dockerignore`：排除 `node_modules` / `dist` / `var` / 图片，构建上下文可控；
- 容器内 `GET /api/health` 作为 healthcheck，失败会自动标记 unhealthy。

```bash
make docker-build      # docker build -t logistics-agent:latest .
make docker-run        # docker run --rm -p 8000:8000 -v $(CURDIR)/var:/app/var ...
make docker-up         # docker compose up --build
```

### 15.2 CI（GitHub Actions）

`.github/workflows/ci.yml` 三条 job：

| job | 做什么 |
|---|---|
| `python` | 安装 `requirements-dev.txt` → `make test` → `make eval` → `make gate` → 上传报告 |
| `web` | 生成 OpenAPI → `pnpm gen:types` → `pnpm build` |
| `docker` | `docker/build-push-action` 构建镜像（不推送） |

**指标门禁** `scripts/gate.py` 卡 9 项：准确率、召回、误报、引用覆盖、单票成本、
并发 10 P95、性能错误数、红队拦截数、`auto_change_hs`。任一项不达标 CI 直接 fail，
避免“改了规则把指标改坏”悄悄合入。

### 15.3 一键演示

```bash
make demo          # 起 Web 审核台（无依赖兜底）
make demo-script   # 终端跑 PASS/FIX/REVIEW/REJECT 四票
make eval          # 主评测 + 复核 + Judge + 红队 + 性能
```

10 分钟讲解顺序见 `docs/05-demo-script.md`；问答见 `docs/06-interview-qa.md`。

**已知限制**：CI 只在本地等价命令验证过，未在真实 GitHub Runner 跑；Docker 首次构建需要网络拉取基础镜像与 pip/npm 依赖。

## 16. v1.6 架构增补（2026-10-27）

### 16.1 模型路由（src/harness/router.py）

按任务类型选模型档位：summarize/classify/extract → cheap，
eview/ask → strong。
没配 LOGIAGENT_LLM_API_KEY 时统一退化为 MockLLM，**结论不变**；
路由只影响成本与措辞，不参与业务判断。成本对比用 
outer.spec(task).estimate()。

### 16.2 记忆（src/harness/memory.py）

两张 SQLite 表：case_memory（单票 scratchpad，带 token 预算）与
party_history（主体归一化名 → 命中规则 + 摘要 + 时间，TTL 90 天）。
**硬约束**：记忆只产出 history_hints 提示字段，不进 issues、不改 verdict，
让结论始终能只凭本票单证复现。

### 16.3 两种审核模式（src/harness/planner.py + loop.py）

- scripted（默认）：固定七步，可复现、零额外 token；
- 
eact：在规则审核之后做**证据补采**——规划器按问题挑要回查的字段，
  doc.get 取值挂到 issue.verification。只补证据、不改结论。
对比数据见 evals/modes.py（结论一致率 100%，步数 3.7 → 4.4）。

### 16.4 追问（src/application/ask.py）

POST /api/cases/{id}/ask：意图（explain/fix/diff/unrelated）→ 取证据 → 拼回答。
无证据时返回 uncited=true；问题与单证无关时直接拒答；命中注入特征只告警不执行。

### 16.5 向量存储（src/rag/vectors.py）

**自建 sqlite 向量表**（不是向量数据库服务）：ectors(chunk_id, vec BLOB, text, meta)，
余弦检索，embedding provider 可插拔（hash / sim）。同一个检索集上可量化对比，
见 evals/vectors.py。说清楚边界：两个 provider 都不是真模型。

### 16.6 增量索引（src/rag/store.py + python -m src.rag.reindex）

按 chunk 内容指纹做 diff：dded/updated/removed/unchanged。
第二次跑同一条命令 changed=0；改一行规则只重建受影响的 chunk。

### 16.7 异步化（src/adapters/fastapi_api.py）

所有 /api 端点改为 sync def + syncio.to_thread(...)，把 sqlite / 规则计算
放到线程池，避免阻塞事件循环。真实 ASGI 并发 10 的端到端数据见
scripts/async_bench.py（evals/report/async.json）。
