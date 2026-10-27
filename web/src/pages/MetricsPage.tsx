import {
  Alert,
  Button,
  Card,
  Col,
  Progress,
  Row,
  Space,
  Spin,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useQuery } from "@tanstack/react-query";
import { api, type Metrics } from "../api/client";
import styles from "./MetricsPage.module.css";

type AgentMetrics = {
  avg_steps?: number;
  avg_ms?: number;
  p95_ms?: number;
  per_case_cost?: number;
  total_cost?: number;
  degraded?: number;
};

type CitationMetrics = { coverage?: number; total?: number };

type CaseRow = {
  id: string;
  title?: string;
  expected?: string;
  got?: string;
  verdict_ok?: boolean;
  recall?: number;
  issue_count?: number;
};

export default function MetricsPage() {
  const metrics = useQuery({ queryKey: ["metrics"], queryFn: api.metrics });

  if (metrics.isLoading) {
    return (
      <Card title="评测指标">
        <div className={styles.center}><Spin /></div>
      </Card>
    );
  }

  const m = metrics.data as Metrics | undefined;
  if (!m?.available) {
    return (
      <Card title="评测指标">
        <Alert
          type="info"
          showIcon
          message="还没有评测结果"
          description={m?.hint || "先运行 `python evals/runner.py --json` 生成结果。"}
          action={<Button onClick={() => metrics.refetch()}>重新检查</Button>}
        />
      </Card>
    );
  }

  const agent = (m.agent ?? {}) as AgentMetrics;
  const citation = (m.citation ?? {}) as CitationMetrics;
  const rows = (m.cases ?? []) as unknown as CaseRow[];

  const byExpected = rows.reduce<Record<string, { total: number; ok: number }>>(
    (acc, row) => {
      const key = row.expected || "—";
      acc[key] = acc[key] ?? { total: 0, ok: 0 };
      acc[key].total += 1;
      if (row.verdict_ok) acc[key].ok += 1;
      return acc;
    },
    {},
  );

  const columns: ColumnsType<CaseRow> = [
    { title: "用例", dataIndex: "id", width: 96 },
    { title: "标题", dataIndex: "title", ellipsis: true },
    { title: "期望", dataIndex: "expected", width: 80 },
    { title: "实际", dataIndex: "got", width: 80 },
    {
      title: "结论",
      dataIndex: "verdict_ok",
      width: 72,
      render: (v: boolean) => (v ? <Tag color="success">对</Tag> : <Tag color="error">错</Tag>),
    },
    {
      title: "召回",
      dataIndex: "recall",
      width: 80,
      render: (v: number) => `${Math.round((v ?? 0) * 100)}%`,
    },
    { title: "问题", dataIndex: "issue_count", width: 64, align: "right" },
  ];

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Card
        title="评测指标"
        extra={
          <Space>
            <Typography.Text type="secondary">
              生成于 {m.generated_at || "—"}
            </Typography.Text>
            <Button size="small" onClick={() => metrics.refetch()} loading={metrics.isFetching}>
              刷新
            </Button>
          </Space>
        }
      >
        <Row gutter={[16, 16]}>
          <Col xs={12} md={6}>
            <Statistic title="结论准确率" value={(m.accuracy ?? 0) * 100} precision={1} suffix="%" />
            <Progress percent={Number(((m.accuracy ?? 0) * 100).toFixed(1))} showInfo={false} />
          </Col>
          <Col xs={12} md={6}>
            <Statistic title="缺陷召回率" value={(m.recall ?? 0) * 100} precision={1} suffix="%" />
            <Progress percent={Number(((m.recall ?? 0) * 100).toFixed(1))} showInfo={false} />
          </Col>
          <Col xs={12} md={6}>
            <Statistic
              title="误报用例率"
              value={(m.false_positive_case_rate ?? 0) * 100}
              precision={1}
              suffix="%"
              valueStyle={{ color: (m.false_positive_case_rate ?? 0) > 0 ? "#b91c1c" : "#15803d" }}
            />
          </Col>
          <Col xs={12} md={6}>
            <Statistic
              title="引用覆盖率"
              value={(citation.coverage ?? 0) * 100}
              precision={1}
              suffix="%"
            />
          </Col>
          <Col xs={12} md={6}>
            <Statistic title="平均步数" value={agent.avg_steps ?? 0} precision={1} />
          </Col>
          <Col xs={12} md={6}>
            <Statistic title="P95 延迟" value={agent.p95_ms ?? 0} precision={1} suffix="ms" />
          </Col>
          <Col xs={12} md={6}>
            <Statistic
              title="单票成本"
              value={agent.per_case_cost ?? 0}
              precision={6}
              prefix="¥"
            />
          </Col>
          <Col xs={12} md={6}>
            <Statistic title="规则数" value={m.rules_total ?? 0} />
          </Col>
        </Row>
      </Card>

      <Card title="分类别准确率" size="small">
        <Row gutter={[16, 12]}>
          {Object.entries(byExpected).map(([key, value]) => (
            <Col xs={12} md={6} key={key}>
              <div className={styles.cat}>
                <Typography.Text strong>{key}</Typography.Text>
                <Typography.Text type="secondary">
                  {value.ok}/{value.total}
                </Typography.Text>
              </div>
              <Progress
                percent={Number(((value.ok / value.total) * 100).toFixed(0))}
                size="small"
              />
            </Col>
          ))}
        </Row>
      </Card>

      <Card title={`逐条结果（${rows.length}）`} size="small">
        <Table<CaseRow>
          rowKey={(r) => r.id ?? Math.random().toString()}
          size="small"
          dataSource={rows}
          columns={columns}
          pagination={{ pageSize: 15, showSizeChanger: false, size: "small" }}
          scroll={{ x: 720 }}
        />
      </Card>
    </Space>
  );
}
