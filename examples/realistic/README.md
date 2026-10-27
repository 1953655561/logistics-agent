# 真实感合成单证（5 票）

字段参照：

- 海关总署 2019 年第 18 号公告《中华人民共和国海关进出口货物报关单填制规范》
- UPS《商业发票填写指南》

数据全部为**合成数据**，企业名、单号、金额均为虚构，用于功能测试与演示。

## 文件

| 文件 | 期望结论 | 主要命中规则 | 场景 |
|---|---|---|---|
| `REAL-001-standard-toys-PASS.json` | PASS | — | 标准进口玩具，四单一致、FOB 运保费已申报、3C 齐全 |
| `REAL-002-amount-mismatch-FIX.json` | FIX | `L2-13` | 报关单总价少报 0.25%，超过 0.1% 总额容差 |
| `REAL-003-missing-3c-REVIEW.json` | REVIEW | `L4-33` | 食品研磨机属 3C 品类，未申报证书号 |
| `REAL-004-old-machinery-REJECT.json` | REJECT | `L4-36` | 品名含“旧机电”，属禁限类目 |
| `REAL-005-multi-defect-REVIEW.json` | REVIEW | `L2-19` / `L2-20` / `L4-42` | FOB 漏报运保费 + 原产国不一致 + 申报超期 |

`index.json` 是生成时校验的结果清单；`build.py` 可重新生成并断言期望结论。

## 字段对照（节选）

### 报关单

| 填制规范字段 | 本项目 JSON |
|---|---|
| 境内收货人 | `declaration.consignee` |
| 进境关别 | `declaration.customs_office`（附加字段，规则不强制） |
| 运输方式 | `declaration.transport_mode` |
| 监管方式 | `declaration.trade_mode` |
| 征免性质 | `declaration.exemption_nature` |
| 启运国（地区） | `declaration.origin_country` |
| 装货港 | `declaration.loading_port` |
| 境内目的地 | `declaration.destination` |
| 成交方式 | `declaration.incoterm` |
| 运费 / 保费 | `declaration.freight` / `declaration.insurance` |
| 合同协议号 | `declaration.contract_no` |
| 提运单号 | `declaration.bl_no` |
| 许可证号 / 有效期 | `declaration.license_no` / `license_expiry` |
| 商品编号 | `declaration.items[].hs_code` |
| 商品名称 | `declaration.items[].name` / `name_en` |
| 数量 / 单位 / 单价 / 总价 | `qty` / `unit` / `unit_price` / `amount` |
| 原产国 | `declaration.items[].origin` |
| 法定第一/第二单位 | `legal_unit1` / `legal_unit2` |
| 申报要素 | `declaration.items[].elements` |

### UPS 商业发票

| 发票字段 | 本项目 JSON |
|---|---|
| Invoice No. / Date | `invoice.invoice_no` / `invoice.date` |
| Seller / Buyer | `invoice.seller` / `invoice.buyer` |
| Currency | `invoice.currency` |
| Incoterms | `invoice.incoterm` |
| Description of goods | `invoice.items[].name` / `name_en` |
| HS Code | `invoice.items[].hs_code` |
| Quantity / Unit Price / Total | `qty` / `unit_price` / `amount` |
| Country of Origin | `invoice.items[].origin` |
| Reason for Export | `invoice.reason_for_export`（附加字段） |
| Freight / Insurance | `invoice.incoterm` + `declaration.freight/insurance` |

## 怎么用

**一键校验**：

```bash
python examples/realistic/build.py
```

**命令行跑一票**：

```bash
python -m src.app.cli audit REAL-001 \
  --docs examples/realistic/REAL-001-standard-toys-PASS.json --auto --offline
```

**审核台导入**：

1. 打开审核台 →「导入单证」；
2. 选择/粘贴任一 `REAL-*.json`；
3. 案件编号可留空；
4. 「导入并审核」。

## 怎么改造成自己的测试数据

- 测金额：改 `declaration.total_amount`（相对发票少 0.1% 以上就会报 `L2-13`）；
- 测数量：改 `declaration.items[].qty`（默认容差 1%，散装 3%）；
- 测重量：改 `bl.gross_weight`（容差 3%）；
- 测缺证件：清空 `declaration.cert_no`；
- 测缺单证：删掉 `bl` 或 `packing_list`，导入后结论会转 `REVIEW`；
- 测归类：改 `items[].hs_code` 或 `name`，触发 `L3-25` / `L3-26`。

> 注意：真实业务数据请先脱敏，不要提交真实企业名、税号、单号或个人信息。
