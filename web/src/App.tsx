import { useState } from "react";
import { Layout, Segmented, Space, Tag, Tooltip, Typography } from "antd";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api/client";
import CaseListPage from "./pages/CaseListPage";
import CaseDetailPage from "./pages/CaseDetailPage";
import MetricsPage from "./pages/MetricsPage";
import styles from "./App.module.css";

type View = "console" | "metrics";

export default function App() {
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });
  const model = health.data?.model;
  const offline = model?.offline ?? true;
  const tierNames = model?.tiers
    ? Object.entries(model.tiers).map(([tier, name]) => `${tier}=${name}`).join(" / ")
    : "";

  const params = new URLSearchParams(window.location.search);
  const [view, setView] = useState<View>(
    params.get("view") === "metrics" ? "metrics" : "console",
  );
  const [selectedId, setSelectedId] = useState<string | null>(params.get("case"));

  const selectCase = (id: string) => {
    setSelectedId(id);
    setView("console");
    const next = new URLSearchParams(window.location.search);
    next.set("case", id);
    next.delete("view");
    window.history.replaceState(null, "", `?${next.toString()}`);
  };

  const changeView = (v: View) => {
    setView(v);
    const next = new URLSearchParams(window.location.search);
    if (v === "metrics") next.set("view", "metrics");
    else next.delete("view");
    window.history.replaceState(null, "", `?${next.toString()}`);
  };

  return (
    <Layout className={styles.shell}>
      <Layout.Header className={styles.header}>
        <Space size={12} align="center">
          <span className={styles.logoMark}>审</span>
          <div>
            <Typography.Title level={4} className={styles.brand}>
              关务智能审核台
            </Typography.Title>
            <div className={styles.sub}>进口一般贸易 · 单证智能审核</div>
          </div>
        </Space>
        <Space size={16}>
          <Segmented<View>
            value={view}
            onChange={(v) => changeView(v)}
            options={[
              { label: "审核台", value: "console" },
              { label: "评测指标", value: "metrics" },
            ]}
          />
          {offline ? (
            <Tooltip title={`模型未配置，全部走 MockLLM（可复现、零成本）。${tierNames}`}>
              <Tag color="green">离线 mock</Tag>
            </Tooltip>
          ) : (
            <Tooltip title={`路由：${JSON.stringify(model?.routes ?? {})}`}>
              <Tag color="blue">在线模型 · {tierNames || model?.active}</Tag>
            </Tooltip>
          )}
        </Space>
      </Layout.Header>

      <Layout.Content className={styles.content}>
        {view === "console" ? (
          <div className={styles.grid}>
            <CaseListPage
              selectedId={selectedId}
              onSelect={selectCase}
            />
            <CaseDetailPage
              caseId={selectedId}
              onAudit={selectCase}
            />
          </div>
        ) : (
          <MetricsPage />
        )}
      </Layout.Content>
    </Layout>
  );
}
