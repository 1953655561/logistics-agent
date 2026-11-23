import type { components } from "../types/api";

export type CaseSummary = components["schemas"]["CaseSummary"];
export type CaseDetail = components["schemas"]["CaseDetail"];
export type Scenario = components["schemas"]["ScenarioOut"];
export type Metrics = components["schemas"]["MetricsOut"];
export type RuleInfo = components["schemas"]["RuleOut"];
export type DocsOut = components["schemas"]["DocsOut"];

/** 原始文件解析记录（/api/cases/{id}/ingest） */
export interface IngestFileMeta {
  filename: string;
  route: string;
  doc_type: string | null;
  sheet: string | null;
  page: number | null;
  engine: string | null;
  confidence: number | null;
  ocr_confidence: number | null;
  missing: string[];
  checks: string[];
  status: string;
}

export interface IngestMeta {
  case_id: string;
  available?: boolean;
  docs: string[];
  missing_docs: string[];
  needs_human: boolean;
  files: IngestFileMeta[];
}

export type IngestResult = CaseDetail & { ingest: IngestMeta };

/** 追问的返回（后端 /api/cases/{id}/ask）。手写而不是生成，避免为一个小结构重跑 OpenAPI。 */
export interface AskOut {
  case_id: string;
  question: string;
  intent: string;
  answer: string;
  evidence: {
    rule_id: string;
    field_path: string;
    evidence: Record<string, unknown>;
    /** 后端已展平的字段（path = value），前端优先用它渲染，避免一坨 JSON */
    fields?: { path: string; value: unknown }[];
  }[];
  citations: { rule_id: string; chunk_id: string; section: string; excerpt: string }[];
  tools_called: string[];
  confidence: string;
  uncited: boolean;
  guard: unknown[];
}

/** 历史提示（后端 history_hints） */
export interface HistoryHint {
  kind: string;
  label: string;
  party: string;
  seen_cases: number;
  cases: string[];
  top_rules: { rule_id: string; count: number }[];
  note: string;
  last_seen: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body?.detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail || `HTTP ${res.status}`);
  }
  return (await res.json()) as T;
}

/** multipart 上传：不要手动设 Content-Type，浏览器要自己带 boundary。 */
async function requestForm<T>(path: string, form: FormData): Promise<T> {
  const res = await fetch(path, { method: "POST", body: form });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body?.detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail || `HTTP ${res.status}`);
  }
  return (await res.json()) as T;
}

export const api = {
  health: () =>
    request<{
      status: string;
      scenarios: number;
      rules: number;
      model?: {
        offline: boolean;
        active: string;
        llm: string;
        routes: Record<string, string>;
        tiers: Record<string, string>;
      };
    }>("/api/health"),
  listCases: (limit = 50) => request<CaseSummary[]>(`/api/cases?limit=${limit}`),
  getCase: (id: string) => request<CaseDetail>(`/api/cases/${encodeURIComponent(id)}`),
  getDocs: (id: string) => request<DocsOut>(`/api/cases/${encodeURIComponent(id)}/docs`),
  getTrace: (id: string) =>
    request<Record<string, unknown>[]>(`/api/cases/${encodeURIComponent(id)}/trace`),
  audit: (id: string) =>
    request<CaseDetail>(`/api/cases/${encodeURIComponent(id)}/audit`, {
      method: "POST",
      body: "{}",
    }),
  importCase: (caseId: string, docs: Record<string, unknown>) =>
    request<CaseDetail>("/api/cases/import", {
      method: "POST",
      body: JSON.stringify({ case_id: caseId, docs }),
    }),
  ingestFiles: (caseId: string, files: File[]) => {
    const form = new FormData();
    files.forEach((file) => form.append("files", file));
    if (caseId.trim()) form.append("case_id", caseId.trim());
    return requestForm<IngestResult>("/api/ingest", form);
  },
  getIngest: (id: string) =>
    request<IngestMeta>(`/api/cases/${encodeURIComponent(id)}/ingest`),
  approve: (id: string, approved: boolean, comment: string) =>
    request<CaseDetail>(`/api/cases/${encodeURIComponent(id)}/approve`, {
      method: "POST",
      body: JSON.stringify({ approved, comment }),
    }),
  ask: (id: string, question: string) =>
    request<AskOut>(`/api/cases/${encodeURIComponent(id)}/ask`, {
      method: "POST",
      body: JSON.stringify({ question }),
    }),
  listScenarios: () => request<Scenario[]>("/api/scenarios"),
  listRules: () => request<RuleInfo[]>("/api/rules"),
  metrics: () => request<Metrics>("/api/metrics"),
};
