import { Descriptions, Typography } from "antd";
import styles from "./JsonView.module.css";

export default function JsonView({ data }: { data: unknown }) {
  if (data === null || data === undefined) {
    return <Typography.Text type="secondary">—</Typography.Text>;
  }
  if (typeof data !== "object") {
    return <Typography.Text>{String(data)}</Typography.Text>;
  }
  if (Array.isArray(data)) {
    return <pre className={styles.pre}>{JSON.stringify(data, null, 2)}</pre>;
  }
  const entries = Object.entries(data as Record<string, unknown>);
  return (
    <Descriptions
      size="small"
      bordered
      column={1}
      items={entries.map(([key, value]) => ({
        key,
        label: key,
        children:
          value !== null && typeof value === "object" ? (
            <pre className={styles.pre}>{JSON.stringify(value, null, 2)}</pre>
          ) : (
            String(value ?? "—")
          ),
      }))}
    />
  );
}
