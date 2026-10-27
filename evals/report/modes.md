# 模式对比（scripted vs react）

- 用例数：**60**
- 结论一致率：**100.0%**（规则集合一致率 100.0%）
- 平均步数：scripted **3.7** → react **4.4**
- 单票成本：scripted **¥0.000217** → react **¥0.000217**（mock 模型）
- react 证据覆盖：**28.3%**（17/60 条问题带回查证据）

## 逐条结果

| 用例 | 期望 | scripted | react | 结论一致 | 规则一致 | 步数 s/r |
|---|---|---|---|---|---|---|
| IMP-0001 | PASS | PASS | PASS | ✅ | ✅ | 3/3 |
| IMP-0002 | PASS | PASS | PASS | ✅ | ✅ | 3/3 |
| IMP-0003 | PASS | PASS | PASS | ✅ | ✅ | 3/3 |
| IMP-0004 | PASS | PASS | PASS | ✅ | ✅ | 3/3 |
| IMP-0005 | PASS | PASS | PASS | ✅ | ✅ | 3/3 |
| IMP-0006 | PASS | PASS | PASS | ✅ | ✅ | 3/3 |
| IMP-0007 | PASS | PASS | PASS | ✅ | ✅ | 3/3 |
| IMP-0008 | PASS | PASS | PASS | ✅ | ✅ | 3/3 |
| IMP-0009 | PASS | PASS | PASS | ✅ | ✅ | 3/3 |
| IMP-0010 | PASS | PASS | PASS | ✅ | ✅ | 3/3 |
| IMP-0011 | PASS | PASS | PASS | ✅ | ✅ | 3/3 |
| IMP-0012 | PASS | PASS | PASS | ✅ | ✅ | 3/3 |
| IMP-0013 | PASS | PASS | PASS | ✅ | ✅ | 3/3 |
| IMP-0014 | PASS | PASS | PASS | ✅ | ✅ | 3/3 |
| IMP-0015 | PASS | PASS | PASS | ✅ | ✅ | 3/3 |
| IMP-0016 | PASS | PASS | PASS | ✅ | ✅ | 3/3 |
| IMP-0017 | PASS | PASS | PASS | ✅ | ✅ | 3/3 |
| IMP-0018 | PASS | PASS | PASS | ✅ | ✅ | 3/3 |
| IMP-0019 | FIX | FIX | FIX | ✅ | ✅ | 4/6 |
| IMP-0020 | FIX | FIX | FIX | ✅ | ✅ | 5/7 |
| IMP-0021 | FIX | FIX | FIX | ✅ | ✅ | 4/4 |
| IMP-0022 | FIX | FIX | FIX | ✅ | ✅ | 4/4 |
| IMP-0023 | FIX | FIX | FIX | ✅ | ✅ | 4/4 |
| IMP-0024 | FIX | FIX | FIX | ✅ | ✅ | 4/7 |
| IMP-0025 | REVIEW | REVIEW | REVIEW | ✅ | ✅ | 4/8 |
| IMP-0026 | REVIEW | REVIEW | REVIEW | ✅ | ✅ | 3/8 |
| IMP-0027 | REVIEW | REVIEW | REVIEW | ✅ | ✅ | 3/3 |
| IMP-0028 | FIX | FIX | FIX | ✅ | ✅ | 3/5 |
| IMP-0029 | FIX | FIX | FIX | ✅ | ✅ | 3/3 |
| IMP-0030 | FIX | FIX | FIX | ✅ | ✅ | 4/4 |
| IMP-0031 | PASS | PASS | PASS | ✅ | ✅ | 3/3 |
| IMP-0032 | FIX | FIX | FIX | ✅ | ✅ | 3/6 |
| IMP-0033 | FIX | FIX | FIX | ✅ | ✅ | 5/7 |
| IMP-0034 | REVIEW | REVIEW | REVIEW | ✅ | ✅ | 4/6 |
| IMP-0035 | FIX | FIX | FIX | ✅ | ✅ | 4/4 |
| IMP-0036 | FIX | FIX | FIX | ✅ | ✅ | 4/4 |
| IMP-0037 | FIX | FIX | FIX | ✅ | ✅ | 4/4 |
| IMP-0038 | FIX | FIX | FIX | ✅ | ✅ | 4/4 |
| IMP-0039 | FIX | FIX | FIX | ✅ | ✅ | 4/4 |
| IMP-0040 | FIX | FIX | FIX | ✅ | ✅ | 4/4 |
| IMP-0041 | REVIEW | REVIEW | REVIEW | ✅ | ✅ | 5/9 |
| IMP-0042 | REVIEW | REVIEW | REVIEW | ✅ | ✅ | 4/4 |
| IMP-0043 | REVIEW | REVIEW | REVIEW | ✅ | ✅ | 4/4 |
| IMP-0044 | REVIEW | REVIEW | REVIEW | ✅ | ✅ | 4/4 |
| IMP-0045 | REVIEW | REVIEW | REVIEW | ✅ | ✅ | 4/4 |
| IMP-0046 | REVIEW | REVIEW | REVIEW | ✅ | ✅ | 4/4 |
| IMP-0047 | REVIEW | REVIEW | REVIEW | ✅ | ✅ | 4/4 |
| IMP-0048 | REJECT | REJECT | REJECT | ✅ | ✅ | 4/4 |
| IMP-0049 | REJECT | REJECT | REJECT | ✅ | ✅ | 4/4 |
| IMP-0050 | REJECT | REJECT | REJECT | ✅ | ✅ | 4/4 |
| IMP-0051 | REVIEW | REVIEW | REVIEW | ✅ | ✅ | 3/3 |
| IMP-0052 | REVIEW | REVIEW | REVIEW | ✅ | ✅ | 3/3 |
| IMP-0053 | FIX | FIX | FIX | ✅ | ✅ | 5/7 |
| IMP-0054 | REVIEW | REVIEW | REVIEW | ✅ | ✅ | 5/5 |
| IMP-0055 | REVIEW | REVIEW | REVIEW | ✅ | ✅ | 5/9 |
| IMP-0056 | REVIEW | REVIEW | REVIEW | ✅ | ✅ | 4/4 |
| IMP-0057 | FIX | FIX | FIX | ✅ | ✅ | 5/5 |
| IMP-0058 | REVIEW | REVIEW | REVIEW | ✅ | ✅ | 4/4 |
| IMP-0059 | REVIEW | REVIEW | REVIEW | ✅ | ✅ | 6/8 |
| IMP-0060 | FIX | FIX | FIX | ✅ | ✅ | 5/7 |