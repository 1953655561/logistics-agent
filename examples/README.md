# 单证 JSON 示例与导入说明

`docs.example.json` 是一票完整的合成单证，可直接用于审核台「导入单证」或命令行。

更多真实感数据（5 票，覆盖 PASS/FIX/REVIEW/REJECT）见 [`realistic/`](realistic/)。

## 顶层结构

```json
{
  "contract":     { "contract_no": "...", "date": "...", "currency": "USD", "incoterm": "FOB", "total_amount": 48000 },
  "invoice":      { "invoice_no": "...", "date": "...", "currency": "USD", "items": [...], "total_amount": 48000 },
  "packing_list": { "pl_no": "...", "packages": 50, "gross_weight": 1200.5, "net_weight": 1150.0, "items": [...] },
  "bl":           { "bl_no": "...", "date": "...", "packages": 50, "gross_weight": 1200.5, "consignee": "...", "items": [...] },
  "declaration":  { "declare_date": "...", "items": [...], "total_amount": 48000, "currency": "USD" }
}
```

至少需要 `invoice` 或 `declaration`；缺少其他单证也能审，结论会降为 `REVIEW`（单证不齐），这正是“缺单证”测试场景。

## 商品项最少字段

`invoice.items` / `declaration.items` 必须是非空数组，每项至少：

```json
{
  "name": "塑料制玩具配件",
  "name_en": "PLASTIC TOY PARTS",
  "hs_code": "9503008900",
  "qty": 1000,
  "unit": "个",
  "unit_price": 48.0,
  "amount": 48000.0,
  "origin": "CN",
  "legal_unit1": "个",
  "legal_unit2": "千克"
}
```

`declaration.items` 还需要 `elements`（申报要素），可由审核台/规则引擎提示缺失；导入时可以先不填全，用结论驱动补全。

## 导入方式

**Web**：审核台 →「导入单证」→ 粘贴/上传 JSON → 可手填案件编号（留空自动生成）→「导入并审核」。

**CLI**：

```bash
python -m src.app.cli audit MY-CASE-001 --docs examples/docs.example.json --auto --offline
```

**HTTP**：

```bash
curl -X POST http://127.0.0.1:8000/api/cases/import \
  -H "Content-Type: application/json" \
  -d "{\"case_id\":\"MY-CASE-001\",\"docs\": $(cat examples/docs.example.json)}"
```

## 校验规则

- 顶层必须是对象；
- 至少一份已知单证；
- `invoice.items` / `declaration.items` 必须是非空数组（存在时）；
- 单文件 ≤ 1MB；
- 注入/控制字符会由护栏清洗并记录；
- 同一 `case_id` 已存在时自动加后缀，避免覆盖历史审核单。

> 所有示例数据均为合成数据，不含真实企业名、单号或个人信息。
