import { useEffect, useState } from "react";
import {
  Alert,
  App as AntApp,
  Button,
  Card,
  Descriptions,
  Empty,
  List,
  Modal,
  Space,
  Spin,
  Tabs,
  Tag,
  Timeline,
  Typography,
} from "antd";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type AskOut, type CaseDetail, type HistoryHint } from "../api/client";
import ApprovalDrawer from "../components/ApprovalDrawer";
import JsonView from "../components/JsonView";
import { Money, SeverityTag, StatusTag, VerdictTag } from "../components/tags";
import styles from "./CaseDetailPage.module.css";

type Issue = NonNullable<CaseDetail["issues"]>[number];
type Step = NonNullable<CaseDetail["steps"]>[number];
type Review = NonNullable<CaseDetail["review"]>;

interface Props {
  caseId: string | null;
  onAudit?: (id: string) => void;
}

const DOC_LABELS: Record<string, string> = {
  contract: "合同",
  invoice: "商业发票",
  packing_list: "装箱单",
  bl: "提单",
  declaration: "报关单",
};

export default function CaseDetailPage({ caseId, onAudit }: Props) {
  const { message } = AntApp.useApp();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState("issues");
  const [approvalOpen, setApprovalOpen] = useState(false);
  const [askState, setAskState] = useState<{
    ruleId: string;
    loading: boolean;
    data?: AskOut;
    error?: string;
  } | null>(null);

  useEffect(() => {
    setTab("issues");
    setApprovalOpen(false);
  }, [caseId]);

  const detail = useQuery({
    queryKey: ["case", caseId],
    queryFn: () => api.getCase(caseId as string),
    enabled: !!caseId,
  });

  const docs = useQuery({
    queryKey: ["docs", caseId],
    queryFn: () => api.getDocs(caseId as string),
    enabled: !!caseId && tab === "docs",
  });

  const reAudit = useMutation({
    mutationFn: (id: string) => api.audit(id),
    onSuccess: (data) => {
      message.success("已重新审核");
      queryClient.setQueryData(["case", data.case_id], data);
      queryClient.invalidateQueries({ queryKey: ["cases"] });
      onAudit?.(data.case_id);
    },
    onError: (err: Error) => message.error(err.message),
  });

  if (!caseId) {
    return (
      <Card className={styles.card} title="单票详情">
        <Empty description="从左侧选择一票审核单" />
      </Card>
    );
  }

  if (detail.isLoading) {
    return (
      <Card className={styles.card} title={`单票详情 · ${caseId}`}>
        <div className={styles.center}><Spin /></div>
      </Card>
    );
  }

  if (detail.isError) {
    return (
      <Card className={styles.card} title={`单票详情 · ${caseId}`}>
        <Alert type="error" showIcon message={(detail.error as Error).message} />
      </Card>
    );
  }

  const d = detail.data as CaseDetail;
  const review = (d.review ?? {}) as Review;
  const issues = d.issues ?? [];
  const steps = d.steps ?? [];
  const guard = d.guard ?? [];
  // history_hints 是 v1.6 新字段，生成类型里还没有，这里局部断言
  const hints = ((d as unknown as { history_hints?: HistoryHint[] }).history_hints) ?? [];

  const askWhy = (ruleId: string, fieldPath = "") => {
    const field = fieldPath ? `（字段 ${fieldPath}）` : "";
    setAskState({ ruleId, loading: true });
    api
      .ask(d.case_id, `${ruleId} 这条为什么算问题${field}？该怎么改？`)
      .then((data) => setAskState({ ruleId, loading: false, data }))
      .catch((err: Error) => setAskState({ ruleId, loading: false, error: err.message }));
  };

  return (
    <Card
      className={styles.card}
      title={
        <Space wrap>
          <span className={styles.caseId}>{d.case_id}</span>
          <StatusTag state={d.state} />
          <VerdictTag verdict={d.verdict} />
        </Space>
      }
      extra={
        <Space>
          <Button size="small" onClick={() => detail.refetch()} loading={detail.isFetching}>
            刷新
          </Button>
          {d.state === "PENDING_APPROVAL" ? (
            <Button type="primary" size="small" onClick={() => setApprovalOpen(true)}>
              人工审批
            </Button>
          ) : null}
          {d.state === "RETURNED" ? (
            <Button
              size="small"
              loading={reAudit.isPending}
              onClick={() => reAudit.mutate(d.case_id)}
            >
              补正后重审
            </Button>
          ) : null}
        </Space>
      }
    >
      <Typography.Title level={5} className={styles.title}>
        {d.title}
      </Typography.Title>
      <Typography.Paragraph className={styles.summary}>
        {d.summary || "—"}
      </Typography.Paragraph>

      {d.degraded ? (
        <Alert
          className={styles.alert}
          type="warning"
          showIcon
          message="本次审核有降级（步数预算 / 模型 / 工具异常），结论保留但建议人工确认。"
        />
      ) : null}
      {guard.length ? (
        <Alert
          className={styles.alert}
          type="warning"
          showIcon
          message={`护栏命中 ${guard.length} 条：${guard
            .map((g) => String((g as { kind?: string }).kind ?? ""))
            .filter(Boolean)
            .join("、")}`}
        />
      ) : null}
      {hints.length ? (
        <Alert
          className={styles.alert}
          type="info"
          showIcon
          message={`历史提示：${hints.map((h) => h.note).join("；")}`}
          description={
            <Space wrap size={4}>
              <Typography.Text type="secondary">来源单：</Typography.Text>
              {(hints[0].cases ?? []).map((cid) => (
                <Tag key={cid}>{cid}</Tag>
              ))}
            </Space>
          }
        />
      ) : null}

      <Descriptions
        size="small"
        column={2}
        colon={false}
        className={styles.meta}
        items={[
          { key: "state", label: "状态", children: <StatusTag state={d.state} /> },
          { key: "verdict", label: "结论", children: <VerdictTag verdict={d.verdict} /> },
          { key: "issues", label: "问题数", children: d.issue_count },
          { key: "cost", label: "单票成本", children: <Money value={d.cost} /> },
          {
            key: "review",
            label: "复核",
            span: 2,
            children: review.recommendation ? (
              <Space wrap>
                <Tag>{review.recommendation}</Tag>
                <Typography.Text type="secondary">
                  {review.reason || "—"}
                </Typography.Text>
              </Space>
            ) : (
              "—"
            ),
          },
          { key: "updated", label: "更新时间", span: 2, children: d.updated_at || "—" },
        ]}
      />

      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          {
            key: "issues",
            label: `问题清单 ${issues.length}`,
            children: issues.length ? (
              <List
                className={styles.list}
                dataSource={issues}
                renderItem={(it: Issue) => (
                  <List.Item className={`${styles.issue} ${styles[it.severity || "low"] ?? ""}`}>
                    <div className={styles.issueBody}>
                      <Space wrap size={6}>
                        <Typography.Text code>{it.rule_id}</Typography.Text>
                        <SeverityTag severity={it.severity} />
                        <Typography.Text strong>{it.message}</Typography.Text>
                      </Space>
                      {it.citation_text || it.citation ? (
                        <div className={styles.cite}>
                          依据：{it.citation_text || it.citation}
                          {it.citation_chunk ? (
                            <Typography.Text code className={styles.chunk}>
                              {it.citation_chunk}
                            </Typography.Text>
                          ) : null}
                        </div>
                      ) : null}
                      {it.suggestion ? (
                        <div className={styles.suggest}>建议：{it.suggestion}</div>
                      ) : null}
                      {it.rule_id ? (
                        <Button
                          size="small"
                          type="link"
                          style={{ paddingLeft: 0 }}
                          onClick={() => askWhy(String(it.rule_id), String(it.field_path ?? ""))}
                        >
                          为什么？
                        </Button>
                      ) : null}
                      {it.evidence && Object.keys(it.evidence).length ? (
                        <div className={styles.cite}>
                          对比：
                          {Object.entries(it.evidence)
                            .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
                            .join("；")}
                        </div>
                      ) : null}
                    </div>
                  </List.Item>
                )}
              />
            ) : (
              <Empty description="无问题，可直接申报" />
            ),
          },
          {
            key: "docs",
            label: "单证",
            children: docs.isLoading ? (
              <div className={styles.center}><Spin /></div>
            ) : docs.isError ? (
              <Alert type="error" showIcon message={(docs.error as Error).message} />
            ) : (
              <Tabs
                size="small"
                items={Object.entries(docs.data?.docs ?? {}).map(([key, value]) => ({
                  key,
                  label: DOC_LABELS[key] ?? key,
                  children: <JsonView data={value} />,
                }))}
              />
            ),
          },
          {
            key: "trace",
            label: `处理轨迹 ${steps.length}`,
            children: steps.length ? (
              <Timeline
                items={steps.map((s: Step, idx) => ({
                  color: s.ok === false ? "red" : "blue",
                  children: (
                    <div>
                      <Space wrap size={6}>
                        <Typography.Text strong>
                          {idx + 1}. {s.name}
                        </Typography.Text>
                        <Typography.Text code>{s.tool || "—"}</Typography.Text>
                        <Typography.Text type="secondary">
                          {Number(s.ms ?? 0).toFixed(2)} ms
                        </Typography.Text>
                        {s.ok === false ? <Tag color="error">失败</Tag> : null}
                      </Space>
                      {s.error ? <div className={styles.cite}>{s.error}</div> : null}
                    </div>
                  ),
                }))}
              />
            ) : (
              <Empty description="暂无轨迹" />
            ),
          },
          {
            key: "review",
            label: "复核与护栏",
            children: (
              <Space direction="vertical" size={14} style={{ width: "100%" }}>
                <Descriptions
                  size="small"
                  column={1}
                  bordered
                  items={[
                    { key: "agree", label: "是否同意", children: review.agree ? "同意" : "有疑问" },
                    {
                      key: "rec",
                      label: "建议",
                      children: review.recommendation || "—",
                    },
                    { key: "source", label: "来源", children: review.source || "—" },
                    { key: "reason", label: "理由", children: review.reason || "—" },
                  ]}
                />
                {(review.doubts ?? []).length ? (
                  <div>
                    <Typography.Text strong>阻断性疑问</Typography.Text>
                    <List
                      size="small"
                      dataSource={review.doubts ?? []}
                      renderItem={(x) => (
                        <List.Item>
                          <Space>
                            <Tag color="error">{x.code}</Tag>
                            {x.detail}
                          </Space>
                        </List.Item>
                      )}
                    />
                  </div>
                ) : null}
                {(review.observations ?? []).length ? (
                  <div>
                    <Typography.Text strong>过判观察（不改变结论）</Typography.Text>
                    <List
                      size="small"
                      dataSource={review.observations ?? []}
                      renderItem={(x) => (
                        <List.Item>
                          <Space>
                            <Tag color="warning">{x.code}</Tag>
                            {x.detail}
                          </Space>
                        </List.Item>
                      )}
                    />
                  </div>
                ) : null}
                {guard.length ? (
                  <div>
                    <Typography.Text strong>护栏记录</Typography.Text>
                    <List
                      size="small"
                      dataSource={guard}
                      renderItem={(g) => (
                        <List.Item>
                          <Space wrap>
                            <Tag>{String((g as { kind?: string }).kind ?? "")}</Tag>
                            <Typography.Text type="secondary">
                              {String((g as { path?: string }).path ?? "")}
                            </Typography.Text>
                            {String((g as { detail?: string }).detail ?? "")}
                          </Space>
                        </List.Item>
                      )}
                    />
                  </div>
                ) : null}
              </Space>
            ),
          },
        ]}
      />

      <ApprovalDrawer
        open={approvalOpen}
        caseId={d.case_id}
        verdict={d.verdict}
        onClose={() => setApprovalOpen(false)}
      />

      <Modal
        open={!!askState}
        title={askState ? `追问 · ${askState.ruleId}` : ""}
        footer={null}
        onCancel={() => setAskState(null)}
        width={720}
      >
        {askState?.loading ? (
          <div className={styles.center}><Spin /></div>
        ) : askState?.error ? (
          <Alert type="error" showIcon message={askState.error} />
        ) : askState?.data ? (
          <Space direction="vertical" size={10} style={{ width: "100%" }}>
            <Typography.Paragraph className={styles.summary}>
              {askState.data.answer}
            </Typography.Paragraph>
            <Typography.Text type="secondary">
              置信：{askState.data.confidence}
              {askState.data.uncited ? "（无证据支撑）" : ""} · 工具：
              {askState.data.tools_called.join("、") || "—"}
            </Typography.Text>
            {askState.data.evidence.length ? (
              <div>
                <Typography.Text strong>证据</Typography.Text>
                {askState.data.evidence.map((ev, i) => (
                  <div key={i} className={styles.cite}>
                    {ev.fields?.length
                      ? ev.fields
                          .map((f) => `${f.path} = ${String(f.value)}`)
                          .join("；")
                      : JSON.stringify(ev.evidence)}
                  </div>
                ))}
              </div>
            ) : null}
            {askState.data.citations.length ? (
              <div>
                <Typography.Text strong>引用</Typography.Text>
                {askState.data.citations.map((c) => (
                  <div key={c.chunk_id} className={styles.cite}>
                    {c.chunk_id} · {c.excerpt}
                  </div>
                ))}
              </div>
            ) : null}
          </Space>
        ) : null}
      </Modal>
    </Card>
  );
}
