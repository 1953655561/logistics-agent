# 检索评测（RAG 召回）

- 检索集：**30** 条口语化 query（不含规则编号，避免精确命中抹平难度）
- recall@1：**93.3%**
- recall@3：**100.0%**
- MRR：**0.961**

> 端到端「引用覆盖率 100%」说明的是引用能挂上，不是检索准；这两个指标才回答 RAG 召回得怎么样。

## 逐条结果

| # | query | 期望 | 命中位次 | top3 |
|---|---|---|---|---|
| 1 | 发票和报关单总价对不上，按哪个改 | rules#L2-13 | 1 | rules#L2-13, rules#L2-20, rules#L2-18 |
| 2 | 四张单子币制不一样 | rules#L2-14 | 2 | rules#L1-03, rules#L2-14, rules#L2-12 |
| 3 | 品名少一个字算不算不一致 | rules#L2-11 | 1 | rules#L2-11, rules#L2-14, rules#L3-25 |
| 4 | 收货人和提单通知人对不上 | rules#L2-18 | 1 | rules#L2-18, rules#L2-17, rules#L1-02 |
| 5 | 唛头目的港和卸货港写法不同 | rules#L2-22 | 1 | rules#L2-22, rules#L1-01, rules#L4-38 |
| 6 | 发票上没有合同号 | rules#L2-21 | 1 | rules#L2-21, rules#L2-23, rules#L2-18 |
| 7 | FOB 成交运费要不要申报 | rules#L2-19 | 1 | rules#L2-19, rules#L4-41, rules#L3-30 |
| 8 | 报关单原产国和发票不一致 | rules#L2-20 | 1 | rules#L2-20, rules#L2-11, rules#L2-24 |
| 9 | 合同金额和发票金额差很多 | rules#L2-23 | 1 | rules#L2-23, rules#L1-07, rules#L2-13 |
| 10 | 品牌类型发票和报关单写的不一样 | rules#L2-24 | 1 | rules#L2-24, rules#L2-18, rules#L2-20 |
| 11 | 商品编号位数不对或者带字母 | rules#L1-10 | 1 | rules#L1-10, rules#L3-23, elements#2202100000 |
| 12 | 缺少法定第二计量单位 | rules#L1-04 | 1 | rules#L1-04, rules#L3-30, rules#L4-36 |
| 13 | 申报日期早于提单日期 | rules#L1-02 | 1 | rules#L1-02, rules#L2-17, rules#L1-06 |
| 14 | 报关单币制代码写错 | rules#L1-03 | 1 | rules#L1-03, rules#L2-14, rules#L2-17 |
| 15 | 毛重比净重还小 | rules#L1-08 | 1 | rules#L1-08, rules#L2-16, rules#L2-15 |
| 16 | 托盘包装没填托盘数 | rules#L1-09 | 1 | rules#L1-09, rules#L4-39, rules#L4-43 |
| 17 | 随附单证缺了提单 | rules#L1-06 | 1 | rules#L1-06, rules#L1-02, rules#L2-22 |
| 18 | 一票超过五十项商品要拆单 | rules#L1-05 | 1 | rules#L1-05, rules#L1-04, rules#L3-24 |
| 19 | 单价乘数量对不上行金额 | rules#L1-07 | 1 | rules#L1-07, rules#L2-12, rules#L2-23 |
| 20 | 特许权使用费没算进完税价格 | rules#L4-41 | 1 | rules#L4-41, rules#L2-19, rules#L4-43 |
| 21 | 进境超过十四天才申报 | rules#L4-42 | 1 | rules#L4-42, rules#L1-05, rules#L3-28 |
| 22 | 木包装没有 IPPC 标识 | rules#L4-43 | 1 | rules#L4-43, rules#L1-09, rules#L4-39 |
| 23 | 许可证在申报日已经过期 | rules#L4-44 | 1 | rules#L4-44, rules#L4-33, rules#L1-02 |
| 24 | 玩具进口要不要 3C 认证 | rules#L4-33 | 3 | elements#9503006000, elements#9503008900, rules#L4-33 |
| 25 | 贸易方式和征免性质不匹配 | rules#L4-35 | 1 | rules#L4-35, rules#L1-01, rules#L1-04 |
| 26 | 9503008900 要报哪些申报要素 | elements#9503008900 | 1 | elements#9503008900, elements#3917400000, elements#9503006000 |
| 27 | 8471300000 的规范申报要素 | elements#8471300000 | 1 | elements#8471300000, elements#3917400000, elements#9405100000 |
| 28 | 1905310000 申报要填什么 | elements#1905310000 | 1 | elements#1905310000, elements#7306300000, elements#8509400000 |
| 29 | 8509400000 的要素清单 | elements#8509400000 | 1 | elements#8509400000, rules#L4-37, elements#3917400000 |
| 30 | 6109100021 需要报哪些要素 | elements#6109100021 | 1 | elements#6109100021, elements#8517120000, elements#3917400000 |