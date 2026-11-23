import dayjs from "dayjs";
import { Tag, Typography } from "antd";

const STATUS_LABEL: Record<string, string> = {
  DRAFT: "草稿",
  REVIEWING: "审核中",
  PENDING_APPROVAL: "待审批",
  APPROVED: "已通过",
  RETURNED: "已退回",
  FAILED: "失败",
};

const STATUS_COLOR: Record<string, string> = {
  DRAFT: "default",
  REVIEWING: "processing",
  PENDING_APPROVAL: "warning",
  APPROVED: "success",
  RETURNED: "error",
  FAILED: "error",
};

const VERDICT_LABEL: Record<string, string> = {
  PASS: "可申报",
  FIX: "可补正",
  REVIEW: "需复核",
  REJECT: "不可申报",
};

const VERDICT_COLOR: Record<string, string> = {
  PASS: "success",
  FIX: "warning",
  REVIEW: "error",
  REJECT: "volcano",
};

const REVIEW_LABEL: Record<string, string> = {
  agree: "同意",
  escalate: "建议升级",
  downgrade: "建议降级",
  advisory: "提示",
};

const REVIEW_COLOR: Record<string, string> = {
  agree: "success",
  escalate: "error",
  downgrade: "warning",
  advisory: "default",
};

export function StatusTag({ state }: { state?: string }) {
  if (!state) return <Tag>—</Tag>;
  return <Tag color={STATUS_COLOR[state] ?? "default"}>{STATUS_LABEL[state] ?? state}</Tag>;
}

export function VerdictTag({ verdict }: { verdict?: string }) {
  if (!verdict) return <Tag>—</Tag>;
  return (
    <Tag color={VERDICT_COLOR[verdict] ?? "default"}>
      {VERDICT_LABEL[verdict] ?? verdict}
    </Tag>
  );
}

export function SeverityTag({ severity }: { severity?: string }) {
  const color = severity === "high" ? "error" : severity === "mid" ? "warning" : "default";
  const label = severity === "high" ? "高" : severity === "mid" ? "中" : "低";
  return <Tag color={color}>{label}</Tag>;
}

/** 复核建议：把 agree/escalate/downgrade 这类英文枚举翻成中文，避免界面中英混排。 */
export function ReviewTag({ recommendation }: { recommendation?: string }) {
  if (!recommendation) return <Tag>—</Tag>;
  return (
    <Tag color={REVIEW_COLOR[recommendation] ?? "default"}>
      {REVIEW_LABEL[recommendation] ?? recommendation}
    </Tag>
  );
}

/** 金额：0 / 空值显示破折号，非零保留 4 位；极小值显示 <0.0001（mock 成本常见）。 */
export function Money({ value }: { value?: number | null }) {
  const n = Number(value ?? 0);
  if (!value || !Number.isFinite(n) || n <= 0) {
    return <Typography.Text type="secondary">—</Typography.Text>;
  }
  return (
    <Typography.Text>
      {n < 0.0001 ? "¥<0.0001" : `¥${n.toFixed(4)}`}
    </Typography.Text>
  );
}

/** 时间：后端给 ISO 字符串，界面统一成人读格式，去掉 T。 */
export function formatTime(value?: string | null, withYear = false): string {
  if (!value) return "—";
  const d = dayjs(value);
  return d.isValid() ? d.format(withYear ? "YYYY-MM-DD HH:mm" : "MM-DD HH:mm") : value;
}

/** 结论文本里混着 REVIEW/REJECT 等枚举时，翻成中文再展示。 */
export function localizeText(text?: string | null): string {
  if (!text) return "";
  return text.replace(/\b(PASS|FIX|REVIEW|REJECT)\b/g, (m) => VERDICT_LABEL[m] ?? m);
}
