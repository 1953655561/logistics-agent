import { useEffect, useMemo, useState } from "react";
import {
  App as AntApp,
  Button,
  Card,
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
import { Money, StatusTag, VerdictTag } from "../components/tags";
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

  const cases = useQuery({ queryKey: ["cases"], queryFn: () => api.listCases() });
  const scenarios = useQuery({ queryKey: ["scenarios"], queryFn: api.listScenarios });

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
        width: 104,
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
        width: 148,
        ellipsis: true,
        render: (v: string) => <Typography.Text type="secondary">{v || "—"}</Typography.Text>,
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

      <Table<CaseSummary>
        className={styles.table}
        rowKey="case_id"
        size="middle"
        loading={cases.isLoading}
        dataSource={cases.data ?? []}
        columns={columns}
        pagination={{ pageSize: 10, showSizeChanger: false, size: "small" }}
        scroll={{ x: 760 }}
        locale={{ emptyText: "暂无审核单，点「新建审核」开始" }}
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
