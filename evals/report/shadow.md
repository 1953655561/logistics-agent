# 影子评测报告（human-labelled，自动生成）

- 单证：`examples/realistic/1/REAL-002-amount-mismatch-FIX.json`
- 当前引擎：结论 **REVIEW**，问题 **29** 条
- 人工标注进度：**0/29**（0%）
- precision / recall：**不参与打分**（没有 label=correct/wrong 的条目）
- 标注分布：unreviewed 29、correct 0、wrong 0、unsure 0
- 与当前引擎对账：命中 **29**/29，golden 有而引擎没有 0 条，引擎多报 0 条

## 未标注条目（不参与打分，仅列出）

| 规则 | 字段 |
|---|---|
| L1-10 | invoice.items[0].hs_code |
| L1-10 | packing_list.items[0].hs_code |
| L2-11 | packing_list.items[].name |
| L2-11 | bl.items[].name |
| L2-11 | declaration.items[].name |
| L2-13 | declaration.total_amount |
| L2-14 | declaration.currency |
| L2-23 | contract.total_amount |
| L4-40 | declaration.bl_no |
| L1-02 | invoice.date |
| L1-02 | packing_list.date |
| L1-02 | bl.arrival_date |
| L1-03 | contract.currency |
| L1-03 | invoice.currency |
| L1-04 | invoice.items[0].unit |
| L1-04 | invoice.items[0].legal_unit2 |
| L2-18 | declaration.consignee |
| L2-18 | declaration.consignee |
| L2-18 | invoice.seller |
| L2-18 | bl.shipper |
| L2-18 | invoice.buyer |
| L2-19 | incoterm |
| L2-21 | declaration.contract_no |
| L2-21 | invoice.contract_no |
| L2-22 | packing_list.marks.port |
| L2-24 | declaration.items[0].elements.brand_type |
| L2-24 | declaration.items[0].elements.use |
| L4-35 | declaration.trade_mode |
| L4-42 | bl.arrival_date |

> 说明：人工标注文件 `evals/golden/human-labelled.json` 里全部条目初始为 `unreviewed`，本报告**不伪造**人工结论；标注补齐后重跑本脚本即可得到 precision / recall。