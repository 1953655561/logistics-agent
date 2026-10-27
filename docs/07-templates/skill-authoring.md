# SKILL.md 写作规范（skill authoring）

> 适用：`skills/<name>/SKILL.md`。加载器是 `src/harness/skills.py`，**只用标准库**，
> 不引入 PyYAML，按行解析 front-matter。默认技能：`skills/document-audit/SKILL.md`。
> 技能只约束「说明文本怎么写」，不参与规则判定，也不改变 `verdict` / `issues`。

## 1. 位置与命名

```text
skills/
  document-audit/
    SKILL.md      # 必须叫这个名字，只扫描一层 skills/*/SKILL.md
```

- 目录名用 kebab-case，与 front-matter 的 `name` 一致（加载器会先按 `name`、
  再按目录名找默认技能）。
- 一个目录一个技能；`SKILL.md` 大小写敏感（Windows 上也按这个写法）。
- 技能是静态文件，不放单证数据、日志、密钥、生成物。

## 2. front-matter（加载器的真实语法）

```markdown
---
name: document-audit
description: 一句话说明技能负责什么、适用什么场景、不适用什么场景。
---

正文从第二个 --- 之后开始。
```

硬规则（不符合会抛 `ValueError`，消息带文件路径与行号）：

- `---` 必须各自独立成行；第一条非空行是开始标记，下一行 `---` 是结束标记；
  缺开始、缺结束、空文件都会报错。
- 只支持**单行** `key: value`：不支持 YAML 的列表（`-`）、嵌套、块标量（`|` / `>`）、
  多行续写；值内部的冒号没问题（只按第一个 `:` 切分）。
- 空行与 `#` 开头的注释行忽略；重复键报错；没有冒号的行报错。
- 值两侧成对的单/双引号会被去掉。
- `name`、`description` 必填且非空；其它键收进 `Skill.meta`，加载器**不解释**，
  所以拼错的键不会被当成配置生效。
- `name` 建议 kebab-case、全局唯一；`description` 建议一行写完，包含用途与
  “不适用”边界，别写成营销文案。
- 正文可以为空（不报错），但空正文的技能没有意义；建议正文非空。

## 3. 正文结构（建议顺序）

1. **适用与不适用**：业务范围、输入形态（结构化 JSON，不是扫描件）；
   明确不做的能力（OCR、真实向量库、A2A、外部系统调用）。
2. **输入契约**：单证键、关键字段、字段类型与缺失策略。字段名必须与代码一致。
3. **流程 / 工具契约**：先调什么、后调什么；每个工具的入参与返回，
   以 `src/tools/audit_tools.py` 的 JSON Schema 为准。
4. **规则职责**：分层（L1/L2/L3/L4）、编号、各自管什么、结论口径；
   数量与编号必须与 `docs/01-rule-library.md` 和 `src/registry.py` 对得上。
5. **输出契约**：`verdict` 四态、`issues` 字段、引用要求（可回查的 `chunk_id`）。
6. **硬边界**：不改判 HS、不改原始单证、记忆只提示、离线可跑、失败显式降级。
7. **自检清单**：用可勾选条目收尾，方便人和模型自查。

写作要求：

- 用中文；代码标识符、工具名、字段名保持英文原样。
- 用表格列契约、用代码块列命令，避免大段散文。
- 数字必须可核对（5 单、46 条、10 位编码、8 步预算）；代码变了要同步改技能。
- 单文件建议控制在 15KB 以内：技能会进系统提示，太长会挤占上下文。
- 宁可写“当前未实现”，也不要写一个听起来很强但仓库里没有的能力。

## 4. 禁止事项

- [ ] **禁止编造能力**：OCR / 扫描件识别 / PDF 解析、真实向量数据库、真实税则库、
      A2A、外部 API、联网检索、自动落库，本仓库都没有。
- [ ] **禁止改判 HS**：只能 6 位建议 + 人工确认；禁止 `auto_change_hs` /
      `change_hs` / `auto_reclassify`。
- [ ] **禁止建议修改原始单证**：输入只读，只输出补正建议与草稿。
- [ ] **禁止让技能改结论**：不得写“按本技能把 verdict 改为 …”或“忽略 issues”；
      技能只影响说明文本。
- [ ] **禁止真实数据**：不写真实企业名、真实单号、个人信息；示例也要合成。
- [ ] **禁止把不可信输入嵌入技能**：front-matter 与正文是静态可信内容；
      不要把用户单证文本、网页内容、日志拼进来。
- [ ] **禁止引入依赖**：不用 PyYAML、不装包；解析逻辑保持在 `skills.py`。
- [ ] **禁止用技能替代规则**：判定由 `src/rules/**` 负责，技能不是第二套规则引擎。

## 5. 加载与校验

加载器 API（`src/harness/skills.py`）：

| 函数 | 行为 |
|---|---|
| `load_skill(path)` | 解析单个 `SKILL.md`；语法错误抛 `ValueError` |
| `discover(dir="skills")` | 扫描 `dir/*/SKILL.md`，按目录名排序；目录不存在返回 `[]` |
| `Skill.prompt_block()` | 拼出带 `【技能开始：name】` / `【技能结束：name】` 边界的提示块 |
| `default_skill(dir="skills")` | 找 `document-audit`；找不到返回 `None` |

- 相对目录先按当前工作目录解析，找不到再回退到仓库根目录；测试在
  `tests/` 下跑也能定位到 `skills/`。
- 语法错误直接抛错，不静默跳过；`discover` 遇到坏技能会失败，便于及早发现。

自检命令：

```bash
python -c "from src.harness.skills import default_skill; s=default_skill(); print(s.name, len(s.body))"
python -c "from src.harness.skills import default_skill; print(default_skill().prompt_block()[:200])"
python -m unittest tests.test_skills
```

集成自检（技能不得改变结论）：

```python
from src.harness.loop import AuditLoop
# 同一票分别用 skill=None 与 skill=default_skill() 跑，比较 issues 与 verdict 必须完全一致
```

## 6. 变更管理

- 改技能正文 = 改模型看到的说明口径：同步检查 `tests/test_skills.py` 与
  `docs/07-templates/` 下的相关模板。
- 若技能描述的能力变了（新增工具、规则数变化），先改代码与 `docs/01`，再改技能，
  顺序不能反。
- 删除技能时确认 `default_skill()` 返回 `None`、`AuditLoop(skill=None)` 行为不变；
  引用该技能的文档与测试一起清理。
- 技能没有独立版本号字段；用 git 历史与 `description`/正文变更说明追踪。
