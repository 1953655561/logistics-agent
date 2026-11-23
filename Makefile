PY ?= python
PNPM ?= pnpm
CASE ?= IMP-0025
PORT ?= 8000
IMAGE ?= logistics-agent:latest

.PHONY: test eval runner review judge redteam perf hallucination shadow modes retrieval vectors extraction async gate baseline baseline-check ci web-install web-types web-build web-dev demo demo-script api mcp show audit ask list sample-cases docker-build docker-run docker-up clean

test:
	$(PY) -m unittest discover -s tests -v

# 一键跑全部评测：主评测 + 复核对照 + Judge + 红队 + 性能 + 幻觉 + 模式 + 检索 + 影子 + 抽取层
eval: runner review judge redteam perf hallucination modes retrieval shadow extraction

runner:
	$(PY) evals/runner.py --json

review:
	$(PY) evals/review_compare.py

judge:
	$(PY) evals/judge.py

redteam:
	$(PY) evals/redteam.py --json

perf:
	$(PY) evals/perf.py

# 幻觉指标：无引用断言率 / 引用不可回查率（gate 第 10、11 项依赖它）
hallucination:
	$(PY) evals/hallucination.py

# 影子评测：与人工标注 golden 比对（只对已标注条目打分）
shadow:
	$(PY) evals/shadow.py

# 两种审核模式对比（scripted vs react）
modes:
	$(PY) evals/modes.py

# 检索召回：recall@1/3 + MRR
retrieval:
	$(PY) evals/retrieval.py

# 向量 provider 对比（hash vs sim，纯向量口径）
vectors:
	$(PY) evals/vectors.py

# 抽取层评测：字段准确率 + 字段 CER（OCR 路由需要 requirements-ocr.txt）
extraction:
	$(PY) evals/extraction.py

# 真实 ASGI 并发基准（并发 10 的端到端 P50/P95）
async:
	$(PY) scripts/async_bench.py

# 指标门禁：准确率/召回/误报/引用/成本/P95/红队/幻觉/抽取层（12 项）
gate:
	$(PY) scripts/gate.py

# 基线：冻结当前指标；回归比对（每阶段收尾都跑）
baseline:
	$(PY) scripts/baseline.py

baseline-check:
	$(PY) scripts/baseline_check.py

# CI 等价命令
ci: test eval gate baseline-check

# 前端（AntD + Vite）：先装依赖，再生成 OpenAPI 类型并构建
web-install:
	cd web && $(PNPM) install

web-types:
	$(PY) -m src.app.api --dump-openapi web/openapi.json
	cd web && $(PNPM) gen:types

web-build: web-types
	cd web && $(PNPM) build

web-dev:
	cd web && $(PNPM) dev

# 无第三方依赖也能起服务；有 web/dist 时直接服务 AntD 构建产物
demo:
	$(PY) -m src.app.fallback_server --port $(PORT)

# 终端版一键演示：四种结论各跑一票
demo-script:
	$(PY) scripts/demo.py

# FastAPI + 构建产物（需要 fastapi/uvicorn；未构建时只提供 /api 与文档）
api:
	$(PY) -m src.app.api --port $(PORT)

# 起 MCP stdio 服务：make mcp CASE=IMP-0001
mcp:
	$(PY) -m src.mcp.server --case $(CASE)

# 跑一票单证全流程：make audit CASE=IMP-0025
audit:
	$(PY) -m src.app.cli audit $(CASE) --auto --offline

# 追问：make ask CASE=xxx Q="为什么 L2-13？"
ask:
	$(PY) -m src.app.cli ask $(CASE) "$(Q)"

list:
	$(PY) -m src.app.cli list

# 看单条用例的审核明细：make show ID=IMP-0019
show:
	$(PY) evals/debug_case.py $(ID)

# 重新生成/校验 5 票真实感合成单证
sample-cases:
	$(PY) examples/realistic/build.py

# Docker
docker-build:
	docker build -t $(IMAGE) .

docker-run:
	docker run --rm -p $(PORT):8000 -v "$(CURDIR)/var:/app/var" $(IMAGE)

docker-up:
	docker compose up --build

clean:
	rm -rf evals/report/result.json evals/report/review.md evals/report/judge.md \
		evals/report/redteam.md evals/report/redteam.json \
		evals/report/perf.md evals/report/perf.json
	find . -name '__pycache__' -type d -exec rm -rf {} +
