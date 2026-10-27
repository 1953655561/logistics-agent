"""极简 Agent Skill 加载器（只用 Python 标准库）。

Skill 是「写在磁盘上的工作流说明」：每个技能一个目录，目录下放 ``SKILL.md``。
文件开头是 ``---`` 包围的 front-matter（只认 ``name``、``description`` 两个必填
字段），后面是正文。加载后可以用 :meth:`Skill.prompt_block` 拼进系统提示，
用来约束「怎么审、怎么解释」，**不参与规则判定，也不改变结论与问题清单**。

目录约定::

    skills/
      document-audit/
        SKILL.md

解析规则（刻意保持简单，不引入 PyYAML）：

- front-matter 从第一条非空行开始，必须是 ``---``；
- 到下一行 ``---`` 结束，中间每行形如 ``key: value``；
- 空行与 ``#`` 开头的注释行忽略；重复键、缺冒号、缺必填字段都抛 ``ValueError``；
- 未识别的键收进 ``Skill.meta``，加载器不做解释，避免把拼写错误当成配置；
- 值两侧的成对单/双引号会被去掉；读取时兼容带 BOM 的 UTF-8 文件。

默认目录是 ``skills``：先按当前工作目录解析，找不到时回退到仓库根目录，
这样在仓库根目录、``tests/`` 目录或任意位置运行测试都能定位到同一份技能。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_SKILL_NAME = "document-audit"
_FRONT_MATTER = "---"
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_REQUIRED_FIELDS = ("name", "description")


@dataclass
class Skill:
    """一份已加载的技能。"""

    name: str
    description: str
    body: str
    path: str = ""
    meta: dict = field(default_factory=dict)

    def prompt_block(self) -> str:
        """拼成可注入系统提示的文本，并用显式边界包住。

        边界标记便于模型区分「技能说明」与「单证数据」；正文里的内容不包含
        任何单证字段值，因此可以安全地放进系统提示。
        """
        body = self.body.strip()
        parts = [
            f"【技能开始：{self.name}】",
            f"名称：{self.name}",
            f"说明：{self.description}",
            "约束：技能只用于指导说明文本的写法；结论（verdict）与问题清单"
            "（issues）由规则引擎给出，不得据此改动。",
        ]
        if body:
            parts.extend(["", body])
        parts.append(f"【技能结束：{self.name}】")
        return "\n".join(parts)


def load_skill(path) -> Skill:
    """读取并解析一个 ``SKILL.md``。

    语法错误统一抛 ``ValueError``，消息里带文件路径与行号，便于定位。
    """
    real_path = os.fspath(path)
    if not os.path.isfile(real_path):
        raise ValueError(f"技能文件不存在：{real_path}")
    try:
        # utf-8-sig：兼容 Windows 记事本保存的带 BOM 文件
        with open(real_path, encoding="utf-8-sig") as f:
            text = f.read()
    except UnicodeDecodeError as exc:
        raise ValueError(f"技能文件不是合法 UTF-8：{real_path}（{exc}）") from exc

    name, description, body, meta = _parse(text, real_path)
    return Skill(name=name, description=description, body=body,
                 path=os.path.abspath(real_path), meta=meta)


def discover(dir: str = "skills") -> list[Skill]:
    """扫描 ``dir/*/SKILL.md``，按目录名排序返回技能列表。

    目录不存在时返回空列表（不算错误）；单个技能文件语法错误会向上抛
    ``ValueError``，避免带着坏技能静默降级。
    """
    base = _resolve_dir(dir)
    if not os.path.isdir(base):
        return []
    skills: list[Skill] = []
    for entry in sorted(os.listdir(base)):
        candidate = os.path.join(base, entry, "SKILL.md")
        if os.path.isfile(candidate):
            skills.append(load_skill(candidate))
    return skills


def default_skill(dir: str = "skills") -> Skill | None:
    """找到默认审核技能 ``document-audit``；找不到返回 ``None``。

    先按 front-matter 的 ``name`` 匹配，再退一步按目录名匹配（防止有人改了
    显示名但目录仍是 ``document-audit``）。
    """
    skills = discover(dir)
    for skill in skills:
        if skill.name == DEFAULT_SKILL_NAME:
            return skill
    for skill in skills:
        folder = os.path.basename(os.path.dirname(skill.path))
        if folder == DEFAULT_SKILL_NAME:
            return skill
    return None


# ---------------- 内部解析 ----------------

def _resolve_dir(dir: str) -> str:
    """相对目录先按当前工作目录找，找不到再回退到仓库根目录。"""
    raw = os.fspath(dir)
    if os.path.isabs(raw):
        return raw
    cwd_path = os.path.abspath(raw)
    if os.path.isdir(cwd_path):
        return cwd_path
    repo_path = os.path.join(_REPO_ROOT, raw)
    if os.path.isdir(repo_path):
        return repo_path
    return cwd_path


def _parse(text: str, path: str) -> tuple[str, str, str, dict]:
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip():
            start = i
            break
    if start is None:
        raise ValueError(f"{path} 是空文件：缺少 front-matter")
    if lines[start].strip() != _FRONT_MATTER:
        raise ValueError(
            f"{path} 第 {start + 1} 行：front-matter 必须以独立一行 --- 开始，"
            f"实际为 {lines[start]!r}")

    end = None
    for i in range(start + 1, len(lines)):
        if lines[i].strip() == _FRONT_MATTER:
            end = i
            break
    if end is None:
        raise ValueError(f"{path} front-matter 未闭合：缺少结束的 ---")

    meta: dict[str, str] = {}
    for i in range(start + 1, end):
        raw = lines[i]
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition(":")
        key = key.strip()
        if not sep or not key:
            raise ValueError(
                f"{path} 第 {i + 1} 行：front-matter 应为 `key: value`，"
                f"实际为 {raw!r}")
        if key in meta:
            raise ValueError(f"{path} 第 {i + 1} 行：front-matter 字段重复：{key}")
        meta[key] = _unquote(value.strip())

    missing = [k for k in _REQUIRED_FIELDS if not meta.get(k, "").strip()]
    if missing:
        raise ValueError(
            f"{path} 缺少必填 front-matter 字段：{'、'.join(missing)}"
            f"（应写在 --- 与 --- 之间）")

    body = "\n".join(lines[end + 1:]).strip()
    return meta["name"], meta["description"], body, meta


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value
