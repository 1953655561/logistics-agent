# Web 审核台（AntD 5 + React 18 + TS + Vite + TanStack Query）

## 启动

```bash
pnpm install
pnpm dev        # http://localhost:5173，/api 代理到 http://127.0.0.1:8000
```

后端先起：

```bash
python -m src.app.api --port 8000       # FastAPI + 构建产物
# 或
python -m src.app.fallback_server --port 8000   # 无依赖兜底
```

## 构建

```bash
# 1) 从 FastAPI 导出 OpenAPI，再生成 TS 类型（禁止手写 DTO）
python -m src.app.api --dump-openapi web/openapi.json
pnpm gen:types

# 2) 类型检查 + 构建到 web/dist
pnpm build
```

构建完成后，FastAPI / 兜底服务会自动服务 `web/dist`；没有构建产物时兜底服务会服务
`web/fallback/index.html`。

## 页面

- **审核台**：审核单列表、按合成用例新建审核、单票详情（问题清单 / 五单证 / 处理轨迹 / 复核与护栏）、
  `PENDING_APPROVAL` 时的人工审批 Drawer。
- **评测指标**：准确率、召回、误报、引用覆盖、平均步数、P95、单票成本、逐条结果。
- 深链：`/?case=IMP-0025` 直接打开某票；`/?view=metrics` 打开指标页。

## 约定

- 样式用 AntD token + CSS Modules，不引 Tailwind / 全局 reset。
- 所有数据来自 `/api`，前端不做业务判断；结论、引用、复核意见都按后端给的展示。
- `src/types/api.ts` 是 `openapi-typescript` 生成的，不要手改。
