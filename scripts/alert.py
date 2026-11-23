"""告警出口：门禁不过 → 落盘告警文件（+ 可选 webhook），exit 1。

    python scripts/alert.py

读取五份评测报告：
`evals/report/{result,perf,redteam,hallucination,extraction}.json`，
复用 `scripts/gate.py::checks()` 的 12 项阈值（单一事实源，不另抄一份）。

- 任意一项不过 → 写 `var/alerts/<时间戳>.json`，打印失败项，返回 1；
- 全部通过 → 不产生文件，返回 0；
- 设置环境变量 `LOGIAGENT_ALERT_WEBHOOK` 时，用 urllib POST 一个 JSON；
  发送失败只打印日志，绝不抛异常（告警通道不能反过来阻断主流程）。

缺报告文件不静默跳过：对应门禁项按失败处理，并写进告警 payload 的
`missing_reports`，避免"没跑评测所以没告警"。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import gate                                                    # noqa: E402

REPORT = os.path.join(ROOT, "evals", "report")
ALERTS = os.path.join(ROOT, "var", "alerts")
FILES = ("result.json", "perf.json", "redteam.json",
         "hallucination.json", "extraction.json")
WEBHOOK_ENV = "LOGIAGENT_ALERT_WEBHOOK"


def load_reports(report_dir: str = REPORT) -> tuple[dict, list[str]]:
    """读四份报告；缺文件返回空字典 + 缺失清单。"""
    data: dict[str, dict] = {}
    missing: list[str] = []
    for name in FILES:
        key = name[:-len(".json")]
        path = os.path.join(report_dir, name)
        if not os.path.exists(path):
            missing.append(name)
            data[key] = {}
            continue
        with open(path, encoding="utf-8") as f:
            data[key] = json.load(f)
    return data, missing


def notify(url: str, payload: dict) -> bool:
    """POST 告警 JSON；任何异常只记日志，不向上抛。"""
    if not url:
        return False
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(request, timeout=3) as resp:
            print(f"   webhook 已发送：HTTP {getattr(resp, 'status', 0)}")
        return True
    except Exception as exc:                    # 网络问题不能影响主流程
        print(f"   webhook 发送失败（仅记日志）：{type(exc).__name__}: {exc}",
              file=sys.stderr)
        return False


def _alert_path(alerts_dir: str, now: datetime) -> str:
    """时间戳文件名；同一秒重跑时加序号，不覆盖上一条告警。"""
    base = now.strftime("%Y%m%d-%H%M%S")
    candidate = os.path.join(alerts_dir, base + ".json")
    seq = 2
    while os.path.exists(candidate):
        candidate = os.path.join(alerts_dir, f"{base}-{seq}.json")
        seq += 1
    return candidate


def run(report_dir: str = REPORT, alerts_dir: str = ALERTS,
        webhook: str | None = None, now: datetime | None = None
        ) -> tuple[int, list[dict], str | None]:
    """执行一次告警检查，返回 (退出码, 失败项, 告警文件路径)。"""
    data, missing = load_reports(report_dir)
    items = gate.checks(data.get("result") or {}, data.get("perf") or {},
                        data.get("redteam") or {},
                        data.get("hallucination") or {},
                        data.get("extraction") or {})
    failed = [{"name": name, "actual": actual}
              for name, ok, actual in items if not ok]

    print("告警检查（门禁 %d 项）" % len(items))
    if not failed:
        print("✅ 门禁全部通过，不产生告警")
        return 0, [], None

    now = now or datetime.now()
    os.makedirs(alerts_dir, exist_ok=True)
    path = _alert_path(alerts_dir, now)
    payload = {
        "created_at": now.isoformat(timespec="seconds"),
        "gate_total": len(items),
        "failed": failed,
        "missing_reports": missing,
    }
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"❌ {len(failed)} 项未通过，告警已写入 {path}")
    for item in failed:
        print(f"  - {item['name']}（实际 {item['actual']}）")
    if missing:
        print("  缺少报告：" + "、".join(missing))

    url = os.environ.get(WEBHOOK_ENV, "") if webhook is None else webhook
    notify(url, payload)
    return 1, failed, path


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    code, _, _ = run()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
