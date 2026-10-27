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

export function Money({ value }: { value?: number }) {
  return <Typography.Text>¥{Number(value ?? 0).toFixed(6)}</Typography.Text>;
}
