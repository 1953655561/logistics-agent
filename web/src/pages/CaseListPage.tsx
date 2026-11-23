import { useEffect, useMemo, useState } from "react";
import {
  App as AntApp,
  Button,
  Card,
  Input,
  Segmented,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type CaseSummary } from "../api/client";
import ImportCaseModal from "../components/ImportCaseModal";
import { Money, StatusTag, VerdictTag, formatTime } from "../components/tags";
import styles from "./CaseListPage.module.css";

interface Props {
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export default function CaseListPage({ selectedId, onSelect }: Props) {
  const { message } = AntApp.useApp();
  const queryClient = useQueryClient();
  const [scenarioId, setScenarioId] = useState<string>("");
  const [importOpen, setImportOpen] = useState(false);
  const [q, setQ] = useState("");
  const [stateFilter, setStateFilter] = useState<string>("all");
  const [page, setPage] = useState(1);

  const cases = useQuery({ queryKey: ["cases"], queryFn: () => api.listCases() });
  const scenarios = useQuery({ queryKey: ["scenarios"], queryFn: api.listScenarios });

  const stateCounts = useMemo(() => {
    const counts: Record<string, number> = { all: (cases.data ?? []).length };
    for (const c of cases.data ?? []) counts[c.state] = (counts[c.state] ?? 0) + 1;
    return counts;
  }, [cases.data]);

  const filtered = useMemo(() => {
    const kw = q.trim().toLowerCase();
    return (cases.data ?? []).filter((c) => {
      const matchQ =
        !kw ||
        c.case_id.toLowerCase().includes(kw) ||
        (c.title ?? "").toLowerCase().includes(kw);
      const matchS = stateFilter === "all" || c.state === stateFilter;
      return matchQ && matchS;
    });
  }, [cases.data, q, stateFilter]);

  useEffect(() => {
    setPage(1);
  }, [q, stateFilter]);

  useEffect(() => {
    if (!scenarioId && scenarios.data?.length) {
      setScenarioId(scenarios.data[0].id);
    }
  }, [scenarioId, scenarios.data]);

  const audit = useMutation({
    mutationFn: (id: string) => api.audit(id),
    onSuccess: (data) => {
      message.success(`审核完成：#${data.case_id} · ${data.verdict}`);
      queryClient.setQueryData(["case", data.case_id], data);
      queryClient.invalidateQueries({ queryKey: ["cases"] });
      onSelect(data.case_id);
    },
    onError: (err: Error) => message.error(err.message),
  });

  const columns = useMemo<ColumnsType<CaseSummary>>(
    () => [
      {
        title: "审核单",
        dataIndex: "case_id",
        width: 168,
        ellipsis: { showTitle: true },
        render: (v: string) => <Typography.Text code>{v}</Typography.Text>,
      },
      {
        title: "标题",
        dataIndex: "title",
        ellipsis: true,
      },
      {
        title: "状态",
        dataIndex: "state",
        width: 92,
        render: (v: string) => <StatusTag state={v} />,
      },
      {
        title: "结论",
        dataIndex: "verdict",
        width: 86,
        render: (v: string) => <VerdictTag verdict={v} />,
      },
      {
        title: "问题",
        dataIndex: "issue_count",
        width: 62,
        align: "right",
      },
      {
        title: "成本",
        dataIndex: "cost",
        width: 96,
        align: "right",
        render: (v: number) => <Money value={v} />,
      },
      {
        title: "更新",
        dataIndex: "updated_at",
        width: 116,
        align: "right",
        render: (v: string) => (
          <Typography.Text type="secondary">{formatTime(v)}</Typography.Text>
        ),
      },
    ],
    [],
  );

  const selectedScenario = scenarios.data?.find((s) => s.id === scenarioId);

  return (
    <Card
      className={styles.card}
      title={
        <Space>
          <span>审核单</span>
          <Tag>{cases.data?.length ?? 0}</Tag>
        </Space>
      }
      extra={
        <Button size="small" onClick={() => cases.refetch()} loading={cases.isFetching}>
          刷新
        </Button>
      }
    >
      <div className={styles.toolbar}>
        <Select
          className={styles.scenario}
          value={scenarioId || undefined}
          onChange={setScenarioId}
          placeholder="选择合成用例"
          loading={scenarios.isLoading}
          showSearch
          optionFilterProp="label"
          options={(scenarios.data ?? []).map((s) => ({
            value: s.id,
            label: `${s.id} · ${s.title}`,
          }))}
        />
        <Button
          type="primary"
          loading={audit.isPending}
          disabled={!scenarioId}
          onClick={() => scenarioId && audit.mutate(scenarioId)}
        >
          新建审核
        </Button>
        <Button onClick={() => setImportOpen(true)}>导入单证</Button>
        {selectedScenario ? (
          <Tag color="blue">期望 {selectedScenario.expected}</Tag>
        ) : null}
      </div>

      <div className={styles.filters}>
        <Input
          allowClear
          className={styles.search}
          placeholder="搜索单号或标题"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <Segmented
          size="small"
          value={stateFilter}
          onChange={(v) => setStateFilter(String(v))}
          options={[
            { label: `全部 ${stateCounts.all ?? 0}`, value: "all" },
            { label: `待审批 ${stateCounts.PENDING_APPROVAL ?? 0}`, value: "PENDING_APPROVAL" },
            { label: `已通过 ${stateCounts.APPROVED ?? 0}`, value: "APPROVED" },
            { label: `已退回 ${stateCounts.RETURNED ?? 0}`, value: "RETURNED" },
          ]}
        />
        {q || stateFilter !== "all" ? (
          <Typography.Text type="secondary">匹配 {filtered.length} 条</Typography.Text>
        ) : null}
      </div>

      <Table<CaseSummary>
        className={styles.table}
        rowKey="case_id"
        size="middle"
        loading={cases.isLoading}
        dataSource={filtered}
        columns={columns}
        pagination={{
          pageSize: 10,
          current: page,
          onChange: setPage,
          showSizeChanger: false,
          size: "small",
        }}
        scroll={{ x: 820 }}
        locale={{
          emptyText:
            q || stateFilter !== "all"
              ? "没有匹配的审核单"
              : "暂无审核单，点「新建审核」开始",
        }}
        rowClassName={(r) => (r.case_id === selectedId ? styles.rowActive : "")}
        onRow={(r) => ({
          onClick: () => onSelect(r.case_id),
          style: { cursor: "pointer" },
        })}
      />

      <ImportCaseModal
        open={importOpen}
        onClose={() => setImportOpen(false)}
        onImported={(id) => onSelect(id)}
      />
    </Card>
  );
}
