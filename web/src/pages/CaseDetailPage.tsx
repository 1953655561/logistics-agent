import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  App as AntApp,
  Button,
  Card,
  Collapse,
  Descriptions,
  Empty,
  List,
  Modal,
  Segmented,
  Skeleton,
  Space,
  Tabs,
  Tag,
  Timeline,
  Typography,
} from "antd";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type AskOut, type CaseDetail, type HistoryHint } from "../api/client";
import ApprovalDrawer from "../components/ApprovalDrawer";
import JsonView from "../components/JsonView";
import {
  Money,
  ReviewTag,
  SeverityTag,
  StatusTag,
  VerdictTag,
  formatTime,
  localizeText,
} from "../components/tags";
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

/** 证据渲染：把机器结构翻成人能扫的 chips，而不是把 JSON 直接打出来。 */
function EvidenceView({ evidence }: { evidence: Record<string, unknown> }) {
  const entries = Object.entries(evidence ?? {});
  if (!entries.length) return null;
  return (
    <div className={styles.evidence}>
      <Typography.Text type="secondary">对比：</Typography.Text>
      <Space wrap size={4}>
        {entries.flatMap(([key, value]) => {
          if (key === "suggestions" && Array.isArray(value)) {
            return (value as Array<Record<string, unknown>>).slice(0, 3).map((s, i) => (
              <Tag key={`${key}-${i}`} color="blue">
                {String(s.hs6 ?? "")} · {String(s.name ?? "")} ·{" "}
                {Number(s.confidence ?? 0).toFixed(2)}
              </Tag>
            ));
          }
          if (Array.isArray(value)) {
            return [
              <Tag key={key}>
                {key}：{value.join(" / ")}
              </Tag>,
            ];
          }
          if (value !== null && typeof value === "object") {
            return [
              <Tag key={key}>
                {key}：{JSON.stringify(value)}
              </Tag>,
            ];
          }
          return [
            <Tag key={key}>
              {key}：{String(value)}
            </Tag>,
          ];
        })}
      </Space>
    </div>
  );
}

export default function CaseDetailPage({ caseId, onAudit }: Props) {
  const { message } = AntApp.useApp();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState("issues");
  const [approvalOpen, setApprovalOpen] = useState(false);
  const [sev, setSev] = useState<string>("all");
  const [askState, setAskState] = useState<{
    ruleId: string;
    loading: boolean;
    data?: AskOut;
    error?: string;
  } | null>(null);

  useEffect(() => {
    setTab("issues");
    setApprovalOpen(false);
    setSev("all");
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

  const ingest = useQuery({
    queryKey: ["ingest", caseId],
    queryFn: () => api.getIngest(caseId as string),
    enabled: !!caseId && tab === "ingest",
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

  // 历史提示：按 note 去重，同一句话只出现一次，并把主体合并展示。
  // （后端每个主体各出一条，文案往往相同，直接 join 会出现三段重复。）
  const hintGroups = useMemo(() => {
    const hs =
      ((detail.data as unknown as { history_hints?: HistoryHint[] } | undefined)
        ?.history_hints) ?? [];
    const map = new Map<
      string,
      { note: string; labels: string[]; cases: string[]; seen: number }
    >();
    for (const h of hs) {
      const g = map.get(h.note) ?? { note: h.note, labels: [], cases: [], seen: 0 };
      if (!g.labels.includes(h.label)) g.labels.push(h.label);
      g.seen = Math.max(g.seen, h.seen_cases ?? 0);
      for (const c of h.cases ?? []) if (!g.cases.includes(c)) g.cases.push(c);
      map.set(h.note, g);
    }
    return [...map.values()].map((g) => ({ ...g, cases: g.cases.slice(0, 3) }));
  }, [detail.data]);

  // 三组提示往往指向同一批来源单，按唯一单号去重后再计数
  const hintCaseCount = useMemo(
    () => new Set(hintGroups.flatMap((g) => g.cases)).size,
    [hintGroups],
  );

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
        <Skeleton active paragraph={{ rows: 8 }} />
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
  const counts = { high: 0, mid: 0, low: 0 };
  for (const it of issues) {
    const k: "high" | "mid" | "low" =
      it.severity === "high" || it.severity === "mid" || it.severity === "low"
        ? it.severity
        : "low";
    counts[k] += 1;
  }
  const shownIssues =
    sev === "all" ? issues : issues.filter((it) => (it.severity ?? "low") === sev);

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
      {hintGroups.length ? (
        <Collapse
          size="small"
          className={styles.hints}
          items={[
            {
              key: "hints",
              label: (
                <Space size={6} wrap>
                  <Tag color="blue" style={{ marginInlineEnd: 0 }}>
                    历史提示
                  </Tag>
                  <Typography.Text type="secondary">
                    {hintGroups.length} 组
                    {hintCaseCount ? ` · 涉及 ${hintCaseCount} 票` : ""}
                  </Typography.Text>
                </Space>
              ),
              children: (
                <Space direction="vertical" size={8} style={{ width: "100%" }}>
                  {hintGroups.map((g, i) => (
                    <div key={i}>
                      <Space size={6} wrap>
                        <Tag>{g.labels.join(" / ")}</Tag>
                        <Typography.Text>{g.note}</Typography.Text>
                      </Space>
                      {g.cases.length ? (
                        <div className={styles.hintCases}>
                          来源单：
                          {g.cases.map((cid) => (
                            <Tag key={cid}>{cid}</Tag>
                          ))}
                          {g.seen > g.cases.length ? (
                            <Typography.Text type="secondary">
                              （共 {g.seen} 票，显示前 {g.cases.length} 个）
                            </Typography.Text>
                          ) : null}
                        </div>
                      ) : null}
                    </div>
                  ))}
                </Space>
              ),
            },
          ]}
        />
      ) : null}

      <div className={styles.metaRow}>
        <span className={styles.metaItem}>
          <Typography.Text type="secondary">状态</Typography.Text>
          <StatusTag state={d.state} />
        </span>
        <span className={styles.metaItem}>
          <Typography.Text type="secondary">结论</Typography.Text>
          <VerdictTag verdict={d.verdict} />
        </span>
        <span className={styles.metaItem}>
          <Typography.Text type="secondary">问题</Typography.Text>
          <Typography.Text strong>{d.issue_count ?? 0}</Typography.Text>
        </span>
        <span className={styles.metaItem}>
          <Typography.Text type="secondary">单票成本</Typography.Text>
          <Money value={d.cost} />
        </span>
        <span className={styles.metaItem}>
          <Typography.Text type="secondary">复核</Typography.Text>
          <ReviewTag recommendation={review.recommendation} />
        </span>
        <span className={styles.metaItem}>
          <Typography.Text type="secondary">更新</Typography.Text>
          <Typography.Text>{formatTime(d.updated_at, true)}</Typography.Text>
        </span>
      </div>
      {review.reason ? (
        <div className={styles.reviewLine}>
          <Typography.Text type="secondary">复核意见：</Typography.Text>
          <Typography.Text>{localizeText(review.reason)}</Typography.Text>
        </div>
      ) : null}

      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          {
            key: "issues",
            label: `问题清单 ${issues.length}`,
            children: issues.length ? (
              <>
                <div className={styles.issueFilter}>
                  <Segmented
                    size="small"
                    value={sev}
                    onChange={(v) => setSev(String(v))}
                    options={[
                      { label: `全部 ${issues.length}`, value: "all" },
                      { label: `高 ${counts.high}`, value: "high" },
                      { label: `中 ${counts.mid}`, value: "mid" },
                      { label: `低 ${counts.low}`, value: "low" },
                    ]}
                  />
                </div>
                <List
                  className={styles.list}
                  dataSource={shownIssues}
                  locale={{ emptyText: "该级别没有问题" }}
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
                          依据：
                          {(it.citation_text || it.citation || "").replace(/^依据：/, "")}
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
                        <EvidenceView evidence={it.evidence as Record<string, unknown>} />
                      ) : null}
                    </div>
                  </List.Item>
                )}
                />
              </>
            ) : (
              <Empty description="无问题，可直接申报" />
            ),
          },
          {
            key: "docs",
            label: "单证",
            children: docs.isLoading ? (
              <Skeleton active paragraph={{ rows: 6 }} />
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
            key: "ingest",
            label: "原始单证",
            children: ingest.isLoading ? (
              <Skeleton active paragraph={{ rows: 5 }} />
            ) : ingest.isError ? (
              <Alert type="error" showIcon message={(ingest.error as Error).message} />
            ) : !ingest.data?.available ? (
              <Empty description="本单不是由原始文件上传创建（或没有解析记录）" />
            ) : (
              <Space direction="vertical" size={10} style={{ width: "100%" }}>
                {ingest.data.needs_human ? (
                  <Alert
                    type="warning"
                    showIcon
                    message="有低置信/未识别项：审核结论可用，但建议人工确认原始单证后再放行。"
                  />
                ) : null}
                <Typography.Text type="secondary">
                  识别到 {ingest.data.docs.length} 份单证
                  {ingest.data.missing_docs.length
                    ? `，缺少 ${ingest.data.missing_docs
                        .map((k) => DOC_LABELS[k] ?? k)
                        .join(" / ")}`
                    : "（五单齐套）"}
                  ；共 {ingest.data.files.length} 个文件/页面。
                </Typography.Text>
                <List
                  size="small"
                  dataSource={ingest.data.files}
                  renderItem={(f) => (
                    <List.Item>
                      <Space direction="vertical" size={2} style={{ width: "100%" }}>
                        <Space wrap size={6}>
                          <Typography.Text code>{f.filename}</Typography.Text>
                          {f.doc_type ? (
                            <Tag color="blue">{DOC_LABELS[f.doc_type] ?? f.doc_type}</Tag>
                          ) : (
                            <Tag color="error">未识别单证</Tag>
                          )}
                          <Tag>{f.route || "—"}</Tag>
                          {f.engine ? <Tag>{f.engine}</Tag> : null}
                          {typeof f.confidence === "number" ? (
                            <Tag color={f.confidence >= 0.9 ? "green" : "orange"}>
                              置信 {f.confidence.toFixed(2)}
                            </Tag>
                          ) : null}
                          {f.status && f.status !== "ok" ? (
                            <Tag color="error">{f.status}</Tag>
                          ) : null}
                        </Space>
                        {f.missing.length ? (
                          <Typography.Text type="secondary">
                            缺字段：{f.missing.join("、")}
                          </Typography.Text>
                        ) : null}
                        {f.checks.length ? (
                          <Typography.Text type="secondary">
                            提示：{f.checks.join("；")}
                          </Typography.Text>
                        ) : null}
                      </Space>
                    </List.Item>
                  )}
                />
              </Space>
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
                      children: <ReviewTag recommendation={review.recommendation} />,
                    },
                    { key: "source", label: "来源", children: review.source || "—" },
                    {
                      key: "reason",
                      label: "理由",
                      children: localizeText(review.reason) || "—",
                    },
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
          <Skeleton active paragraph={{ rows: 4 }} />
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
